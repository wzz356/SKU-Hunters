"""IPAssessment — IP官输出契约

对应剧本 1.3：IP 热度评估、生命周期预测、授权风险。
数据白名单：仅 IP 热度数据、授权信息库、历史联名案例库。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceMixin


class IPCandidate(BaseModel):
    """单个 IP 候选评估"""

    ip_name: str = Field(..., description="IP 名称")
    heat_score: float = Field(..., ge=0, le=100, description="当前热度 0-100")
    lifecycle_stage: str = Field(
        ..., description="生命周期：rising/peak/declining/unknown"
    )
    window_estimate: str = Field(
        ..., description="窗口期估计，如 6-9个月；依据历史同构曲线"
    )
    regional_fit: float = Field(..., ge=0, le=100, description="目标市场适配度")
    rejected: bool = Field(default=False, description="是否不推荐")
    reject_reason: str | None = Field(
        default=None, description="不推荐原因：过热衰退/授权成本超预算/区域错配"
    )


class IPAssessment(EvidenceMixin):
    """IP官核心输出"""

    category: str
    market: str
    ip_ranking: list[IPCandidate] = Field(..., description="IP 候选优先级排序")
    licensing_risk: str = Field(
        ..., description="授权风险声明；无风险时必须显式写'无已知风险'"
    )
    strategy_note: str = Field(
        default="", description="联名策略研判，如「成熟形态快反」而非「话题引爆」"
    )
