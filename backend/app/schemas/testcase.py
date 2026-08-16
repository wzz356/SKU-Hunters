"""BacktestCase — 历史回测集案例格式

对应测试集设计：30-50 个已完结案例，爆/平/扑各约 1/3。
生命线纪律：
1. 时点截取——input_snapshot 只含 decision_date 之前公开可得的数据
2. 必须有失败案例——扑街占比不低于 1/3
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .evidence import EvidenceRef


class Outcome(str, Enum):
    HIT = "hit"          # 爆
    AVERAGE = "average"  # 平
    FLOP = "flop"        # 扑


class BacktestCase(BaseModel):
    """单个回测案例——时光机回测的最小单位"""

    case_id: str = Field(..., description="如 case-2024-labubu-sea")
    title: str = Field(..., description="案例名，如 Labubu 东南亚联名")
    category: str
    market: str
    decision_date: str = Field(
        ..., description="决策时点（YYYY-MM-DD）——输入数据不得晚于此日"
    )
    input_snapshot: dict = Field(
        ...,
        description="决策时点前公开可得的信号快照："
        "{trend_signals, demand_signals, ip_signals, competition_signals}",
    )
    actual_outcome: Outcome = Field(..., description="实际结果标签")
    outcome_metrics: dict = Field(
        default_factory=dict,
        description="公开可查证的结果指标：销量排名/财报提及/热搜曲线等",
    )
    outcome_evidence: list[EvidenceRef] = Field(
        ..., min_length=1, description="结果判定的公开来源（新闻/财报/榜单）"
    )
    human_verified: bool = Field(
        default=False, description="结果标签是否经人工核对"
    )


class BacktestSet(BaseModel):
    """回测集——含分层抽样校验"""

    version: str
    cases: list[BacktestCase]

    def outcome_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for c in self.cases:
            dist[c.actual_outcome.value] = dist.get(c.actual_outcome.value, 0) + 1
        return dist

    def validate_balance(self) -> bool:
        """扑街案例占比不低于 1/3（防幸存者偏差）"""
        dist = self.outcome_distribution()
        total = len(self.cases)
        return total > 0 and dist.get("flop", 0) / total >= 1 / 3
