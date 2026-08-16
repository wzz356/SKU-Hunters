"""GTMPlan — 全球化官输出契约（Phase 2）

对应剧本 3.2：上市国家排序、分批计划、定价、本地化要点。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class CountryPlan(BaseModel):
    """单国上市计划"""

    country: str = Field(..., description="国家/地区码，如 TH/JP")
    batch: int = Field(..., ge=1, description="上市批次，1 为首批")
    price_band: str = Field(..., description="当地货币价格带，如 ฿199-299")
    timing: str = Field(..., description="上市时点，如 首批2周内")
    rationale: str = Field(..., description="依据的区域适配证据")


class GTMPlan(EvidenceMixin):
    """单个方案的全球化上市策略"""

    proposal_name: str = Field(..., description="对应 ProductProposal.name")
    country_plans: list[CountryPlan] = Field(..., description="按批次排序")
    localization_notes: list[str] = Field(
        default_factory=list, description="本地化要点，如 日本需礼盒装"
    )
    deferred_markets: list[str] = Field(
        default_factory=list, description="建议暂缓的市场及原因"
    )
    dependencies: str = Field(
        default="", description="批次间依赖说明，如 第二批依赖首批动销数据"
    )
