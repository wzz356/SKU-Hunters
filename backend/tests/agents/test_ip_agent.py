"""IP 官 IPStrategyAgent 测试 — 真实实现 + provider 切换 + 权限边界

覆盖：
1. 合法 IPAssessment（确定性统计，heat_score 来自 heat_index）
2. IPDataView 正确注入
3. 不持有 BaseDataAdapter
4. 不持有其他 Agent View
5. IP 信号来自真实 View 返回
6. heat_score 不凭空生成
7. licensing_risk 缺授权信息 → 待核验
8. source_url 缺失不伪造
9. 无 IP 信号 → unknown
10. BaseUnavailable / BaseProviderError → unknown
11. real 模式不回退 Mock
12. mock/real 切换
13. graph IP 节点完整运行
14. 完整 review 无回归
"""

from __future__ import annotations

import asyncio

import pytest
from app.agents.ip_agent import IPAgent, IPStrategyAgent, get_ip_agent_class
from app.agents.mock_agents import MockIPAgent
from app.data.base_adapter import (
    BaseDataAdapter,
    BaseProviderError,
    BaseUnavailable,
    MockBaseProvider,
    RestrictedQueryPort,
)
from app.data.scoped_views import IPDataView

# ── 测试辅助 ──────────────────────────

def _record(record_id, keyword, brand, heat_index, source_url, category="IP", platform="weibo"):
    return {
        "record_id": record_id,
        "keyword": keyword,
        "platform": platform,
        "category": category,
        "summary": f"{keyword}联名话题讨论",
        "heat_index": heat_index,
        "interaction": 100.0,
        "brand": brand,
        "price_range": None,
        "record_date": "2026-08-01",
        "source_url": source_url,
        "snapshot_id": "snap-x",
        "ingested_at": "2026-08-10T10:00:00+00:00",
    }

def _view(records):
    """构造只读 IPDataView（经受限查询端口 + Mock provider）"""
    return IPDataView(
        RestrictedQueryPort(BaseDataAdapter(provider=MockBaseProvider(records=records)))
    )

def _agent(view):
    return IPStrategyAgent(views={"IPDataView": view})

def _run(agent, category="潮玩", market="CN"):
    return asyncio.run(agent.run({"brief": {"category": category, "market": market}}))

class _FailingView:
    """伪造 view：调用 get_ip_signals 即抛指定异常（数据源故障）"""

    def __init__(self, exc):
        self._exc = exc

    def get_ip_signals(self, candidates=None, as_of=None, snapshot_id=None):
        raise self._exc

# ── 1. 合法 IPAssessment ──────────────────────────

def test_valid_ip_assessment():
    view = _view([
        _record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001"),
        _record("r2", "Chiikawa", "Chiikawa", 85.0, "https://example.com/ip/002"),
    ])
    result = _run(_agent(view))
    assert result["category"] == "潮玩"
    assert result["market"] == "CN"
    assert len(result["ip_ranking"]) == 2
    # 按热度降序
    assert result["ip_ranking"][0]["ip_name"] == "三丽鸥"
    assert result["ip_ranking"][0]["heat_score"] == pytest.approx(90.0)
    assert result["ip_ranking"][1]["ip_name"] == "Chiikawa"
    # 缺数据字段 → unknown/待核验语义（不编造）
    assert result["ip_ranking"][0]["lifecycle_stage"] == "unknown"
    assert result["ip_ranking"][0]["window_estimate"] == "待核验"
    assert result["ip_ranking"][0]["regional_fit"] == 0.0
    assert result["ip_ranking"][0]["rejected"] is True
    assert result["licensing_risk"] == "待核验"
    assert result["confidence"] == "low"
    assert result["evidence_refs"]

# ── 2. IPDataView 注入 ──────────────────────────

def test_view_injection():
    view = _view([_record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001")])
    agent = _agent(view)
    assert agent.views["IPDataView"] is view
    result = _run(agent)
    assert result["confidence"] != "unknown"

# ── 3. 不持有 BaseDataAdapter ──────────────────────────

def test_no_adapter_access():
    agent = _agent(_view([]))
    assert not hasattr(agent, "adapter")
    assert not hasattr(agent, "_adapter")
    assert not hasattr(agent, "base_adapter")
    assert not hasattr(agent, "provider")

# ── 4. 不持有其他 Agent View ──────────────────────────

def test_no_other_view_access():
    agent = _agent(_view([]))
    assert "IPDataView" in agent.views
    assert "ConsumerDataView" not in agent.views
    assert "TrendDataView" not in agent.views
    assert "BusinessSummaryView" not in agent.views

# ── 5. IP 信号来自真实 View 返回 ──────────────────────────

def test_ip_signals_from_real_view():
    view = _view([_record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001")])
    result = _run(_agent(view))
    names = [c["ip_name"] for c in result["ip_ranking"]]
    assert names == ["三丽鸥"]  # 只来自真实 IP 信号的 brand，不凭空生成

# ── 6. heat_score 不凭空生成 ──────────────────────────

def test_heat_score_not_fabricated():
    view = _view([_record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001")])
    result = _run(_agent(view))
    assert result["ip_ranking"][0]["heat_score"] == pytest.approx(90.0)

def test_heat_score_aggregates_max():
    """同 IP 多条记录 → heat_score 取峰值热度（明确聚合结果，非随机）"""
    view = _view([
        _record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001"),
        _record("r2", "三丽鸥", "三丽鸥", 75.0, "https://example.com/ip/001b"),
    ])
    result = _run(_agent(view))
    assert len(result["ip_ranking"]) == 1
    assert result["ip_ranking"][0]["heat_score"] == pytest.approx(90.0)

# ── 7. 缺授权信息 licensing_risk 待核验 ──────────────────────────

def test_licensing_risk_pending():
    view = _view([_record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001")])
    result = _run(_agent(view))
    assert result["licensing_risk"] == "待核验"

# ── 8. source_url 缺失不伪造 ──────────────────────────

def test_source_url_missing_not_fabricated():
    view = _view([
        _record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001"),
        _record("r2", "Chiikawa", "Chiikawa", 85.0, None),  # 无 source_url
    ])
    result = _run(_agent(view))
    urls = [e["url"] for e in result["evidence_refs"]]
    assert urls == ["https://example.com/ip/001"]  # 不伪造 Chiikawa 链接
    # 但 heat 数据真实，两 IP 均在 ip_ranking
    names = [c["ip_name"] for c in result["ip_ranking"]]
    assert "三丽鸥" in names and "Chiikawa" in names

def test_all_source_url_missing_returns_unknown():
    """全部缺 source_url → 有信号但无证据链接 → unknown，不产出 ip_ranking"""
    view = _view([_record("r1", "三丽鸥", "三丽鸥", 90.0, None)])
    result = _run(_agent(view))
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []
    assert result["evidence_refs"] == []

# ── 9. 无 IP 信号 → unknown ──────────────────────────

def test_no_ip_signals_returns_unknown():
    view = _view([_record("r1", "小风扇", "几素", 82.5, "https://example.com/fan/001", category="小风扇")])  # 无 category="IP" 记录
    result = _run(_agent(view))
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []
    assert result["licensing_risk"] == "待核验"

def test_no_view_returns_unknown():
    agent = IPStrategyAgent(views={})  # 无 IPDataView 权限
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []

# ── 9b. 候选池过滤（Brief 范围约束） ──────────────────────────

def test_candidate_pool_filters():
    """candidate_pool 非空 → 只查询候选池中的 IP，不聚合全库"""
    view = _view([
        _record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001"),
        _record("r2", "Chiikawa", "Chiikawa", 85.0, "https://example.com/ip/002"),
    ])
    agent = _agent(view)
    result = asyncio.run(agent.run({
        "brief": {"category": "潮玩", "market": "CN", "candidate_pool": ["三丽鸥"]}
    }))
    names = [c["ip_name"] for c in result["ip_ranking"]]
    assert names == ["三丽鸥"]  # 只返回候选池中的 IP

def test_candidate_pool_empty_returns_all():
    """candidate_pool 为空 → 显式返回全库 Top IP（非隐含空 keyword 不过滤）"""
    view = _view([
        _record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001"),
        _record("r2", "Chiikawa", "Chiikawa", 85.0, "https://example.com/ip/002"),
    ])
    agent = _agent(view)
    result = asyncio.run(agent.run({
        "brief": {"category": "潮玩", "market": "CN", "candidate_pool": []}
    }))
    names = [c["ip_name"] for c in result["ip_ranking"]]
    assert names == ["三丽鸥", "Chiikawa"]  # 空候选池 → 全库 Top IP

def test_candidate_pool_no_match_returns_unknown():
    """candidate_pool 无匹配 → 无 IP 信号 → unknown"""
    view = _view([_record("r1", "三丽鸥", "三丽鸥", 90.0, "https://example.com/ip/001")])
    agent = _agent(view)
    result = asyncio.run(agent.run({
        "brief": {"category": "潮玩", "market": "CN", "candidate_pool": ["不存在的IP"]}
    }))
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []

# ── 10. 数据源故障 → unknown ──────────────────────────

def test_base_unavailable_returns_unknown():
    agent = IPStrategyAgent(views={"IPDataView": _FailingView(BaseUnavailable("无配置"))})
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []
    assert result["licensing_risk"] == "待核验"

def test_base_provider_error_returns_unknown():
    agent = IPStrategyAgent(views={"IPDataView": _FailingView(BaseProviderError("网络超时"))})
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []

# ── 11. real 模式不回退 Mock ──────────────────────────

def test_real_mode_does_not_fallback(monkeypatch):
    monkeypatch.setenv("IP_AGENT_PROVIDER", "deterministic")
    assert get_ip_agent_class() is IPStrategyAgent
    agent = IPStrategyAgent(views={"IPDataView": _FailingView(BaseUnavailable("无配置"))})
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["ip_ranking"] == []  # 不回退 Mock 的固定 Chiikawa/Loopy

# ── 12. mock/real 切换 ──────────────────────────

def test_mock_real_switch(monkeypatch):
    assert get_ip_agent_class() is MockIPAgent  # 默认 mock
    monkeypatch.setenv("IP_AGENT_PROVIDER", "real")
    assert get_ip_agent_class() is IPAgent  # LLM 研判版
    monkeypatch.setenv("IP_AGENT_PROVIDER", "deterministic")
    assert get_ip_agent_class() is IPStrategyAgent  # 确定性聚合版
    monkeypatch.setenv("IP_AGENT_PROVIDER", "mock")
    assert get_ip_agent_class() is MockIPAgent

# ── 13. graph IP 节点完整运行 ──────────────────────────

def test_graph_ip_node_runs(monkeypatch):
    from app.engine import connector_gateway
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent

    # 重置 Base adapter 单例，确保 BASE_PROVIDER_MODE=mock 生效
    monkeypatch.setattr(connector_gateway, "_base_adapter", None)
    monkeypatch.setenv("BASE_PROVIDER_MODE", "mock")
    monkeypatch.setitem(AGENT_REGISTRY, "ip", IPStrategyAgent)

    agent = _instantiate_agent("ip")
    assert isinstance(agent, IPStrategyAgent)
    result = asyncio.run(agent.run({"brief": {"category": "潮玩", "market": "CN"}, "feedback": []}))
    assert result["category"] == "潮玩"
    assert result["market"] == "CN"
    assert isinstance(result["ip_ranking"], list)
    # fixture-004 是 category="IP" 记录（brand=三丽鸥，heat_index=90）
    assert any(c["ip_name"] == "三丽鸥" for c in result["ip_ranking"])

def test_graph_ip_agent_gets_ip_data_view(monkeypatch):
    """graph 工厂经网关注入 IPDataView，不注入其他 view 或 adapter"""
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent

    monkeypatch.setitem(AGENT_REGISTRY, "ip", IPStrategyAgent)
    agent = _instantiate_agent("ip")
    assert hasattr(agent, "views")
    assert "IPDataView" in agent.views
    assert isinstance(agent.views["IPDataView"], IPDataView)
    assert "ConsumerDataView" not in agent.views
    assert "TrendDataView" not in agent.views
    assert not isinstance(agent, BaseDataAdapter)
    assert not hasattr(agent, "adapter")

# ── 14. 完整 review 无回归 ──────────────────────────

async def test_full_review_no_regression():
    from app.engine.graph import run_review

    async def ask(gate):
        if gate["gate"] == "retro":
            return {"action": "done"}
        return {"action": "confirm"}

    events = [e async for e in run_review(
        {"category": "解压玩具", "market": "CN", "budget_range": "mid"}, ask_human=ask
    )]
    roles = [e["role"] for e in events]
    assert "ip" in roles
    assert roles[-1] == "learning"
