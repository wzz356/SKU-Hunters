"""SQLite 持久化测试 — 外键 / UPSERT / 异常安全

使用临时数据库（monkeypatch _DB_PATH），不污染 data/committee.db 真实数据。
"""

from __future__ import annotations

import sqlite3

import pytest
from app import store


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    """每个测试独立临时 DB，测试后关闭连接"""
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "committee_test.db")
    store.close()  # 重置当前线程连接，确保用新路径
    yield
    store.close()


def test_retro_logs_survive_session_update(isolated_store):
    """session 经 UPSERT 更新后，retro_logs 不丢失"""
    sid = "sess_test"
    store.create(sid, {"category": "小风扇", "market": "CN", "budget_range": "low"})
    store.add_retro_log(sid, "为什么否决？", "因为成本超预算")

    # 再次落盘（触发 UPSERT，而非 INSERT OR REPLACE 先删父行）
    store.create_or_update(
        sid,
        brief={"category": "小风扇", "market": "CN", "budget_range": "low"},
        status="approved",
        archive={"retro_turns": 1},
    )

    logs = store.list_retro_logs(sid)
    assert len(logs) == 1
    assert logs[0]["question"] == "为什么否决？"
    assert logs[0]["answer"] == "因为成本超预算"


def test_foreign_key_enforced(isolated_store):
    """外键约束生效：retro_log 引用不存在的 session 必须被拒绝"""
    with pytest.raises(sqlite3.IntegrityError):
        store.add_retro_log("nonexistent_session", "q", "a")


def test_no_duplicate_session(isolated_store):
    """UPSERT 不会产生重复 session"""
    sid = "sess_test"
    brief = {"category": "小风扇", "market": "CN", "budget_range": "low"}
    store.create_or_update(sid, brief=brief, status="completed")
    store.create_or_update(sid, brief=brief, status="approved", final_action="approve")

    sessions = store.list_all()
    matched = [s for s in sessions if s["session_id"] == sid]
    assert len(matched) == 1
    assert matched[0]["status"] == "approved"


def test_write_error_preserves_existing(isolated_store):
    """一次写入异常（外键违反）不会破坏已有数据"""
    sid = "sess_test"
    store.create(sid, {"category": "小风扇", "market": "CN", "budget_range": "low"})
    store.create_or_update(
        sid,
        brief={"category": "小风扇", "market": "CN", "budget_range": "low"},
        status="completed",
    )

    # 触发失败写入（外键违反），应回滚、不影响已提交数据
    with pytest.raises(sqlite3.IntegrityError):
        store.add_retro_log("ghost_session", "q", "a")

    d = store.get(sid)
    assert d is not None
    assert d["status"] == "completed"
    assert d["brief"]["category"] == "小风扇"
