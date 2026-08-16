"""Stage 11A — 统一任务数据上下文契约与 live/fixture 隔离测试"""

from __future__ import annotations

import pytest

from app.engine.task_data_context import (
    DataSource,
    TaskDataContext,
    TaskMode,
    build_fixture_context,
    build_live_context,
    build_unavailable_context,
)

# ── 契约构造 ──────────────────────────

def test_build_live_context_fields():
    ctx = build_live_context("p1", 100, 50, ["snap-a"], "2026-08-16T00:00:00Z")
    assert ctx.mode == TaskMode.LIVE
    assert ctx.data_source == DataSource.FEISHU
    assert ctx.snapshot_id == "snap-a"
    assert ctx.ingestion_run_id == "snap-a"
    assert ctx.record_count == 100
    assert ctx.evidence_count == 50
    assert ctx.status == "ok"


def test_build_live_context_empty_snapshot():
    ctx = build_live_context("p1", 0, 0, [], "2026-08-16T00:00:00Z")
    assert ctx.snapshot_id == ""
    assert ctx.ingestion_run_id == ""


def test_build_fixture_context():
    ctx = build_fixture_context("p1", "2026-08-16T00:00:00Z")
    assert ctx.mode == TaskMode.FIXTURE
    assert ctx.data_source == DataSource.FIXTURE


def test_build_unavailable_context():
    ctx = build_unavailable_context("p1", "飞书不可用")
    assert ctx.status == "unavailable"
    assert ctx.data_source == DataSource.UNAVAILABLE
    assert "飞书不可用" in ctx.caveats


def test_context_roundtrip():
    ctx = build_live_context("p1", 10, 5, ["snap-a"], "2026-08-16T00:00:00Z")
    data = ctx.to_dict()
    restored = TaskDataContext.model_validate(data)
    assert restored.mode == TaskMode.LIVE
    assert restored.data_source == DataSource.FEISHU
    assert restored.record_count == 10
    assert restored.evidence_count == 5


# ── service 层 data_context 写入 ──────────────────────────

def test_build_plan_data_context_fixture():
    from app.planning.service import _build_plan_data_context
    plan = {"plan_id": "p", "brief": {"mode": "fixture"}, "mode": "fixture"}
    ctx = _build_plan_data_context(plan, {})
    assert ctx["data_source"] == "fixture"
    assert ctx["mode"] == "fixture"


def test_build_plan_data_context_live():
    from app.planning.service import _build_plan_data_context
    plan = {"plan_id": "p", "brief": {"mode": "live"}, "mode": "live"}
    bundle = {"dataContext": {
        "data_source": "feishu", "record_count": 100, "evidence_count": 50,
        "snapshot_id": "snap-a", "generated_at": "2026-08-16T00:00:00Z",
    }}
    ctx = _build_plan_data_context(plan, bundle)
    assert ctx["data_source"] == "feishu"
    assert ctx["mode"] == "live"
    assert ctx["record_count"] == 100
    assert ctx["evidence_count"] == 50
    assert ctx["snapshot_id"] == "snap-a"


# ── live / fixture 隔离 ──────────────────────────

def test_live_does_not_fallback_to_fixture(monkeypatch):
    """live 任务在非 feishu 模式下必须显式报错，不得回退 fixture/crawled/llm"""
    monkeypatch.setenv("BASE_PROVIDER_MODE", "mock")
    from app.planning.insight_resolver import (
        LLMGenerationError,
        _resolve_insight_bundle,
    )
    with pytest.raises(LLMGenerationError):
        _resolve_insight_bundle("小风扇", {"mode": "live"})


def test_feishu_failure_no_fallback(monkeypatch):
    """feishu 模式但读取失败 → 显式报错，不静默回退 fixture"""
    monkeypatch.setenv("BASE_PROVIDER_MODE", "feishu")

    def boom(*args, **kwargs):
        raise ValueError("飞书不可用")

    monkeypatch.setattr("app.planning.live_insights.build_live_insight_bundle", boom)
    from app.planning.insight_resolver import (
        LLMGenerationError,
        _resolve_insight_bundle,
    )
    with pytest.raises(LLMGenerationError):
        _resolve_insight_bundle("小风扇", {"mode": "live"})


def test_fixture_task_still_works_without_feishu(monkeypatch):
    """fixture 任务不依赖 feishu，走 crawled/llm 路径（此处应成功或走 crawled）"""
    monkeypatch.setenv("BASE_PROVIDER_MODE", "mock")
    # fixture 任务不应抛「要求 feishu」错误，而应进入 crawled/llm 分支
    from app.planning.insight_resolver import _resolve_insight_bundle
    # 若 SocialEvidenceLoader 无该品类则走 LLM，可能因无 Key 抛 LLMGenerationError；
    # 关键断言：错误信息不得包含「要求 feishu」
    try:
        _resolve_insight_bundle("小风扇", {"mode": "fixture"})
    except Exception as exc:  # noqa: BLE001
        assert "要求 feishu" not in str(exc)


# ── 热度不标销量 ──────────────────────────

def test_heat_not_labeled_sales():
    from app.planning.live_data import _hot_rows
    from app.schemas.base_data import BasePlatform, BaseRecord

    records = [
        BaseRecord(
            record_id="1", keyword="便携小风扇", platform=BasePlatform.XIAOHONGSHU,
            category="便携小风扇", summary="s", heat_index=91.0, interaction=100.0,
            brand="品牌A", price_range="39-99", record_date="2026-08-01",
            source_url="https://example.com/1", snapshot_id="snap-a",
            ingested_at="2026-08-10T00:00:00Z",
        ),
        BaseRecord(
            record_id="2", keyword="手持小风扇", platform=BasePlatform.TIKTOK,
            category="手持小风扇", summary="s", heat_index=73.0, interaction=50.0,
            brand="品牌B", price_range="120-149", record_date="2026-08-01",
            source_url="https://example.com/2", snapshot_id="snap-a",
            ingested_at="2026-08-10T00:00:00Z",
        ),
    ]
    rows = _hot_rows(records)
    for row in rows:
        assert "sales" not in row  # 不得把热度标成销量
        assert "heat" in row


# ── live 洞察内嵌 dataContext ──────────────────────────

def test_live_insight_has_data_context():
    """live 洞察 bundle 内嵌 dataContext，且 evidence_count 来自真实 evidence refs"""
    from app.data.base_adapter import (
        BaseDataAdapter,
        MockBaseProvider,
    )
    from app.planning.live_insights import build_live_insight_bundle
    from app.schemas.base_data import BasePlatform, BaseRecord

    records = [
        BaseRecord(
            record_id="1", keyword="便携小风扇", platform=BasePlatform.XIAOHONGSHU,
            category="便携小风扇", summary="真实摘要-1", heat_index=91.0, interaction=10.0,
            brand="品牌A", price_range="39-99", record_date="2026-08-01",
            source_url="https://example.com/1", snapshot_id="snap-a",
            ingested_at="2026-08-10T00:00:00Z",
        ),
        BaseRecord(
            record_id="2", keyword="手持小风扇", platform=BasePlatform.TIKTOK,
            category="手持小风扇", summary="真实摘要-2", heat_index=73.0, interaction=5.0,
            brand="品牌B", price_range="120-149", record_date="2026-08-01",
            source_url="https://example.com/2", snapshot_id="snap-a",
            ingested_at="2026-08-10T00:00:00Z",
        ),
    ]
    adapter = BaseDataAdapter(provider=MockBaseProvider(records=records))
    bundle = build_live_insight_bundle("风扇", {"mode": "live"}, adapter)
    dc = bundle["dataContext"]
    assert dc["data_source"] == "feishu"
    assert dc["record_count"] == 2  # 父品类「风扇」聚合便携小风扇 + 手持小风扇
    assert dc["evidence_count"] == 2  # 来自真实 source_url 的 evidence refs
    assert dc["snapshot_id"] == "snap-a"
    assert bundle["evidenceCount"] == 2  # 证据数量来自真实 evidence refs，非手填
