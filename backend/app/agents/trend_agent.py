"""趋势官 Agent — 基于真实 Google Trends + B站数据的趋势分析

从旧本地趋势官迁移的能力：
  1. Google/B站连接器异常传播：连接器故障抛 ConnectorFetchError，
     本 Agent 捕获后写入 caveats（data_gaps），绝不把故障折叠为"正常零命中"。
  2. data_gaps / caveats：数据缺口、来源缺失、降级状态显式记录并上抛。
  3. unknown 不伪装成确定结论：无数据 / 来源不足时 heat_index 不产出、
     confidence 保持 unknown、lifecycle 保持 unknown，不做默认值掩盖。
  4. 确定性指标计算：综合热度 / 生命周期 / 置信度 / 互动率全部由
     TrendMetrics 在 Python 侧计算，不让 LLM 生成数字。
  5. EvidenceRef 闭环：每条结论绑定可追溯证据（Google 链接 + B站视频 BV），
     结论与证据一致不断链。
  6. Google/B站空数据与失败状态严格区分：no_data（查询无结果）与
     connector 故障（采集失败）是不同的 gap，分别记录。

仍保留 Mock 语义：
  - 输出契约严格为 GitHub 仓库的 FeatureMatrix.model_dump()（冻结 Schema 不改）。
  - 通过 get_trend_agent_class() 提供注册表切换：默认 mock，设
    TREND_AGENT_PROVIDER=real 时启用本真实 Agent（可回退到 Mock）。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from app.engine.strict_mode import resolve_provider

from ..data.bilibili_hot import BilibiliConnector
from ..data.errors import ConnectorFetchError
from ..data.google_trends import GoogleTrendsConnector
from ..schemas.evidence import Confidence, EvidenceRef
from ..schemas.feature import FeatureMatrix, TrendItem
from .base_agent import BaseAgent
from .trend_conflict_detector import TrendConflictDetector
from .trend_metrics import SourceSignal, TrendMetrics

# 平台标签（按实际可用来源拼接，不虚构来源）
_PLATFORM_LABEL = {"google_trends": "Google Trends", "bilibili_ranking": "B站"}
_CONFIDENCE_MAP = {
    "high": Confidence.HIGH,
    "medium": Confidence.MEDIUM,
    "low": Confidence.LOW,
    "unknown": Confidence.UNKNOWN,
}


class TrendAgent(BaseAgent):
    """趋势官 — Trend Intelligence Agent（真实数据多源版）"""

    name = "trend"
    description = "市场研究总监，负责全球消费趋势感知与预判（Google+B站）"

    def __init__(
        self,
        config: dict | None = None,
        google_connector: Any | None = None,
        bilibili_connector: Any | None = None,
    ):
        super().__init__(config)
        self.connector = google_connector or GoogleTrendsConnector()
        self.google = self.connector
        self.bilibili = bilibili_connector or BilibiliConnector()
        self._metrics = TrendMetrics()
        self._detector = TrendConflictDetector()
        self.llm_api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """执行趋势分析。

        context 输入（两种契约兼容）:
            编排层（graph 节点）: brief（Brief dict）、feedback
            独立直连: keywords、category、geo、market

        输出: GitHub 仓库 FeatureMatrix.model_dump()（含 evidence_refs/caveats/confidence）。
        """
        brief = context.get("brief") or {}
        category = brief.get("category") or context.get("category", "general")
        # 区分"未传 market"与"显式传入"：raw_market 记录原始输入，
        # market 解析为最终区域（缺省回退 global），避免把显式 CN 误记 gap。
        raw_market = brief.get("market")
        if raw_market is None:
            raw_market = context.get("market")
        market = raw_market if raw_market not in (None, "") else "global"
        geo = context.get("geo", "")
        keywords = context.get("keywords") or [category]
        region_label = geo or market

        data_gaps: list[str] = []
        if category in ("", "未指定"):
            data_gaps.append("category 未指定，使用兼容默认值")
        if raw_market in (None, ""):
            data_gaps.append("market 未指定，使用默认值")

        trend_items: list[TrendItem] = []
        all_evidence: list[EvidenceRef] = []
        all_scores: list = []
        all_caveats: list[str] = []

        for kw in keywords[:5]:  # Google Trends 单次最多5个关键词
            signals, gaps, caveats = await self._collect_signals(
                kw, market, geo, region_label
            )
            data_gaps.extend(gaps)
            all_caveats.extend(caveats)

            if not signals:
                data_gaps.append(f"所有数据源对「{kw}」均不可用")
                continue

            source_scores = [
                self._metrics.compute_source_score(s) for s in signals
            ]
            heat_index = self._metrics.compute_heat_index(source_scores)
            lifecycle = self._metrics.judge_lifecycle(source_scores)
            conflicts = self._detector.detect(source_scores)

            all_scores.extend(source_scores)
            for c in conflicts:
                all_caveats.append(f"「{kw}」{c.description}")

            all_evidence.extend(self._build_evidence_refs(kw, signals))

            # heat_index 无法计算（有效来源不足）：不得伪造热度，只记 gap。
            if heat_index is None:
                data_gaps.append(f"「{kw}」有效数据源不足，无法计算综合热度，不产出结论")
                continue

            trend_items.append(TrendItem(
                keyword=kw,
                heat_index=round(heat_index, 1),
                platform=self._platform_label(signals),
                region=region_label,
                lifecycle=lifecycle,
            ))

        caveats = list(dict.fromkeys(data_gaps + all_caveats))

        # 汇总置信度：无结论 → unknown；否则按全部有效来源确定性评估
        if not trend_items:
            confidence_enum = Confidence.UNKNOWN
        else:
            top = trend_items[0]
            overall_conf = self._metrics.assess_confidence(
                all_scores, top.heat_index, top.lifecycle
            )
            confidence_enum = _CONFIDENCE_MAP.get(overall_conf, Confidence.UNKNOWN)

        summary = self._generate_summary(trend_items, category, region_label)

        matrix = FeatureMatrix(
            category=category,
            region=region_label,
            trends=trend_items,
            summary=summary,
            analysis_date=datetime.now(timezone.utc).date().isoformat(),
            evidence_refs=all_evidence,
            confidence=confidence_enum,
            caveats=caveats,
        )
        return matrix.model_dump()

    # ── 数据采集（统一为 SourceSignal，异常/空数据进 gap，不伪造）────────

    async def _collect_signals(
        self, kw: str, market: str, geo: str, region_label: str
    ) -> tuple[list[SourceSignal], list[str], list[str]]:
        signals: list[SourceSignal] = []
        gaps: list[str] = []
        caveats: list[str] = []
        tasks: list = []

        if self.google is not None:
            tasks.append(self._fetch_google_signal(kw, geo or market, region_label))
        if self.bilibili is not None:
            tasks.append(self._fetch_bilibili_signal(kw, region_label))
        if not tasks:
            gaps.append("无可用数据源（连接器未配置）")
            return signals, gaps, caveats

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                # 连接器故障：带关键词归属写入 gap，不折叠为零命中
                name = getattr(res, "connector", "connector")
                gaps.append(f"{name} 对「{kw}」采集失败: {res}")
                continue
            signal, gap, cav = res
            if signal is not None:
                signals.append(signal)
            if gap:
                gaps.append(gap)
            caveats.extend(cav)
        return signals, gaps, caveats

    async def _fetch_google_signal(
        self, kw: str, geo: str, region_label: str
    ) -> tuple[SourceSignal | None, str | None, list[str]]:
        """Google Trends 采集。三种状态严格区分：
          - 连接器故障（抛异常）→ (None, gap)
          - 查询无数据（no_data / 指标全 None）→ (None, gap)
          - 正常数据 → (SourceSignal, None)
        """
        try:
            result = await asyncio.to_thread(
                self.google.compute_heat_index, kw, geo=geo
            )
        except ConnectorFetchError as e:
            return None, f"google_trends 对「{kw}」采集失败: {e}", []
        except Exception as e:  # noqa: BLE001 — 连接器故障不阻塞整体
            return None, f"google_trends 对「{kw}」数据不可用: {e}", []

        # 空数据检测：不得把无数据误报成 heat_index=0 的正常结果
        if result.get("no_data") or (
            result.get("level") is None and result.get("heat_index") is None
        ):
            return None, (
                f"google_trends 未查询到「{kw}」在 {geo or 'global'} 的数据"
                f"（搜索量过低或关键词无结果）"
            ), []

        level = result.get("level")
        data_quality = "low" if level is not None and level < 5 else "high"

        signal = SourceSignal(
            source="google_trends",
            keyword=kw,
            region=geo or "global",
            observed_at=datetime.now(timezone.utc).isoformat(),
            raw_metrics={
                "level": level,
                "growth": result.get("growth"),
                "breadth": result.get("breadth"),
                "heat_index": result.get("heat_index"),
                "lifecycle": result.get("lifecycle", "unknown"),
                "timeframe": "today 3-m",
            },
            data_quality=data_quality,
            evidence_id=f"google_trends:{kw}",
        )
        return signal, None, []

    async def _fetch_bilibili_signal(
        self, kw: str, region_label: str
    ) -> tuple[SourceSignal | None, str | None, list[str]]:
        """B站采集。故障抛异常 → gap；部分分区失败 → 降级 + caveat；
        查询成功零命中 → 正常信号（low quality），不抛异常。"""
        try:
            result = await asyncio.to_thread(self.bilibili.search_keyword, kw)
        except ConnectorFetchError as e:
            return None, f"bilibili_ranking 对「{kw}」采集失败: {e}", []
        except Exception as e:  # noqa: BLE001
            return None, f"bilibili_ranking 对「{kw}」数据不可用: {e}", []

        caveats: list[str] = []
        failed_parts = result.get("failed_partitions", []) or []
        if failed_parts:
            caveats.append(
                f"B站分区「{'、'.join(failed_parts)}」采集失败，"
                f"结论基于剩余分区，覆盖不完整"
            )

        total_views = result.get("total_views", 0)
        total_results = result.get("total_results", 0)
        videos = result.get("top_videos", []) or []
        scanned = result.get("scanned_videos")

        normalized = {}
        if videos:
            normalized["engagement_rate"] = self._metrics.compute_engagement_rate(
                total_views,
                sum(v.get("like", 0) for v in videos),
                sum(v.get("danmaku", 0) for v in videos),
            )

        signal = SourceSignal(
            source="bilibili_ranking",
            keyword=kw,
            region="CN",
            observed_at=datetime.now(timezone.utc).isoformat(),
            raw_metrics={
                "total_views": total_views,
                "total_results": total_results,
                "avg_views": result.get("avg_views"),
                "scanned_videos": scanned,
                "top_videos": videos[:5],
                "failed_partitions": failed_parts,
            },
            normalized_metrics=normalized,
            data_quality="high" if total_results > 0 else "low",
            evidence_id=f"bilibili:{kw}",
        )
        return signal, None, caveats

    # ── 证据链闭环 ─────────────────────────────────────────

    def _build_evidence_refs(
        self, kw: str, signals: list[SourceSignal]
    ) -> list[EvidenceRef]:
        """从 SourceSignal 构建 GitHub EvidenceRef 列表（url/title/snippet 闭环）。"""
        refs: list[EvidenceRef] = []
        for signal in signals:
            raw = signal.raw_metrics
            if signal.source == "google_trends":
                refs.append(EvidenceRef(
                    url=(
                        f"https://trends.google.com/trends/explore?q={kw}"
                        f"&geo={signal.region}"
                    ),
                    title=f"Google Trends: {kw}",
                    snippet=(
                        f"近7天热度 {raw.get('level')}，环比增长 {raw.get('growth')}%，"
                        f"关联上升查询 {raw.get('breadth')} 个，"
                        f"生命周期: {raw.get('lifecycle')}"
                    ),
                ))
            elif signal.source == "bilibili_ranking":
                # 视频级证据：每条真实视频一条 EvidenceRef，可追溯核验
                for v in raw.get("top_videos", []) or []:
                    bvid = v.get("bvid", "")
                    if not bvid:
                        continue
                    refs.append(EvidenceRef(
                        url=v.get("url") or f"https://www.bilibili.com/video/{bvid}",
                        title=v.get("title", "未知标题"),
                        snippet=(
                            f"播放{v.get('view', 0)} · 分区{v.get('tname', '未知')}"
                        ),
                    ))
                refs.append(EvidenceRef(
                    url=f"https://www.bilibili.com/search?keyword={kw}",
                    title=f"B站分区排行: {kw}",
                    snippet=(
                        f"匹配 {raw.get('total_results', 0)} 个视频，"
                        f"总播放 {raw.get('total_views', 0)}"
                    ),
                ))
        return refs

    # ── 摘要与辅助 ─────────────────────────────────────────

    def _platform_label(self, signals: list[SourceSignal]) -> str:
        labels = [_PLATFORM_LABEL[s.source] for s in signals if s.source in _PLATFORM_LABEL]
        return " + ".join(labels) if labels else "多源"

    def _generate_summary(
        self, items: list[TrendItem], category: str, region: str
    ) -> str:
        """生成趋势摘要。有 LLM Key 时走模型增强，否则规则引擎兜底。"""
        if not items:
            return (
                f"{category} 品类在 {region} 市场暂无有效趋势数据"
                f"（数据源不足或未查询到结果），建议补数后重试。"
            )

        top = items[0]
        rising = [t for t in items if t.lifecycle == "rising"]

        rule_based = (
            f"{category} 品类趋势扫描（{region}）："
            f"当前最热关键词「{top.keyword}」（热度指数 {top.heat_index:.0f}，"
            f"{top.lifecycle} 阶段）。"
        )
        if rising:
            names = "、".join(t.keyword for t in rising)
            rule_based += f"处于上升期的关键词：{names}，建议优先关注。"
        else:
            rule_based += "暂无明确上升趋势信号，建议持续监控。"

        if self.llm_api_key:
            return self._llm_enhanced_summary(items, category, region, rule_based)
        return rule_based

    def _llm_enhanced_summary(
        self,
        items: list[TrendItem],
        category: str,
        region: str,
        fallback: str,
    ) -> str:
        """LLM 增强摘要（只解释已计算指标，不生成数字），失败降级为规则输出。"""
        try:
            import openai

            client = openai.OpenAI()
            data_lines = "\n".join(
                f"- {t.keyword}: 热度{t.heat_index}, 生命周期{t.lifecycle}"
                for t in items
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是名创优品的市场研究总监。基于已计算的真实趋势指标，"
                            "用 100 字以内输出趋势研判，指出最值得关注的 1-2 个方向。"
                            "只解释已有数字，禁止编造数据中不存在的数字。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"品类: {category}\n市场: {region}\n数据:\n{data_lines}",
                    },
                ],
                temperature=0.3,
            )
            return resp.choices[0].message.content or fallback
        except Exception:  # noqa: BLE001 — LLM 故障刻意降级为规则输出
            return fallback


def get_trend_agent_class() -> type[BaseAgent]:
    """注册表切换：默认返回 MockTrendAgent（离线、确定、快）；
    设 TREND_AGENT_PROVIDER=real 时返回本真实 TrendAgent。
    Mock 作为可回退实现保留，不删除。
    """
    provider = resolve_provider("趋势官", "TREND_AGENT_PROVIDER")
    if provider == "real":
        return TrendAgent
    from .mock_agents import MockTrendAgent

    return MockTrendAgent
