"""Challenge Agents — 圆桌质询环节的洞察官（ACT2_CHALLENGE）

创意官提出 ProposalSet 后，三位洞察官（trend/user/ip）各自对方案
发起结构化质询（背书 / 修正 / 反对）。本实现为确定性规则版（Mock）：
基于「自己的 Artifact 结论」与「方案 source_map 是否引用了我方结论」
生成质询，不新造数据——所有理由都引用可追溯的既有证据。

真挑战 Agent 出炉后：按 AGENTS.md 接口 A 接入，替换本文件对应类，
图节点包装层零改动。

纪律：
- 只引用提出方自己的 Artifact（feature_matrix / user_sentiment /
  ip_assessment）与 ProposalSet，禁止引用其他洞察官的原始数据。
- evidence_refs 必须闭合：引用自己 Artifact 的 evidence_refs。
- stance 判定是确定性规则，不硬编码"结论数字"，只做覆盖核对。
"""

from __future__ import annotations

from typing import Any

from app.agents.base_agent import BaseAgent
from app.schemas import (
    ChallengeRecord,
    ChallengeStance,
    Confidence,
    EvidenceRef,
    ProposalSet,
)

# 各洞察官 Artifact 名 → 其 evidence_refs 字段所在
_ARTIFACT_KEYS: dict[str, str] = {
    "trend": "feature_matrix",
    "user": "user_sentiment",
    "ip": "ip_assessment",
}

# 各洞察官在 ProposalSet.source_map 中对应的 artifact 名
_ARTIFACT_LABEL: dict[str, str] = {
    "trend": "FeatureMatrix",
    "user": "UserSentiment",
    "ip": "IPAssessment",
}


class MockChallengeTrendAgent(BaseAgent):
    """趋势官质询：核对方案是否引用趋势结论，提示错失的趋势信号"""

    name = "trend_challenge"

    def _key_conclusion(self, artifact: dict[str, Any]) -> str:
        trends = artifact.get("trends", [])
        if trends:
            top = trends[0]
            return (
                f"最热关键词「{top.get('keyword', '')}」"
                f"（热度 {top.get('heat_index', 0)}，{top.get('lifecycle', '?')}）"
            )
        return artifact.get("summary", "")

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        return _build_challenges(context, "trend", self._key_conclusion)


class MockChallengeUserAgent(BaseAgent):
    """用户官质询：核对方案是否回应真实痛点，提示忽略的需求信号"""

    name = "user_challenge"

    def _key_conclusion(self, artifact: dict[str, Any]) -> str:
        pains = artifact.get("pain_points", [])
        if pains:
            top = max(pains, key=lambda p: p.get("frequency", 0))
            return f"高频痛点「{top.get('description', '')}」（频次 {top.get('frequency', 0)}）"
        return artifact.get("summary", "")

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        return _build_challenges(context, "user", self._key_conclusion)


class MockChallengeIPAgent(BaseAgent):
    """IP官质询：核对方案所选 IP 与窗口期，提示授权风险"""

    name = "ip_challenge"

    def _key_conclusion(self, artifact: dict[str, Any]) -> str:
        ranking = artifact.get("ip_ranking", [])
        if ranking:
            top = ranking[0]
            return (
                f"首选 IP「{top.get('ip_name', '')}」"
                f"（热度 {top.get('heat_score', 0)}，窗口期 {top.get('window_estimate', '-')}）"
            )
        return artifact.get("strategy_note", "")

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        return _build_challenges(context, "ip", self._key_conclusion)


def _build_challenges(
    context: dict[str, Any], source_role: str, key_conclusion
) -> dict[str, Any]:
    """确定性生成质询列表（Mock）：按 source_map 覆盖核对定 stance"""
    artifact = context.get(_ARTIFACT_KEYS[source_role]) or {}
    proposal_set = context.get("proposal_set") or {}
    proposals = ProposalSet.model_validate(proposal_set).proposals

    own_evidence = [
        EvidenceRef(**ref)
        for ref in artifact.get("evidence_refs", [])[:3]
    ]
    label = _ARTIFACT_LABEL[source_role]
    conclusion = key_conclusion(artifact)
    conf = Confidence(artifact.get("confidence", "medium"))

    challenges: list[ChallengeRecord] = []
    for proposal in proposals:
        covered = label in {ref.artifact for ref in proposal.source_map}
        if covered:
            challenges.append(ChallengeRecord(
                proposal_name=proposal.name,
                stance=ChallengeStance.ENDORSE,
                content=f"方案已引用{label}结论「{conclusion}」，与我方判断一致",
                source_role=source_role,
                evidence_refs=own_evidence,
                confidence=conf,
            ))
        else:
            challenges.append(ChallengeRecord(
                proposal_name=proposal.name,
                stance=ChallengeStance.REVISE,
                content=(
                    f"方案未引用{label}关键信号「{conclusion}」，"
                    f"建议补强以提升证据闭合度"
                ),
                source_role=source_role,
                evidence_refs=own_evidence,
                confidence=conf,
            ))

    return {"challenges": [c.model_dump(mode="json") for c in challenges]}


# 质询注册表：真挑战 Agent 出炉后只改这里
CHALLENGE_REGISTRY: dict[str, type] = {
    "trend": MockChallengeTrendAgent,
    "user": MockChallengeUserAgent,
    "ip": MockChallengeIPAgent,
}
