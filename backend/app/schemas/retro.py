"""RetroReport — 学习官输出契约（第五幕）

对应剧本 5.1：预测-结果配对、偏差归因、校准建议。
纪律：学习官只提建议，无自动改参权；N 期积累才提校准；
新权重影子运行验证后才切换；每次变更版本化可回滚。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .brief import Weights
from .evidence import EvidenceMixin


class DimensionGap(BaseModel):
    """单维度预测偏差"""

    dimension: str
    predicted: float = Field(..., description="当初评分")
    actual_signal: str = Field(..., description="实际表现描述")
    accuracy: str = Field(..., description="accurate/overestimated/underestimated")
    note: str = ""


class RetroReport(EvidenceMixin):
    """单方案上市复盘报告"""

    proposal_name: str
    decision_record_ref: str = Field(
        ..., description="当初立项记录 ID（多维表格台账行）——预测-结果配对的钥匙"
    )
    outcome_metrics: dict = Field(
        ..., description="实际结果：首月销量达成率/动销率/售罄率/社媒声量延续性"
    )
    dimension_gaps: list[DimensionGap] = Field(..., description="逐维度偏差")
    attribution: str = Field(..., description="归因：哪个信号是真的，哪个误导了")
    new_dimension_candidates: list[str] = Field(
        default_factory=list, description="新发现的评估维度候选"
    )
    weight_advice: Weights | None = Field(
        default=None, description="权重校准建议（仅建议，人类批准后影子运行再切换）"
    )
    advice_basis_periods: int = Field(
        default=0, description="建议依据的累计期数（样本量纪律：单次不调权重）"
    )
    agent_performance: dict = Field(
        default_factory=dict, description="各 Agent 本期预测准确度，如 {'trend': 0.8}"
    )
    flywheel_metric: str = Field(
        default="", description="飞轮转速：预测偏差率环比变化"
    )
