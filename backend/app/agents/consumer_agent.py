"""ConsumerInsightAgent — 真实用户官

基于 ConsumerDataView（Scoped View）的聚合消费者信号，确定性统计生成 UserSentiment。
只读聚合结果与证据引用；不读 BaseDataAdapter、不读原始评论全文、不访问其他 Agent 的 View。

数据不足 / 数据源故障时返回 confidence="unknown" 的合法产物，不编造痛点/比例/标签/评论。
"""

from __future__ import annotations

import os
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.mock_agents import MockUserAgent
from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.schemas import (
    Confidence,
    EvidenceRef,
    PainPoint,
    SentimentStat,
    UserSentiment,
)

# 痛点信号词（从 summary 确定性提取痛点，不编造）
_PAIN_KEYWORDS = ("难", "缺", "贵", "痛", "问题", "不满")

class ConsumerInsightAgent(BaseAgent):
    """真实用户官：从 ConsumerDataView 聚合信号生成 UserSentiment"""

    name = "consumer_insight_agent"
    description = "消费者洞察：基于品类评论与搜索意图聚合生成用户情感与需求"

    def __init__(self, config: dict | None = None, views: dict[str, Any] | None = None):
        super().__init__(config)
        self.views = views or {}

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        category = brief.get("category", "")
        view = self.views.get("ConsumerDataView")
        if view is None:
            return self._unknown(category, "无 ConsumerDataView 权限")

        try:
            result = view.get_category_signals(category)
        except BaseUnavailable:
            return self._unknown(category, "消费者数据源不可用（配置缺失或未接入）")
        except BaseProviderError:
            return self._unknown(category, "消费者数据源请求失败（网络/服务错误）")

        signals = result.get("signals", []) or []
        evidence = result.get("evidence", []) or []
        if not signals:
            return self._unknown(category, "品类无消费者数据")

        return self._build(category, signals, evidence)

    # ── 数据不足 ──────────────────────────

    def _unknown(self, category: str, caveat: str) -> dict[str, Any]:
        """数据不足 → 合法 UserSentiment，confidence=unknown，不编造"""
        return UserSentiment(
            product_category=category,
            sentiment=SentimentStat(positive=0.0, neutral=1.0, negative=0.0),
            pain_points=[],
            motivation_tags=[],
            summary=f"消费者数据不足：{caveat}。",
            evidence_refs=[],
            confidence=Confidence.UNKNOWN,
            caveats=[caveat],
        ).model_dump(mode="json")

    # ── 有数据 ──────────────────────────

    def _build(self, category: str, signals: list[dict[str, Any]], evidence: list[dict[str, str]]) -> dict[str, Any]:
        # BaseRecord 无情感标注，sentiment 用中性（诚实表示无法判断），总和=1.0
        sentiment = SentimentStat(positive=0.0, neutral=1.0, negative=0.0)
        self._validate_sentiment(sentiment)

        pain_points = self._extract_pain_points(signals)
        motivation_tags = self._extract_motivation_tags(signals)
        evidence_refs = [EvidenceRef(**e) for e in evidence[:5]]
        # 有信号但无可引用链接（source_url 全缺失）→ 诚实降为 UNKNOWN，不编造证据
        if evidence_refs:
            _confidence = Confidence.MEDIUM
            _caveats: list[str] = []
        else:
            _confidence = Confidence.UNKNOWN
            _caveats = ["品类存在消费者信号，但缺少可引用的来源链接（source_url 缺失）"]

        return UserSentiment(
            product_category=category,
            sentiment=sentiment,
            pain_points=pain_points,
            motivation_tags=motivation_tags,
            summary=self._summarize(category, signals, pain_points, motivation_tags),
            evidence_refs=evidence_refs,
            confidence=_confidence,
            caveats=_caveats,
        ).model_dump(mode="json")

    @staticmethod
    def _validate_sentiment(sentiment: SentimentStat) -> None:
        """显式校验情感比例总和为 1.0（schema 未强制，Agent 边界兜底）"""
        total = sentiment.positive + sentiment.neutral + sentiment.negative
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"SentimentStat 总和必须为 1.0，当前 {total:.4f}")

    def _extract_pain_points(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """从 summary 确定性提取痛点（含痛点词）；无则空，不编造"""
        pain_points: list[dict[str, Any]] = []
        seen: set[str] = set()
        for s in signals:
            summary = (s.get("summary") or "").strip()
            for kw in _PAIN_KEYWORDS:
                if kw in summary:
                    desc = summary[:80]
                    if desc not in seen:
                        seen.add(desc)
                        pain_points.append(
                            PainPoint(description=desc, frequency=0.0, severity="medium").model_dump()
                        )
                    break
        return pain_points[:3]

    def _extract_motivation_tags(self, signals: list[dict[str, Any]]) -> list[str]:
        """从 keyword 去重提取动机/搜索标签（确定性）"""
        tags: list[str] = []
        seen: set[str] = set()
        for s in signals:
            kw = (s.get("keyword") or "").strip()
            if kw and kw not in seen:
                seen.add(kw)
                tags.append(kw)
        return tags[:5]

    @staticmethod
    def _summarize(
        category: str,
        signals: list[dict[str, Any]],
        pain_points: list[dict[str, Any]],
        motivation_tags: list[str],
    ) -> str:
        n = len(signals)
        parts = [f"品类「{category}」聚合 {n} 条消费者信号"]
        if motivation_tags:
            parts.append("高频搜索词：" + "、".join(motivation_tags))
        parts.append(
            f"识别到 {len(pain_points)} 类痛点" if pain_points else "未识别到明确痛点信号"
        )
        return "；".join(parts) + "。"

def get_consumer_agent_class() -> type[BaseAgent]:
    """注册表切换：默认 MockUserAgent（离线/确定/快）；
    设 CONSUMER_AGENT_PROVIDER=real 时返回真实 ConsumerInsightAgent。
    """
    provider = os.getenv("CONSUMER_AGENT_PROVIDER", "mock").strip().lower()
    if provider == "real":
        return ConsumerInsightAgent
    return MockUserAgent
