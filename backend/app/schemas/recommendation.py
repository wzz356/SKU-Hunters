"""ProjectRecommendation — 《商品立项建议书》契约

Decision Engine 合成输出（对应剧本 ACT4）。
纪律：
- Top1 入选，落选方案的评分分歧原样保留（C3，不调和）
- 置信度 = 上游最低值（只衰减不放大）
- 风险告警改写为可执行的立项条件
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .evidence import Confidence
from .proposal import ProductProposal
from .review import ConflictRecord
from .scoring import OpportunityScore


class Decision(str, Enum):
    """立项定档——阈值见 Decision Engine 合成规则"""

    APPROVE = "approve"   # 总分 ≥ 80
    HOLD = "hold"         # 60 ~ 80
    REJECT = "reject"     # < 60


class ProjectRecommendation(BaseModel):
    """立项建议书——会议交付给人的最终产物"""

    proposal: ProductProposal = Field(..., description="入选方案（Top1）")
    opportunity_score: OpportunityScore = Field(
        ..., description="入选方案的五维成绩单（含证据链与权重快照）"
    )
    decision: Decision = Field(..., description="approve/hold/reject")
    conditions: list[str] = Field(
        default_factory=list,
        description="立项条件——由各维 risk_warnings 改写为可执行条款",
    )
    dissent_records: list[ConflictRecord] = Field(
        default_factory=list,
        description="分歧记录（C3 评分分歧/C4 人机冲突等），原样呈现不调和",
    )
    runner_ups: list[str] = Field(
        default_factory=list, description="落选方案名及一句话落选原因"
    )
    confidence: Confidence = Field(
        ..., description="全链置信度 = 上游各官最低值（衰减，不放大）"
    )
    summary: str = Field(..., description="建议书摘要（卡片正文）")
