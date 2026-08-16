"""FeatureMatrix — 趋势分析矩阵"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class TrendItem(BaseModel):
    """单条趋势条目"""

    keyword: str = Field(..., description="趋势关键词")
    heat_index: float = Field(..., ge=0, le=100, description="趋势热度指数 0-100")
    platform: str = Field(..., description="来源平台（TikTok/Instagram/小红书等）")
    region: str = Field(default="global", description="区域市场")
    lifecycle: str = Field(
        default="rising", description="生命周期阶段：rising/peak/declining"
    )


class FeatureMatrix(EvidenceMixin):
    """趋势分析矩阵——趋势官核心输出"""

    category: str = Field(..., description="分析品类")
    region: str = Field(default="global", description="分析区域")
    trends: list[TrendItem] = Field(..., description="趋势条目列表")
    summary: str = Field(..., description="趋势摘要")
    analysis_date: str = Field(..., description="分析日期")