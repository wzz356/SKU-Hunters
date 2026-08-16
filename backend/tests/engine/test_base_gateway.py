"""Base 数据网关集成测试 — resolve_views / resolve_write_port / 工厂经网关注入"""

from __future__ import annotations

import pytest
from app.data.base_adapter import BaseDataAdapter
from app.data.scoped_views import (
    LearningLedgerReadView,
    RetroLedgerWriter,
    TrendDataView,
)
from app.engine.connector_gateway import (
    DataAccessViolation,
    resolve_connector,
    resolve_views,
    resolve_write_port,
)


def test_resolve_views_trend():
    """趋势官拿到 TrendDataView"""
    views = resolve_views("trend_agent")
    assert "TrendDataView" in views
    assert isinstance(views["TrendDataView"], TrendDataView)


def test_resolve_views_creative_empty():
    """创意官（product_ideation）不持有任何数据视图"""
    assert resolve_views("product_ideation_agent") == {}


def test_resolve_views_returns_view_not_adapter():
    """resolve_views 返回的是 Scoped View，不是原始 BaseDataAdapter"""
    views = resolve_views("trend_agent")
    view = views["TrendDataView"]
    assert isinstance(view, TrendDataView)
    assert not isinstance(view, BaseDataAdapter)


def test_resolve_views_unknown_agent_empty():
    """未知 agent key → 空视图（fail-closed）"""
    assert resolve_views("nonexistent_agent") == {}


def test_resolve_views_learning_read_only_view():
    """学习官拿到只读台账视图（LearningLedgerReadView，非写入端口）"""
    views = resolve_views("learning_agent")
    assert "LearningLedgerReadView" in views
    assert isinstance(views["LearningLedgerReadView"], LearningLedgerReadView)


def test_resolve_write_port_learning():
    """学习官有独立复盘写入端口 RetroLedgerWriter"""
    port = resolve_write_port("learning_agent")
    assert isinstance(port, RetroLedgerWriter)


def test_resolve_write_port_other_none():
    """非学习官无写入端口（读取与写入分离）"""
    assert resolve_write_port("trend_agent") is None
    assert resolve_write_port("business_evaluation_agent") is None
    assert resolve_write_port("product_ideation_agent") is None


def test_readonly_source_fail_closed():
    """readonly_sources（未实现的只读数据源）不能作为运行时 connector 解析"""
    # social_snapshot 在 trend_agent 的 readonly_sources，不在 connectors
    with pytest.raises(DataAccessViolation):
        resolve_connector("trend_agent", "social_snapshot")


def test_instantiate_agent_injects_views(monkeypatch):
    """Agent 工厂经网关注入 Scoped View（不直接持有 raw adapter）"""
    from app.agents.trend_agent import TrendAgent
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent

    monkeypatch.setitem(AGENT_REGISTRY, "trend", TrendAgent)
    agent = _instantiate_agent("trend")
    assert hasattr(agent, "views")
    assert "TrendDataView" in agent.views
    assert not isinstance(agent, BaseDataAdapter)


def test_instantiate_agent_creative_no_views():
    """创意官实例不持有任何数据视图（物理隔离）"""
    from app.engine.graph import _instantiate_agent

    agent = _instantiate_agent("creative")
    assert agent.views == {}
    assert agent.write_port is None

