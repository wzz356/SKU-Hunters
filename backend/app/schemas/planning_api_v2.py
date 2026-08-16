"""企划列表响应契约 v2

在 Stage 5 B 已冻结的 `PlanSummary`（app/schemas/planning.py）基础上，
为任务中心补充「数据来源（mode）」字段，使前端能正确标注 SourceTag。

设计约束：
- 不修改、不删除原 `PlanSummary`（冻结 schema）。
- 新契约独立于 planning.py，避免触碰已锁定的测试契约。
- mode 取值：fixture（冻结样本）| live（实时）| snapshot（快照）| demo（演示兜底）。
  缺失或未知时为空字符串，由前端映射为「来源未知」。
"""

from __future__ import annotations

from pydantic import BaseModel


class PlanSummaryV2(BaseModel):
    """企划任务列表项 v2（含数据来源 mode）"""

    plan_id: str
    theme: str = ""
    category: str = ""
    audience: str = ""
    status: str = ""      # brief_locked → insights_ready → opportunities_ready → plan_card_ready → archived
    created_at: str = ""
    mode: str = ""        # fixture | live | snapshot | demo（空串表示未知）


class PlanListResponseV2(BaseModel):
    """企划任务列表响应 v2"""

    plans: list[PlanSummaryV2]
