"""TaskDataContext — 统一任务数据事实源契约

每个洞察 / 机会 / 企划卡都能追溯到本上下文，明确其数据来源与完整性。

数据纪律：
- live 任务必须 data_source=feishu；
- fixture 任务必须 data_source=fixture；
- live 任务禁止静默回退 fixture/crawled/llm；
- 数据源失败显式 unavailable，不得自动回退 fixture；
- record_count / evidence_count 来自真实读取，不允许手填。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskMode(str, Enum):
    FIXTURE = "fixture"
    LIVE = "live"


class DataSource(str, Enum):
    FEISHU = "feishu"
    FIXTURE = "fixture"
    CRAWLED = "crawled"
    LLM = "llm"
    UNAVAILABLE = "unavailable"


class TaskDataContext(BaseModel):
    """任务数据事实源上下文"""

    plan_id: str
    mode: TaskMode
    data_source: DataSource
    snapshot_id: str = Field(default="", description="Feishu 数据快照号（live）")
    ingestion_run_id: str = Field(default="", description="本次采集/入库批次号")
    record_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    generated_at: str = Field(default="", description="ISO 时间")
    status: str = Field(default="ok", description="ok | unavailable | degraded")
    caveats: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_live_context(
    plan_id: str,
    record_count: int,
    evidence_count: int,
    snapshot_ids: list[str],
    generated_at: str,
    caveats: list[str] | None = None,
) -> TaskDataContext:
    """构造 live 任务上下文（data_source 固定 feishu）。"""
    snapshots = [s for s in snapshot_ids if s]
    return TaskDataContext(
        plan_id=plan_id,
        mode=TaskMode.LIVE,
        data_source=DataSource.FEISHU,
        snapshot_id=max(snapshots) if snapshots else "",
        ingestion_run_id=max(snapshots) if snapshots else "",
        record_count=record_count,
        evidence_count=evidence_count,
        generated_at=generated_at,
        status="ok",
        caveats=caveats or [],
    )


def build_fixture_context(plan_id: str, generated_at: str) -> TaskDataContext:
    """构造 fixture 任务上下文（data_source 固定 fixture）。"""
    return TaskDataContext(
        plan_id=plan_id,
        mode=TaskMode.FIXTURE,
        data_source=DataSource.FIXTURE,
        generated_at=generated_at,
        status="ok",
    )


def build_unavailable_context(plan_id: str, reason: str) -> TaskDataContext:
    """数据源失败 → unavailable，禁止静默回退 fixture。"""
    return TaskDataContext(
        plan_id=plan_id,
        mode=TaskMode.LIVE,
        data_source=DataSource.UNAVAILABLE,
        status="unavailable",
        caveats=[reason],
    )
