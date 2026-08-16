"""planning repository 并发安全测试 — 状态推进串行 + 并发保存不覆盖"""

from __future__ import annotations

import threading

import pytest
from app.planning import repository, service
from app.planning.service import StateTransitionError

BRIEF = {
    "theme": "并发测试主题",
    "category": "小风扇",
    "priceRange": [39, 99],
    "costLimit": 25,
}


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    snapshot = dict(repository._PLANS)
    repository._PLANS.clear()
    monkeypatch.setattr(repository, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(repository, "_STATE_FILE", tmp_path / "plans_state.json")
    monkeypatch.setattr(repository, "_LEGACY_STATE_FILE", tmp_path / "legacy_plans_state.json")
    yield
    repository._PLANS.clear()
    repository._PLANS.update(snapshot)


def test_concurrent_generate_insights_single_advance():
    """同一 plan 并发推进状态：plan 写锁保证只推进一次"""
    plan = repository.create_plan(BRIEF)
    plan_id = plan["plan_id"]

    results: list[str] = []
    errors: list[str] = []

    def worker():
        try:
            service.generate_insights(repository.get_plan(plan_id))
            results.append("ok")
        except StateTransitionError:
            errors.append("transition")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 恰好一次成功，其余因状态已推进而拒绝
    assert len(results) == 1
    assert len(errors) == 3
    assert repository.get_plan(plan_id)["status"] == "insights_ready"


def test_concurrent_save_state_no_corruption():
    """并发保存多个 plan：唯一临时文件名保证落盘完整、不互相覆盖"""
    plans = [repository.create_plan(BRIEF) for _ in range(5)]
    plan_ids = {p["plan_id"] for p in plans}

    def worker(pid: str):
        # 通过 service 原子操作触发 _save_state（整个 _PLANS 落盘）
        plan = repository.get_plan(pid)
        service.generate_insights(plan)

    threads = [threading.Thread(target=worker, args=(pid,)) for pid in plan_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 并发 _save_state 后，文件应包含全部 5 个 plan，且状态正确
    saved = repository._load_state()
    assert set(saved.keys()) == plan_ids
    for p in saved.values():
        assert p["status"] == "insights_ready"
