"""SWOTAnalysis — SWOT 分析"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class SWOTItem(BaseModel):
    """单条SWOT条目"""

    dimension: str = Field(..., description="维度：strength/weakness/opportunity/threat")
    content: str = Field(..., description="内容描述")
    weight: float = Field(default=1.0, ge=0, le=1, description="权重 0-1")


class SWOTAnalysis(EvidenceMixin):
    """SWOT 分析——商业官/全球化官输出"""

    product_name: str = Field(..., description="分析对象")
    items: list[SWOTItem] = Field(..., description="SWOT条目列表")
    overall_score: float = Field(..., ge=0, le=100, description="综合评分")
    recommendation: str = Field(..., description="综合建议")