"""PricingComparison — 定价对比表"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class PricePoint(BaseModel):
    """单条定价对比"""

    product_name: str = Field(..., description="商品名称")
    market_price: float = Field(..., description="市场价格")
    suggested_price: float = Field(..., description="建议定价")
    competitor_price: float | None = Field(default=None, description="竞品参考价")
    currency: str = Field(default="CNY", description="币种")


class PricingComparison(EvidenceMixin):
    """定价对比表——商业官输出之一"""

    category: str = Field(..., description="品类")
    price_points: list[PricePoint] = Field(..., description="定价对比列表")
    price_range: str = Field(..., description="建议价格带")
    margin_estimate: str = Field(..., description="毛利预估")
    summary: str = Field(..., description="定价策略摘要")