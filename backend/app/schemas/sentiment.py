"""UserSentiment — 用户情感分析"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class SentimentStat(BaseModel):
    """情感统计"""

    positive: float = Field(..., ge=0, le=1, description="正面情感占比")
    neutral: float = Field(..., ge=0, le=1, description="中性情感占比")
    negative: float = Field(..., ge=0, le=1, description="负面情感占比")


class PainPoint(BaseModel):
    """用户痛点"""

    description: str = Field(..., description="痛点描述")
    frequency: float = Field(..., ge=0, le=1, description="出现频率 0-1")
    severity: str = Field(default="medium", description="严重程度：low/medium/high")


class UserSentiment(EvidenceMixin):
    """用户情感分析——用户官核心输出"""

    product_category: str = Field(..., description="品类")
    sentiment: SentimentStat = Field(..., description="情感分布")
    pain_points: list[PainPoint] = Field(default_factory=list, description="痛点列表")
    motivation_tags: list[str] = Field(
        default_factory=list, description="购买动机标签"
    )
    summary: str = Field(..., description="用户洞察摘要")