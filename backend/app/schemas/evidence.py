"""证据引用契约（EvidenceRef）
所有 Agent 输出必须绑定 EvidenceRef，确保每条结论可追溯。
剧本三条铁律之二：无证据不得发言。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    """置信度——剧本 0.3 发言卡必填项

    Decision Engine 合成时，低置信度结论权重自动降半；
    置信度沿链路衰减（下游取上游最低值），不允许放大。
    """

    HIGH = "high"          # 多源交叉验证
    MEDIUM = "medium"      # 单源可信
    LOW = "low"            # 推断
    UNKNOWN = "unknown"    # 无法判断（数据不足，合法输出）


class EvidenceRef(BaseModel):
    """单一证据引用"""

    url: str = Field(..., description="信息来源链接")
    title: str = Field(..., description="信息标题")
    snippet: str = Field(..., max_length=200, description="关键摘要")


class EvidenceMixin(BaseModel):
    """混入类：所有结构化产物的基类

    包含证据引用 + 置信度 + 保留意见（发言卡三要素）。
    """

    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list,
        description="支撑本次分析结论的证据引用列表",
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM,
        description="结论置信度：high/medium/low/unknown",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="保留意见：主动声明的不确定性与反向信号",
    )