"""Brief — 评审输入契约 + 权重模板

对应剧本 BRIEF_LOCKED 状态：评审启动前必须冻结的输入。
默认三要素（品类+市场+预算）为必填最小集，其余为高级选项。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class WeightTemplate(str, Enum):
    """权重预设模板——把参数问题翻译成业务语言"""

    DEFAULT = "default"    # 默认均衡
    VOLUME = "volume"      # 走量款：看需求强度
    IMAGE = "image"        # 形象款：看趋势热度
    PROFIT = "profit"      # 利润款：看差异化空间


class Weights(BaseModel):
    """五维权重，总和必须为 1.0"""

    trend_heat: float = Field(default=0.35, ge=0, le=1, description="趋势热度")
    user_demand: float = Field(default=0.25, ge=0, le=1, description="用户需求强度")
    ip_fit: float = Field(default=0.20, ge=0, le=1, description="IP 适配度")
    competition: float = Field(default=0.10, ge=0, le=1, description="竞争程度")
    history_analog: float = Field(default=0.10, ge=0, le=1, description="历史相似案例")

    @model_validator(mode="after")
    def check_sum(self):
        total = (
            self.trend_heat + self.user_demand + self.ip_fit
            + self.competition + self.history_analog
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"五维权重之和必须为 1.0，当前为 {total:.4f}")
        return self


class BudgetRange(str, Enum):
    LOW = "low"      # 新锐 IP / 无 IP
    MID = "mid"      # 中腰部 IP
    HIGH = "high"    # 头部 IP


class Brief(BaseModel):
    """评审输入——BRIEF_LOCKED 状态的冻结对象"""

    # ── 必填最小集 ──
    category: str = Field(..., description="品类，如 潮玩")
    market: str = Field(..., description="目标市场地区码，如 TH/JP/CN，global 为全球")
    budget_range: BudgetRange = Field(..., description="预算区间（硬约束，砍掉签不起的候选）")

    # ── 高级选项（带默认值，渐进式披露）──
    time_window: str | None = Field(
        default=None, description="上市时间窗口，影响押上升期还是峰值期趋势"
    )
    weight_template: WeightTemplate = Field(
        default=WeightTemplate.DEFAULT, description="权重预设模板"
    )
    custom_weights: Weights | None = Field(
        default=None, description="自定义权重；提供时覆盖模板"
    )
    candidate_pool: list[str] = Field(
        default_factory=list, description="候选 IP/方向池，如 ['Labubu','Chiikawa']"
    )
