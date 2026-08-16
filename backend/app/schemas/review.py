"""ReviewResult + ConflictRecord — 质检与冲突契约

对应剧本第六章：ReviewAgent 质检输出 + C1-C6 冲突记录。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ConflictType(str, Enum):
    """剧本 6.1 冲突分类"""

    C1_DATA_SIGNAL = "c1_data_signal"        # 数据信号冲突：如实并陈，禁止调和
    C2_QUOTE_DEVIATION = "c2_quote_deviation"  # 结论引用偏差：质询修正/反对
    C3_SCORE_DIVERGENCE = "c3_score_divergence"  # 评分分歧：不强制一致，写入建议书
    C4_HUMAN_AI = "c4_human_ai"              # 人机冲突：人赢，必须留理由
    C5_INSUFFICIENT = "c5_insufficient"      # 证据不足：降级声明"无法判断"
    C6_INTERRUPTION = "c6_interruption"      # 打断冲突：最小失效重跑


class ConflictRecord(BaseModel):
    """一条冲突记录——直达建议书「分歧记录」区块"""

    conflict_type: ConflictType
    parties: list[str] = Field(..., description="冲突方，如 ['trend','consumer_insight']")
    description: str = Field(..., description="冲突内容（原样呈现，不调和）")
    lifecycle_inference: str = Field(
        default="", description="C1 专用：由信号背离推出的生命周期判断"
    )
    resolution: str = Field(default="open", description="open/resolved/deferred")
    act: str = Field(..., description="发现于第几幕，如 act1")


class ReviewIssue(BaseModel):
    """单条质检问题"""

    rule: str = Field(..., description="触发的规则，如 missing_evidence/conflict_unmarked")
    description: str
    target_node: str = Field(
        ..., description="回退节点——ReviewAgent 打回时 LangGraph 跳转目标"
    )


class ReviewResult(BaseModel):
    """ReviewAgent 质检结果（对应 ACT 门）"""

    passed: bool
    issues: list[ReviewIssue] = Field(default_factory=list)
    checked_artifacts: list[str] = Field(
        default_factory=list, description="本次检查的 Artifact 清单"
    )

    @property
    def fallback_node(self) -> str | None:
        """最早受影响节点（最小失效重跑的起点）"""
        if not self.issues:
            return None
        order = [
            "trend_agent", "consumer_insight_agent", "ip_strategy_agent",
            "product_ideation_agent", "business_evaluation_agent",
            "go_to_market_agent", "report_agent",
        ]
        nodes = [i.target_node for i in self.issues]
        return min(nodes, key=lambda n: order.index(n) if n in order else 99)
