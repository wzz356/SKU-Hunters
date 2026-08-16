"""Decision Engine — 综合决策引擎

汇聚商业官的五维评分与创意官的提案集，合成《商品立项建议书》。
合成规则（与全景设计文档 3.4 一致）：
1. 按总分排序取 Top1（总分算术一致性由 OpportunityScore validator 强制）
2. 落选方案与评分分歧原样写入 dissent_records / runner_ups，不调和
3. 置信度 = 上游最低值（衰减，不放大）；低置信结论显式标注降权
4. 阈值定档：≥80 approve / 60~80 hold / <60 reject
5. risk_warnings 改写为可执行立项条件
"""

from __future__ import annotations

from typing import Any

from app.schemas import (
    Confidence,
    ConflictRecord,
    ConflictType,
    Decision,
    OpportunityScore,
    ProjectRecommendation,
    ProposalSet,
)

_CONFIDENCE_ORDER = [
    Confidence.UNKNOWN,
    Confidence.LOW,
    Confidence.MEDIUM,
    Confidence.HIGH,
]

# 定档阈值
_APPROVE_THRESHOLD = 80.0
_HOLD_THRESHOLD = 60.0
# 与第二名分差小于该值时，记一条 C3 评分分歧（不强制一致，写入建议书）
_CLOSE_CALL_GAP = 10.0


def min_confidence(values: list[Confidence | str]) -> Confidence:
    """取置信度最低值——沿链路只衰减不放大"""
    if not values:
        return Confidence.UNKNOWN
    return min(
        (Confidence(v) for v in values), key=_CONFIDENCE_ORDER.index
    )


class DecisionEngine:
    """综合决策引擎"""

    def synthesize(
        self,
        proposal_set: dict[str, Any],
        opportunity_scores: list[dict[str, Any]],
        conflicts: list[dict[str, Any]] | None = None,
    ) -> ProjectRecommendation:
        """合成立项建议书

        Args:
            proposal_set: 创意官 ProposalSet.model_dump()
            opportunity_scores: 商业官 OpportunityScore.model_dump() 列表
            conflicts: 会议中累积的冲突记录（C1-C6）

        Returns:
            ProjectRecommendation: 立项建议书
        """
        proposals = ProposalSet.model_validate(proposal_set)
        scores = [
            OpportunityScore.model_validate(s) for s in opportunity_scores
        ]
        if not scores:
            raise ValueError("Decision Engine 至少需要一份机会值评分")

        ranked = sorted(scores, key=lambda s: s.total_score, reverse=True)
        top = ranked[0]
        proposal = next(
            p for p in proposals.proposals if p.name == top.proposal_name
        )

        decision = self._decide(top.total_score)
        confidence = min_confidence(
            [top.upstream_confidence, proposal.confidence]
        )
        dissent = self._collect_dissent(ranked, conflicts or [])
        conditions = self._build_conditions(top)
        if confidence in (Confidence.LOW, Confidence.UNKNOWN):
            conditions.append(
                f"上游置信度为 {confidence.value}，低置信结论已降权处理，"
                "建议补充数据后复评"
            )

        return ProjectRecommendation(
            proposal=proposal,
            opportunity_score=top,
            decision=decision,
            conditions=conditions,
            dissent_records=dissent,
            runner_ups=[
                f"{s.proposal_name}（{s.total_score:.1f} 分，落选）"
                for s in ranked[1:]
            ],
            confidence=confidence,
            summary=(
                f"入选方案「{proposal.name}」，机会值 {top.total_score:.1f} 分"
                f"（{decision.value}）。"
                f"价格带 {proposal.price_band}，目标人群 {proposal.target_segment}。"
            ),
        )

    def _decide(self, total: float) -> Decision:
        if total >= _APPROVE_THRESHOLD:
            return Decision.APPROVE
        if total >= _HOLD_THRESHOLD:
            return Decision.HOLD
        return Decision.REJECT

    def _collect_dissent(
        self,
        ranked: list[OpportunityScore],
        conflicts: list[dict[str, Any]],
    ) -> list[ConflictRecord]:
        """C3 分歧：与第二名分差过小时显式记录；会议冲突原样透传"""
        records = [ConflictRecord.model_validate(c) for c in conflicts]
        if len(ranked) >= 2:
            gap = ranked[0].total_score - ranked[1].total_score
            if gap < _CLOSE_CALL_GAP:
                records.append(
                    ConflictRecord(
                        conflict_type=ConflictType.C3_SCORE_DIVERGENCE,
                        parties=["business_evaluation_agent"],
                        description=(
                            f"Top1「{ranked[0].proposal_name}」"
                            f"{ranked[0].total_score:.1f} 分 与 "
                            f"「{ranked[1].proposal_name}」"
                            f"{ranked[1].total_score:.1f} 分 "
                            f"分差仅 {gap:.1f}，评分存在分歧"
                        ),
                        resolution="open",
                        act="act4",
                    )
                )
        return records

    def _build_conditions(self, top: OpportunityScore) -> list[str]:
        """风险告警 → 可执行立项条件"""
        return [
            f"[{w.severity}] {w.risk}（来源维度：{w.source_dimension}）"
            for w in top.risk_warnings
        ]
