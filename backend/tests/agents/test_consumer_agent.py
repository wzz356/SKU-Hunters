"""用户官 ConsumerInsightAgent 测试 — 真实实现 + provider 切换 + 权限边界

覆盖：
1. 合法 UserSentiment（确定性统计，sentiment 总和=1.0）
2. View 注入（经 views 拿 ConsumerDataView）
3. 无法访问 BaseDataAdapter（不持有 raw adapter）
4. 无法访问其他 View（只有 ConsumerDataView）
5. evidence 来自实际记录
6. source_url 缺失不伪造
7. BaseUnavailable / BaseProviderError → unknown
8. 空数据 / 无 View → unknown
9. SentimentStat 总和≠1 阻断
10. 不经过 LLM、不编造（输出全部来自 signals）
11. mock/real 切换
12. 完整 review 无回归
"""

from __future__ import annotations

import asyncio

import pytest
from app.agents.consumer_agent import ConsumerInsightAgent, get_consumer_agent_class
from app.agents.mock_agents import MockUserAgent
from app.data.base_adapter import (
    BaseDataAdapter,
    BaseProviderError,
    BaseUnavailable,
    MockBaseProvider,
    RestrictedQueryPort,
)
from app.data.scoped_views import ConsumerDataView
from app.schemas import SentimentStat

# ── 测试辅助 ──────────────────────────

def _record(record_id, keyword, category, summary, source_url, platform="xiaohongshu", heat_index=80.0):
    return {
        "record_id": record_id,
        "keyword": keyword,
        "platform": platform,
        "category": category,
        "summary": summary,
        "heat_index": heat_index,
        "interaction": 100.0,
        "brand": None,
        "price_range": None,
        "record_date": "2026-08-01",
        "source_url": source_url,
        "snapshot_id": "snap-x",
        "ingested_at": "2026-08-10T10:00:00+00:00",
    }

def _view(records):
    """构造只读 ConsumerDataView（经受限查询端口 + Mock provider）"""
    return ConsumerDataView(
        RestrictedQueryPort(BaseDataAdapter(provider=MockBaseProvider(records=records)))
    )

def _agent(view):
    return ConsumerInsightAgent(views={"ConsumerDataView": view})

def _run(agent, category="小风扇"):
    return asyncio.run(agent.run({"brief": {"category": category}}))

class _FailingView:
    """伪造 view：调用 get_category_signals 即抛指定异常（数据源故障）"""

    def __init__(self, exc):
        self._exc = exc

    def get_category_signals(self, category, as_of=None, snapshot_id=None):
        raise self._exc

# ── 1. 合法 UserSentiment ──────────────────────────

def test_valid_user_sentiment():
    view = _view([
        _record("r1", "小风扇", "小风扇", "便携小风扇收纳困难", "https://example.com/fan/1"),
    ])
    result = _run(_agent(view))
    assert result["product_category"] == "小风扇"
    assert result["confidence"] == "medium"
    s = result["sentiment"]
    assert s["positive"] + s["neutral"] + s["negative"] == pytest.approx(1.0)
    assert s["neutral"] == 1.0  # BaseRecord 无情感标注，中性诚实表示
    # 痛点从 summary 确定性提取（含"难"关键词）
    assert any("收纳困难" in p["description"] for p in result["pain_points"])
    # 动机标签来自 keyword
    assert result["motivation_tags"] == ["小风扇"]
    # 有证据引用
    assert result["evidence_refs"]

# ── 2. View 注入 ──────────────────────────

def test_view_injection():
    view = _view([_record("r1", "小风扇", "小风扇", "s", "https://example.com/fan/1")])
    agent = _agent(view)
    assert agent.views["ConsumerDataView"] is view
    result = _run(agent)
    assert result["confidence"] != "unknown"  # 有数据，正常产出

# ── 3. 无法访问 BaseDataAdapter ──────────────────────────

def test_no_adapter_access():
    agent = _agent(_view([]))
    assert not hasattr(agent, "adapter")
    assert not hasattr(agent, "_adapter")
    assert not hasattr(agent, "base_adapter")
    assert not hasattr(agent, "provider")

# ── 4. 无法访问其他 View ──────────────────────────

def test_no_other_view_access():
    agent = _agent(_view([]))
    assert "ConsumerDataView" in agent.views
    assert "TrendDataView" not in agent.views
    assert "IPDataView" not in agent.views
    assert "BusinessSummaryView" not in agent.views

# ── 5. evidence 来自实际记录 ──────────────────────────

def test_evidence_from_actual_records():
    view = _view([_record("r1", "小风扇", "小风扇", "收纳", "https://example.com/fan/1")])
    result = _run(_agent(view))
    urls = [e["url"] for e in result["evidence_refs"]]
    assert "https://example.com/fan/1" in urls

# ── 6. source_url 缺失不伪造 ──────────────────────────

def test_source_url_missing_not_fabricated():
    view = _view([
        _record("r1", "小风扇", "小风扇", "s1", "https://example.com/fan/1"),
        _record("r2", "小风扇", "小风扇", "s2", None),  # 无 source_url
    ])
    result = _run(_agent(view))
    urls = [e["url"] for e in result["evidence_refs"]]
    assert urls == ["https://example.com/fan/1"]  # 只含有 URL 的记录，不伪造

def test_all_source_url_missing_returns_unknown():
    """全部记录缺 source_url → 有信号但无证据链接，诚实降为 unknown，不编造链接"""
    view = _view([_record("r1", "小风扇", "小风扇", "有信号但无链接", None)])
    result = _run(_agent(view))
    assert result["confidence"] == "unknown"
    assert result["evidence_refs"] == []
    assert result["caveats"]  # 主动声明不确定性

# ── 7. 数据源故障 → unknown ──────────────────────────

def test_base_unavailable_returns_unknown():
    agent = ConsumerInsightAgent(views={"ConsumerDataView": _FailingView(BaseUnavailable("无配置"))})
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["sentiment"]["neutral"] == 1.0
    assert result["pain_points"] == []
    assert result["evidence_refs"] == []
    assert result["caveats"]

def test_base_provider_error_returns_unknown():
    """飞书网络/服务错误也返回 unknown，不崩溃、不编造"""
    agent = ConsumerInsightAgent(views={"ConsumerDataView": _FailingView(BaseProviderError("网络超时"))})
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["caveats"]

# ── 8. 空数据 / 无 View → unknown ──────────────────────────

def test_empty_data_returns_unknown():
    view = _view([])  # 品类无记录
    result = _run(_agent(view), category="不存在品类")
    assert result["confidence"] == "unknown"
    assert result["evidence_refs"] == []
    assert result["pain_points"] == []
    assert result["motivation_tags"] == []

def test_no_view_returns_unknown():
    agent = ConsumerInsightAgent(views={})  # 无 ConsumerDataView 权限
    result = _run(agent)
    assert result["confidence"] == "unknown"
    assert result["caveats"]

# ── 9. SentimentStat 总和≠1 阻断 ──────────────────────────

def test_sentiment_sum_not_one_blocks():
    bad = SentimentStat(positive=0.5, neutral=0.5, negative=0.5)  # 总和 1.5
    with pytest.raises(ValueError):
        ConsumerInsightAgent._validate_sentiment(bad)

# ── 10. 不经过 LLM、不编造 ──────────────────────────

def test_no_llm_no_fabrication(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("用户官不应调用 LLM")

    monkeypatch.setattr("app.engine.llm.complete", boom)
    view = _view([_record("r1", "小风扇", "小风扇", "便携收纳难", "https://example.com/fan/1")])
    result = _run(_agent(view))
    # 正常返回，说明全程未触发 LLM；输出全部来自 signals
    assert result["confidence"] == "medium"
    assert result["motivation_tags"] == ["小风扇"]
    assert result["summary"].startswith("品类「小风扇」")

# ── 11. mock/real 切换 ──────────────────────────

def test_mock_real_switch(monkeypatch):
    assert get_consumer_agent_class() is MockUserAgent  # 默认 mock
    monkeypatch.setenv("CONSUMER_AGENT_PROVIDER", "real")
    assert get_consumer_agent_class() is ConsumerInsightAgent
    monkeypatch.setenv("CONSUMER_AGENT_PROVIDER", "mock")
    assert get_consumer_agent_class() is MockUserAgent

def test_real_mode_does_not_fallback_to_mock(monkeypatch):
    """real 模式下数据源故障 → unknown，绝不回退 Mock 固定产物"""
    monkeypatch.setenv("CONSUMER_AGENT_PROVIDER", "real")
    assert get_consumer_agent_class() is ConsumerInsightAgent
    agent = ConsumerInsightAgent(views={"ConsumerDataView": _FailingView(BaseUnavailable("无配置"))})
    result = _run(agent)
    assert result["confidence"] == "unknown"
    # MockUserAgent 会返回固定的 MEDIUM + 非空痛点，这里必须不是它
    assert result["pain_points"] == []

# ── 12. 完整 review 无回归 ──────────────────────────

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
    assert "user" in roles
    assert roles[-1] == "learning"
