"""IP 官三种实现 + 三档注册表

- MockIPAgent（mock_agents）：默认，离线/确定/快
- IPStrategyAgent（本文件）：确定性真实 IP 官——基于 IPDataView（Scoped View）
  的 IP 聚合信号，确定性生成 IPAssessment。只读 IP 类型数据的聚合结果与证据
  引用；不读 BaseDataAdapter、不读原始评论全文、不访问白名单外的数据源。
  确定性规则：ip_ranking / heat_score 仅来自真实信号聚合；lifecycle_stage /
  window_estimate / regional_fit / licensing_risk 缺数据时一律写
  unknown / 待核验语义，绝不臆造。数据源故障时返回 confidence=unknown 的
  合法产物，不回退 Mock。
- IPAgent（本文件）：真 LLM IP 官——双源热度交叉验证（淘宝搜索联想词 ×
  B站五分区排行榜关键词扫描），heat_score 一律代码算（确定性归一化公式），
  LLM 只做研判（生命周期/窗口期/区域适配/落选理由/策略建议）；授权风险无
  真实库可接 → 固定声明"未接入授权信息库"。候选池为空 / 双源全故障 /
  LLM 未配置 / 输出不合 schema → 回退 MockIPAgent。

注册表三档（get_ip_agent_class）：
  - 默认 / mock          → MockIPAgent
  - deterministic        → IPStrategyAgent（确定性，不烧 LLM）
  - real（或总开关 AGENT_PROVIDER=real）→ IPAgent（LLM，故障回退 Mock）
"""

from __future__ import annotations

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.mock_agents import MockIPAgent
from app.agents.real_common import parse_llm_json
from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.data.bilibili_hot import BilibiliConnector
from app.data.errors import ConnectorFetchError
from app.data.taobao_suggest import TaobaoSuggestConnector
from app.engine.strict_mode import require_mock_allowed, resolve_provider
from app.schemas import Confidence, EvidenceRef, IPAssessment, IPCandidate

# ══════════════════ 确定性实现：IPStrategyAgent ══════════════════

class IPStrategyAgent(BaseAgent):
    """真实 IP 官：从 IPDataView 聚合 IP 信号生成 IPAssessment"""

    name = "ip_strategy_agent"
    description = "IP 策略：基于 IP 热度信号生成 IP 候选排序与授权风险声明"

    def __init__(self, config: dict | None = None, views: dict[str, Any] | None = None):
        super().__init__(config)
        self.views = views or {}

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        category = brief.get("category", "")
        market = brief.get("market", "")
        view = self.views.get("IPDataView")
        if view is None:
            return self._unknown(category, market, "无 IPDataView 权限")

        candidate_pool = brief.get("candidate_pool", []) or []
        try:
            result = view.get_ip_signals(candidates=candidate_pool)
        except BaseUnavailable:
            return self._unknown(category, market, "IP 数据源不可用（配置缺失或未接入）")
        except BaseProviderError:
            return self._unknown(category, market, "IP 数据源请求失败（网络/服务错误）")

        signals = result.get("signals", []) or []
        evidence = result.get("evidence", []) or []
        candidates = self._build_candidates(signals)
        evidence_refs = [EvidenceRef(**e) for e in evidence[:5]]

        if not candidates:
            return self._unknown(category, market, "无 IP 信号（无品牌或热度数据）")
        if not evidence_refs:
            # 有 IP 提及信号但无可引用链接 → 诚实降为 unknown，不产出 ip_ranking
            return self._unknown(category, market, "检测到 IP 提及信号，但缺少可引用的来源链接")

        return self._build(category, market, candidates, evidence_refs)

    # ── 数据不足 ──────────────────────────

    def _unknown(self, category: str, market: str, caveat: str) -> dict[str, Any]:
        """数据不足 → 合法 IPAssessment，confidence=unknown，ip_ranking 为空，不编造"""
        return IPAssessment(
            category=category,
            market=market,
            ip_ranking=[],
            licensing_risk="待核验",
            strategy_note="",
            evidence_refs=[],
            confidence=Confidence.UNKNOWN,
            caveats=[caveat],
        ).model_dump(mode="json")

    # ── 有数据 ──────────────────────────

    def _build(
        self,
        category: str,
        market: str,
        candidates: list[IPCandidate],
        evidence_refs: list[EvidenceRef],
    ) -> dict[str, Any]:
        return IPAssessment(
            category=category,
            market=market,
            ip_ranking=candidates,
            licensing_risk="待核验",
            strategy_note=(
                "IP 热度信号已识别，生命周期/区域适配/授权信息待核验，"
                "暂无法给出联名策略研判"
            ),
            evidence_refs=evidence_refs,
            confidence=Confidence.LOW,
            caveats=[
                "生命周期阶段无数据源，标注 unknown",
                "窗口期无历史同构曲线依据，标注待核验",
                "区域适配数据缺失，regional_fit 无依据，保守标记待核验",
                "授权信息缺失，licensing_risk 待核验",
            ],
        ).model_dump(mode="json")

    def _build_candidates(self, signals: list[dict[str, Any]]) -> list[IPCandidate]:
        """按 brand 聚合 IP 热度，生成候选（缺区域数据 → 确定性中性值 + rejected）"""
        brand_heat: dict[str, float] = {}
        for s in signals:
            brand = s.get("brand")
            heat = s.get("heat_index")
            if not brand or heat is None:
                continue
            brand_heat[brand] = max(brand_heat.get(brand, 0.0), float(heat))

        ranked = sorted(brand_heat.items(), key=lambda x: x[1], reverse=True)
        return [
            IPCandidate(
                ip_name=brand,
                heat_score=round(heat, 2),
                lifecycle_stage="unknown",
                window_estimate="待核验",
                regional_fit=0.0,
                rejected=True,
                reject_reason="区域适配数据缺失，待核验",
            )
            for brand, heat in ranked
        ]


# ══════════════════ LLM 实现：IPAgent ══════════════════

_OUTPUT_CONTRACT = """
以上为角色与职责说明。本次请以「严格 JSON」输出（不要输出任何解释文字）：

{
  "candidates": [
    {
      "ip_name": "照抄输入的 IP 名",
      "lifecycle_stage": "rising/peak/declining/unknown",
      "window_estimate": "窗口期估计，如 6-9个月",
      "regional_fit": 0-100 的目标市场适配度,
      "rejected": false,
      "reject_reason": null 或 "不推荐原因（过热衰退/区域错配等）"
    }
  ],
  "licensing_risk": "授权风险声明（无真实授权库，写'无已知风险（未接入授权信息库）'）",
  "strategy_note": "联名策略研判一两句（如 成熟形态快反 而非 话题引爆）",
  "caveats": ["保留意见"]
}

要求：
1. 每个输入 IP 恰好一条，ip_name 照抄不得改写
2. 研判必须引用所给热度材料（联想词热度/B站播放量），禁止编造材料没有的数据
3. 热度分数由代码计算，你只管 lifecycle/window/regional_fit/策略
"""


def _heat_score(taobao_suggestions: list[dict[str, Any]] | None,
                bili: dict[str, Any] | None) -> float:
    """确定性热度归一：淘宝相对热度(0-100) × B站播放量对数归一，双源各半"""
    parts = []
    if taobao_suggestions is not None:
        avg = (sum(s["heat"] for s in taobao_suggestions) / len(taobao_suggestions)
               if taobao_suggestions else 0)
        parts.append(min(100.0, avg))
    if bili is not None:
        views = bili.get("total_views", 0)
        parts.append(min(100.0, math.log10(1 + views) * 20))
    if not parts:
        return 0.0
    return round(sum(parts) / len(parts), 1)


class IPAgent(BaseAgent):
    """真 IP 官：代码管热度与溯源，LLM 管研判，失败回退 Mock"""

    name = "ip_strategy_agent"

    def __init__(
        self,
        taobao: TaobaoSuggestConnector | None = None,
        bilibili: BilibiliConnector | None = None,
    ):
        self.taobao = taobao or TaobaoSuggestConnector(timeout=6)
        self.bilibili = bilibili or BilibiliConnector(timeout=6)

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._generate, context)
            if result is not None:
                return result
        except Exception:  # noqa: BLE001,S110 — 降级纪律：任何故障回退 Mock
            pass
        require_mock_allowed("IP官 LLM/数据故障回退 Mock")
        return await MockIPAgent().run(context)

    # ── 数据采集（候选 × 双源并行）───────────────────────────

    def _collect(self, candidates: list[str]) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {
            ip: {"taobao": None, "bili": None, "failed": []} for ip in candidates
        }
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}
            for ip in candidates:
                futures[pool.submit(self.taobao.get_suggestions, ip)] = (ip, "taobao")
                futures[pool.submit(self.bilibili.search_keyword, ip)] = (ip, "bili")
            for fut, (ip, source) in futures.items():
                try:
                    results[ip][source] = fut.result()
                except ConnectorFetchError:
                    results[ip]["failed"].append(source)
                except Exception:  # noqa: BLE001 — taobao 约定返回空，双保险
                    results[ip]["failed"].append(source)
        return results

    # ── 主流程 ─────────────────────────────────────────────

    def _generate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        from app.engine.llm import complete, load_prompt

        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")
        market = brief.get("market", "CN")
        feedback = (context.get("feedback") or "").strip()

        candidates = [str(c) for c in (brief.get("candidate_pool") or [])][:3]
        if not candidates:
            return None  # 池空 → Mock（Mock 自带固定候选），不烧 LLM 提名

        collected = self._collect(candidates)

        # ① 全部候选双源全故障 → 回退 Mock（故障 ≠ 零命中）
        if all(
            len(c["failed"]) == 2 for c in collected.values()
        ):
            return None

        # 每候选热度（代码算）+ 材料汇总
        heat_map = {
            ip: _heat_score(c["taobao"], c["bili"]) for ip, c in collected.items()
        }

        # ② 全部候选零命中 → 合法 unknown 输出
        if all(h == 0 for h in heat_map.values()):
            zero_caveats = ["双源零命中：候选可能为长尾/新 IP，建议人工补充销售数据"]
            failed_sources = {s for c in collected.values() for s in c["failed"]}
            if failed_sources:
                zero_caveats.append(
                    f"数据源 {','.join(sorted(failed_sources))} 部分拉取失败，"
                    "零命中结论可能受故障影响"
                )
            return IPAssessment(
                category=category,
                market=market,
                ip_ranking=[
                    {
                        "ip_name": ip, "heat_score": 0,
                        "lifecycle_stage": "unknown", "window_estimate": "无法估计",
                        "regional_fit": 0,
                    }
                    for ip in candidates
                ],
                licensing_risk="无已知风险（未接入授权信息库）",
                strategy_note="候选 IP 在淘宝联想词与B站分区榜均零命中，热度无法判断。",
                evidence_refs=[],
                confidence=Confidence.UNKNOWN,
                caveats=zero_caveats,
            ).model_dump(mode="json")

        # ③ 有料 → LLM 研判
        material = [f"品类：{category}　目标市场：{market}", ""]
        for ip in candidates:
            c = collected[ip]
            material.append(f"【{ip}】代码测算热度 {heat_map[ip]}")
            if c["taobao"] is not None:
                top = sorted(c["taobao"], key=lambda x: x["heat"], reverse=True)[:5]
                material.append(
                    f"  淘宝联想 {len(c['taobao'])} 条："
                    + "、".join(f"{s['query']}({s['heat']})" for s in top)
                )
            if c["bili"] is not None:
                b = c["bili"]
                material.append(
                    f"  B站五分区榜扫描 {b['scanned_videos']} 条视频，"
                    f"命中 {b['total_results']} 条，总播放 {b['total_views']}"
                )
                for v in b["top_videos"][:2]:
                    material.append(f"    · {v['title'][:40]}（播放 {v['view']}）")
            if c["failed"]:
                material.append(f"  （{','.join(c['failed'])} 源拉取失败）")
        if feedback:
            material.append(f"\n【评委打回意见】{feedback}——本轮必须针对性修正")

        persona_prompt = load_prompt(self.name)
        system = (persona_prompt + "\n" + _OUTPUT_CONTRACT) if persona_prompt else _OUTPUT_CONTRACT
        raw = complete(system, "\n".join(material), temperature=0.3, max_tokens=100_000)
        if not raw:
            return None
        data = parse_llm_json(raw)
        if data is None:
            return None

        # ④ 组装：LLM 研判 + 代码热度，按热度降序
        llm_by_name = {
            str(c.get("ip_name", "")): c for c in data.get("candidates", [])
        }
        ranking = []
        for ip in candidates:
            c = llm_by_name.get(ip)
            if c is None:
                return None  # 缺候选 = 输出不完整，回退 Mock
            lifecycle = str(c.get("lifecycle_stage", "unknown"))
            if lifecycle not in ("rising", "peak", "declining", "unknown"):
                lifecycle = "unknown"
            try:
                regional_fit = max(0.0, min(100.0, float(c.get("regional_fit", 50))))
            except (TypeError, ValueError):
                regional_fit = 50.0
            rejected = bool(c.get("rejected", False))
            ranking.append({
                "ip_name": ip,
                "heat_score": heat_map[ip],  # 代码值，覆盖 LLM
                "lifecycle_stage": lifecycle,
                "window_estimate": str(c.get("window_estimate", "无法估计")),
                "regional_fit": regional_fit,
                "rejected": rejected,
                "reject_reason": str(c["reject_reason"]) if rejected and c.get("reject_reason") else None,
            })
        ranking.sort(key=lambda r: r["heat_score"], reverse=True)

        # 证据：代码从连接器返回构建（每候选 B站 top 视频 + 淘宝联想）
        evidence = []
        for ip in candidates:
            c = collected[ip]
            if c["bili"]:
                for v in c["bili"]["top_videos"][:1]:
                    evidence.append(EvidenceRef(
                        url=v["url"],
                        title=f"B站：{v['title'][:30]}",
                        snippet=f"「{ip}」相关视频，播放 {v['view']}"[:200],
                    ))
            if c["taobao"]:
                top1 = max(c["taobao"], key=lambda x: x["heat"], default=None)
                if top1:
                    evidence.append(EvidenceRef(
                        url=f"https://s.taobao.com/search?q={ip}",
                        title="淘宝搜索联想词（实时拉取）",
                        snippet=f"「{ip}」最热联想：{top1['query']}（热度 {top1['heat']}）"[:200],
                    ))

        caveats = [str(x) for x in data.get("caveats", [])][:5]
        caveats.append("热度分由代码按确定性公式计算（淘宝联想热度+B站播放量对数归一）")
        caveats.append("授权风险未接入真实授权信息库，签约前需人工核实")
        failed_sources = {s for c in collected.values() for s in c["failed"]}
        if failed_sources:
            caveats.append(f"数据源 {','.join(sorted(failed_sources))} 部分拉取失败")

        confidence = Confidence.HIGH if not failed_sources else Confidence.MEDIUM

        return IPAssessment(
            category=category,
            market=market,
            ip_ranking=ranking,
            licensing_risk=str(data.get("licensing_risk", "")).strip()
            or "无已知风险（未接入授权信息库）",
            strategy_note=str(data.get("strategy_note", "")),
            evidence_refs=evidence[:8],
            confidence=confidence,
            caveats=caveats,
        ).model_dump(mode="json")


# ══════════════════ 注册表 ══════════════════

def get_ip_agent_class() -> type[BaseAgent]:
    """注册表三档切换：
    - 默认 / mock → MockIPAgent（离线/确定/快）
    - IP_AGENT_PROVIDER=deterministic → IPStrategyAgent
      （确定性聚合：不调用 LLM，信号全部来自 IPDataView）
    - IP_AGENT_PROVIDER=real（或总开关 AGENT_PROVIDER=real）→ IPAgent
      （双源交叉验证 + LLM 研判，数据/LLM 故障时内部回退 Mock）
    注意：注册表在 import 时求值，env 必须在进程启动前设置。
    """
    provider = resolve_provider("IP官", "IP_AGENT_PROVIDER", ("real", "deterministic"))
    if provider == "real":
        return IPAgent
    if provider == "deterministic":
        return IPStrategyAgent
    return MockIPAgent
