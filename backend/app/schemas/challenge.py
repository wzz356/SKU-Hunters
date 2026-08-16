"""ChallengeRecord — 圆桌质询环节契约（ACT2_CHALLENGE）

剧本 6.1 C2 引用偏差的落地：创意官提出 ProposalSet 后，三位洞察官
（trend/user/ip）各自对方案发起结构化质询——背书 / 修正 / 反对。

纪律：
- 质询必须保留来源角色（source_role）与证据（evidence_refs），
  可追溯回提出该质询的洞察官及其底层证据。
- 质询是"对方案的引用与结论的核对"，不是新造数据；内容只能引用
  提出方自己的 Artifact 结论 + ProposalSet 方案要素。
- 质询结果进入 state.challenges，经 Decision Engine 汇总进立项建议书的
  分歧记录（dissent_records），不改冻结 Schema（新增契约=新增文件）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .evidence import Confidence, EvidenceRef


class ChallengeStance(str, Enum):
    """质询立场——背书 / 修正 / 反对"""

    ENDORSE = "endorse"   # 背书：方案已正确引用我方结论，无冲突
    REVISE = "revise"     # 修正：方案部分采用了结论但可补强
    OPPOSE = "oppose"     # 反对：方案与结论相悖或关键信号缺失


class ChallengeRecord(BaseModel):
    """一条结构化质询记录"""

    proposal_name: str = Field(..., description="被质询的方案名（ProductProposal.name）")
    stance: ChallengeStance = Field(..., description="质询立场：endorse/revise/oppose")
    content: str = Field(..., description="质询理由（引用我方结论与方案要素）")
    source_role: str = Field(
        ..., description="发起质询的洞察官：trend/user/ip"
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list,
        description="质询依据——引用发起方 Artifact 的证据链",
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM,
        description="质询置信度（沿用发起方 Artifact 的置信度）",
    )
