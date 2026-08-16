"""OpportunityScore — 商业官输出契约

对应剧本 3.1：五维机会值评分。
关键纪律：总分为可追溯的加权算术，每个分项挂对应 Agent 的证据；
置信度沿用上游最低值（衰减，不放大）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .brief import Weights
from .evidence import Confidence, EvidenceMixin


class DimensionScore(BaseModel):
    """单个维度得分——由拥有该数据的 Agent 独立给出"""

    dimension: str = Field(
        ..., description="trend_heat/user_demand/ip_fit/competition/history_analog"
    )
    score: float = Field(..., ge=0, le=100)
    source_agent: str = Field(..., description="给分来源：trend/consumer_insight/ip_strategy")
    basis: str = Field(..., description="给分依据（引用上游结论）")


class RiskWarning(BaseModel):
    """风险提示，标注来源维度"""

    risk: str
    source_dimension: str
    severity: str = Field(default="medium", description="low/medium/high")


class OpportunityScore(EvidenceMixin):
    """单个方案的机会值评估"""

    proposal_name: str = Field(..., description="对应 ProductProposal.name")
    dimension_scores: list[DimensionScore] = Field(
        ..., min_length=5, max_length=5, description="五维分项，缺一不可"
    )
    weights_used: Weights = Field(..., description="本次使用的权重快照（留痕）")
    total_score: float = Field(..., ge=0, le=100, description="加权总分")
    star_rating: int = Field(..., ge=1, le=5, description="星级 1-5")
    risk_warnings: list[RiskWarning] = Field(default_factory=list)
    upstream_confidence: Confidence = Field(
        ..., description="上游最低置信度（沿链路衰减，不得上调）"
    )

    @model_validator(mode="after")
    def check_total(self):
        """校验总分 = 分项 × 权重 的算术一致性（83 分必须是一笔可追溯的算术）"""
        w = self.weights_used
        weight_map = {
            "trend_heat": w.trend_heat,
            "user_demand": w.user_demand,
            "ip_fit": w.ip_fit,
            "competition": w.competition,
            "history_analog": w.history_analog,
        }
        expected = sum(
            ds.score * weight_map.get(ds.dimension, 0)
            for ds in self.dimension_scores
        )
        if abs(expected - self.total_score) > 0.5:  # 容忍四舍五入误差
            raise ValueError(
                f"总分 {self.total_score} 与分项加权 {expected:.1f} 不一致"
            )
        return self
