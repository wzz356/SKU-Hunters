"""Connector 白名单隔离测试 — 运行时信息隔离（fail-closed）"""

from __future__ import annotations

import pytest
from app.engine.connector_gateway import (
    DataAccessViolation,
    resolve_connector,
    resolve_connectors,
)


def test_product_ideation_cannot_access_raw_data():
    """创意官白名单不含原始数据源（物理隔离，而非 prompt 声明）"""
    connectors = resolve_connectors("product_ideation_agent")
    assert "google_trends" not in connectors
    assert "bilibili_ranking" not in connectors
    assert "taobao_suggest" not in connectors
    # 只含已实现且白名单内的数据源（artifact_store/hit_case_library 未实现，被跳过）
    assert connectors == {}


def test_trend_agent_can_access_its_connectors():
    """趋势官白名单内的真实 connector 可解析"""
    connectors = resolve_connectors("trend_agent")
    assert "google_trends" in connectors
    assert "bilibili_ranking" in connectors


def test_resolve_connector_rejects_out_of_whitelist():
    """白名单外的数据源被拒绝"""
    with pytest.raises(DataAccessViolation):
        resolve_connector("product_ideation_agent", "google_trends")


def test_resolve_connector_allows_in_whitelist():
    """白名单内的数据源可解析为实例"""
    connector = resolve_connector("trend_agent", "google_trends")
    assert connector is not None


def test_resolve_connector_fail_closed_unimplemented():
    """已声明但未实现的 connector fail-closed（拒绝，而非伪造）"""
    with pytest.raises(DataAccessViolation):
        resolve_connector("trend_agent", "social_snapshot")


def test_unknown_agent_key_empty():
    """未知 agent_key 无白名单，返回空映射"""
    assert resolve_connectors("nonexistent_agent") == {}


def test_instantiate_agent_trend_injects_connector(monkeypatch):
    """graph 的 Agent 创建路径经网关注入 connector（信息隔离集成验证）"""
    from app.agents.trend_agent import TrendAgent
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent

    monkeypatch.setitem(AGENT_REGISTRY, "trend", TrendAgent)
    agent = _instantiate_agent("trend")
    assert isinstance(agent, TrendAgent)
    assert agent.google is not None  # google_trends 经网关注入
    assert agent.bilibili is not None  # bilibili_ranking 经网关注入


def test_instantiate_agent_creative_no_raw_connector():
    """创意官（product_ideation）不获得原始数据源 connector"""
    from app.engine.graph import _instantiate_agent

    agent = _instantiate_agent("creative")
    # 创意官非 TrendAgent（真实数据源 agent），不持有 google/bilibili connector
    assert not hasattr(agent, "google")
    assert not hasattr(agent, "bilibili")
