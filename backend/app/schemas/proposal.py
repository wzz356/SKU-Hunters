"""ProductProposal — 创意官输出契约

对应剧本 2.2：3-5 个互异方案，每个要素可溯源。
三条硬校验（在创意官 Agent 内执行）：
1. 方案间形态/场景/价位至少两维不同
2. source_map 必须覆盖三方 Artifact 各至少一条
3. price_band 不得超出 Brief 预算区间
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class SourceRef(BaseModel):
    """方案要素的溯源引用——创意官只见 Artifact 不见原始数据，
    所以溯源到「哪份 Artifact 的哪条结论」为止。"""

    artifact: str = Field(
        ..., description="来源产物：FeatureMatrix/UserSentiment/IPAssessment"
    )
    claim: str = Field(..., description="引用的该产物中的结论原文")
    supports: str = Field(..., description="支撑本方案的哪个要素（形态/人群/价格带/IP）")


class ProductProposal(EvidenceMixin):
    """单个商品创意方案"""

    name: str = Field(..., description="方案名，如 桌面摆件系列")
    concept: str = Field(..., description="一句话概念")
    product_form: str = Field(
        ..., description="商品形态——必须来自用户官形态信号或爆品知识库"
    )
    target_segment: str = Field(..., description="目标人群")
    price_band: str = Field(..., description="价格带，如 ¥39-59")
    source_map: list[SourceRef] = Field(
        ..., min_length=3, description="溯源映射，至少覆盖三方 Artifact 各一条"
    )
    differentiation: str = Field(..., description="与其他候选方案的差异点")

    def covered_artifacts(self) -> set[str]:
        """返回 source_map 覆盖到的 Artifact 类型集合（硬校验 2 用）"""
        return {ref.artifact for ref in self.source_map}


class ProposalSet(BaseModel):
    """创意官一次产出：3-5 个互异方案"""

    proposals: list[ProductProposal] = Field(..., min_length=3, max_length=5)
    ideation_note: str = Field(default="", description="方案陈述与保留意见")
