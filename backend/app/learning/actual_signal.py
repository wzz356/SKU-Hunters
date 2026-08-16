"""NormalizedActualSignal — 归一化实际结果信号契约（学习官）

明确区分实际结果状态，避免把热度/搜索量/聚合数据伪装成销量或上市结果：
- observed：有真实、完整实际结果；
- partial：只有部分有效结果；
- unavailable：实际数据源未接入或无数据；
- invalid：输入存在但字段非法，已被跳过。

纪律：metrics 只保留明确识别且通过范围校验的指标；缺失指标不默认填 0；
非法数值不静默转 0，跳过并记录 caveat；无 source_url 不伪造 EvidenceRef。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas import Confidence, EvidenceRef

# 实际指标建议支持（0~1 范围）
SUPPORTED_METRICS = (
    "first_month_sales_attainment",  # 首月销量达成率
    "sell_through_rate",             # 动销率
    "sellout_rate",                  # 售罄率
    "social_buzz_persistence",       # 社媒声量延续性
)

class ActualStatus(str, Enum):
    OBSERVED = "observed"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"

class NormalizedActualSignal(BaseModel):
    """归一化实际结果信号"""

    status: ActualStatus
    metrics: dict = Field(default_factory=dict, description="通过范围校验的实际指标（0~1）")
    period: str = Field(default="", description="实际结果所属期间")
    source: str = Field(default="", description="数据来源标识")
    snapshot_id: str = Field(default="", description="对应快照/批次号")
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, description="真实来源链接")
    confidence: Confidence = Confidence.UNKNOWN
    caveats: list[str] = Field(default_factory=list)
