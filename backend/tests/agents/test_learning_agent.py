"""LearningAgent 测试 — 真实学习官 + NormalizedActualSignal + 复盘契约

覆盖：四种 status、非法/缺失指标、数据源故障保守、权限边界、
RetroLedgerWriter 只追加、首次/二次 learning 流程、provider 切换。
"""

from __future__ import annotations

import asyncio

from app.agents.learning_agent import (
    LearningAgent,
    MockLearningAgent,
    get_learning_agent_class,
)
from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.data.scoped_views import RetroLedgerWriter
from app.schemas import RetroReport

# ── 测试辅助 ──────────────────────────

def _sales_signal(**metrics):
    sig = {"keyword": "潮玩", "record_date": "2026-09-01"}
    sig.update(metrics)
    return sig

class _FakeView:
    def __init__(self, outcome_signals=None, exc=None):
        self._outcome = outcome_signals if outcome_signals is not None else []
        self._exc = exc

    def get_outcome_signals(self, category, as_of=None, snapshot_id=None):
        if self._exc:
            raise self._exc
        return self._outcome

def _agent(view=None, write_port=None):
    views = {"LearningLedgerReadView": view} if view is not None else {}
    return LearningAgent(views=views, write_port=write_port)

def _context(category="潮玩", market="CN", proposal_name="方案A"):
    return {
        "brief": {"category": category, "market": market, "budget_range": "mid"},
        "category": category, "market": market,
        "proposal": {"name": proposal_name, "concept": "概念", "price_band": "¥39-59"},
        "opportunity_score": {
            "proposal_name": proposal_name, "total_score": 75.0,
            "dimension_scores": [
                {"dimension": "trend_heat", "score": 90.0, "source_agent": "a", "basis": "b"},
                {"dimension": "user_demand", "score": 48.0, "source_agent": "a", "basis": "b"},
                {"dimension": "ip_fit", "score": 85.0, "source_agent": "a", "basis": "b"},
                {"dimension": "competition", "score": 80.0, "source_agent": "a", "basis": "b"},
                {"dimension": "history_analog", "score": 65.0, "source_agent": "a", "basis": "b"},
            ],
        },
        "decision": "approve", "human_action": "approve",
        "session_id": "sess-001", "snapshot_id": "sess-001",
    }

def _run(agent, context):
    return asyncio.run(agent.run(context))

# ── 1. 四种 status ──────────────────────────

def test_observed_status():
    view = _FakeView(outcome_signals=[
        _sales_signal(first_month_sales_attainment=0.8, sell_through_rate=0.7,
                      sellout_rate=0.6, social_buzz_persistence=0.5),
    ])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "observed"
    assert sig["confidence"] == "medium"

def test_partial_status():
    view = _FakeView(outcome_signals=[_sales_signal(first_month_sales_attainment=0.8)])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "partial"
    assert sig["confidence"] == "low"

def test_unavailable_status():
    view = _FakeView(outcome_signals=[])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "unavailable"
    assert sig["confidence"] == "unknown"
    assert sig["metrics"] == {}

def test_invalid_status():
    view = _FakeView(outcome_signals=[_sales_signal(first_month_sales_attainment=2.5)])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "invalid"
    assert sig["metrics"] == {}

# ── 2/3. 非法/缺失指标 ──────────────────────────

def test_invalid_metric_skipped():
    view = _FakeView(outcome_signals=[
        _sales_signal(first_month_sales_attainment=0.8, sell_through_rate=1.5),
    ])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["metrics"] == {"first_month_sales_attainment": 0.8}  # 非法指标跳过
    assert any("非法指标已跳过" in c for c in sig["caveats"])

def test_missing_metric_not_zero():
    view = _FakeView(outcome_signals=[_sales_signal(first_month_sales_attainment=0.8)])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert "sell_through_rate" not in sig["metrics"]  # 缺失不默认填 0

def test_period_source_from_records():
    view = _FakeView(outcome_signals=[
        _sales_signal(first_month_sales_attainment=0.8, source="pos_actuals"),
    ])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["period"] == "2026-09-01"  # 从 record_date 提取
    assert sig["source"] == "pos_actuals"  # 用记录真实提供的 source

def test_period_source_fallback():
    view = _FakeView(outcome_signals=[
        _sales_signal(first_month_sales_attainment=0.8, record_date="", source=""),
    ])
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["source"] == "learning_ledger"  # 缺失时明确用 learning_ledger

# ── 4. 无 sales_actuals → unavailable ──────────────────────────

def test_heat_index_not_sales_actuals():
    view = _FakeView(outcome_signals=[{"keyword": "潮玩", "heat_index": 80.0}])  # 只有热度
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "unavailable"

# ── 5/6. 数据源故障 → unknown 不崩溃 ──────────────────────────

def test_base_unavailable_unknown(monkeypatch):
    monkeypatch.setenv("LEARNING_AGENT_PROVIDER", "real")
    assert get_learning_agent_class() is LearningAgent
    view = _FakeView(exc=BaseUnavailable("无配置"))
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "unavailable"
    assert sig["confidence"] == "unknown"

def test_base_provider_error_unknown(monkeypatch):
    monkeypatch.setenv("LEARNING_AGENT_PROVIDER", "real")
    view = _FakeView(exc=BaseProviderError("网络超时"))
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["status"] == "unavailable"
    assert sig["confidence"] == "unknown"

# ── 7. 无 evidence 不伪造 URL ──────────────────────────

def test_no_evidence_no_fabrication():
    view = _FakeView(outcome_signals=[_sales_signal(first_month_sales_attainment=0.8)])  # 无 source_url
    sig = _run(_agent(view), _context())["normalized_actual_signal"]
    assert sig["evidence_refs"] == []

# ── 8. 不调用 LLM ──────────────────────────

def test_no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("学习官不应调用 LLM")
    monkeypatch.setattr("app.engine.llm.complete", boom)
    view = _FakeView(outcome_signals=[_sales_signal(first_month_sales_attainment=0.8)])
    out = _run(_agent(view), _context())
    assert "retro_report" in out  # 正常返回，未触发 boom

# ── 9/10. 权限边界 ──────────────────────────

def test_only_learning_view():
    agent = _agent(_FakeView())
    assert "LearningLedgerReadView" in agent.views
    assert "TrendDataView" not in agent.views
    assert "ConsumerDataView" not in agent.views
    assert "IPDataView" not in agent.views
    assert "BusinessSummaryView" not in agent.views

def test_no_adapter():
    agent = _agent(_FakeView())
    assert not hasattr(agent, "adapter")
    assert not hasattr(agent, "_adapter")
    assert not hasattr(agent, "base_adapter")

# ── 11/12. RetroLedgerWriter 只追加 ──────────────────────────

def test_retro_writer_append_only():
    ledger: list = []
    writer = RetroLedgerWriter(ledger)
    writer.append_retro_entry("sess-1", "q", "a")
    assert len(ledger) == 1
    assert not hasattr(writer, "clear")
    assert not hasattr(writer, "overwrite")
    assert not hasattr(writer, "remove")

def test_write_port_no_overwrite():
    old = {"session_id": "s1", "question": "q1", "answer": "a1", "timestamp": "t1"}
    ledger = [old]
    writer = RetroLedgerWriter(ledger)
    writer.append_retro_entry("s2", "q2", "a2")
    assert len(ledger) == 2
    assert ledger[0] == old  # 历史保留，未被覆盖

# ── 13/14/15. RetroReport 契约 ──────────────────────────

def test_retro_report_schema():
    view = _FakeView(outcome_signals=[])
    retro = _run(_agent(view), _context())["retro_report"]
    RetroReport.model_validate(retro)  # 通过现有 Schema

def test_weight_advice_none_no_actual():
    view = _FakeView(outcome_signals=[])
    retro = _run(_agent(view), _context())["retro_report"]
    assert retro["weight_advice"] is None
    assert retro["advice_basis_periods"] == 0

def test_dimension_gaps_unavailable():
    view = _FakeView(outcome_signals=[])
    retro = _run(_agent(view), _context())["retro_report"]
    for g in retro["dimension_gaps"]:
        assert g["actual_signal"] == "unavailable"
        assert g["accuracy"] == "unknown"

# ── 16. reject bad case 同样生成学习档案 ──────────────────────────

async def _min_state(decision="reject"):
    return {
        "session_id": "sess",
        "review_logs": [{"node": "human_gate", "decision": decision}],
        "recommendation": {
            "proposal": {"name": "方案A"},
            "opportunity_score": {"total_score": 75.0},
            "decision": "approve",
        },
        "brief": {"category": "潮玩", "market": "CN"},
    }

async def test_reject_bad_case_archived():
    from app.engine.graph import learning_node
    out = await learning_node(await _min_state("reject"))
    log = out["review_logs"][-1]
    assert log["snapshot"]["status"] == "rejected"
    assert "retro_reports" in out

async def test_approve_archived():
    from app.engine.graph import learning_node
    out = await learning_node(await _min_state("approve"))
    log = out["review_logs"][-1]
    assert log["snapshot"]["status"] == "archived"

# ── 17/18/19. 首次/二次 learning 流程 ──────────────────────────

async def test_first_pass_creates_snapshot():
    from app.engine.graph import learning_node
    out = await learning_node(await _min_state())
    log = out["review_logs"][-1]
    assert "snapshot" in log
    assert len(out.get("retro_reports", [])) == 1

async def test_second_pass_appends_retro_turns_only():
    from app.engine.graph import learning_node
    out1 = await learning_node(await _min_state())
    log1 = out1["review_logs"][-1]
    state2 = {
        "session_id": "sess",
        "review_logs": [log1, {"node": "retro", "answer": "a1"}, {"node": "retro", "answer": "a2"}],
        "recommendation": {"proposal": {"name": "方案A"}, "opportunity_score": {"total_score": 75.0}, "decision": "approve"},
        "brief": {"category": "潮玩", "market": "CN"},
    }
    out2 = await learning_node(state2)
    log2 = out2["review_logs"][-1]
    assert log2.get("appended") is True
    assert log2["snapshot"]["retro_turns"] == 2
    assert "retro_reports" not in out2  # 二过不重复生成 RetroReport

async def test_first_pass_snapshot_has_learning_fields():
    from app.engine.graph import learning_node
    out = await learning_node(await _min_state())
    log = out["review_logs"][-1]
    assert "normalized_actual_signal" in log["snapshot"]
    assert "retro_report" in log["snapshot"]
    assert log["snapshot"]["retro_report"]["proposal_name"] == "方案A"

async def test_second_pass_keeps_learning_fields():
    from app.engine.graph import learning_node
    out1 = await learning_node(await _min_state())
    log1 = out1["review_logs"][-1]
    state2 = {
        "session_id": "sess",
        "review_logs": [log1, {"node": "retro", "answer": "a1"}],
        "recommendation": {"proposal": {"name": "方案A"}, "opportunity_score": {"total_score": 75.0}, "decision": "approve"},
        "brief": {"category": "潮玩", "market": "CN"},
    }
    out2 = await learning_node(state2)
    log2 = out2["review_logs"][-1]
    assert "normalized_actual_signal" in log2["snapshot"]  # 二过保留
    assert "retro_report" in log2["snapshot"]
    assert log2["snapshot"]["retro_turns"] == 1

# ── 21. full_review 无回归 ──────────────────────────

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
    assert roles[-1] == "learning"
    learning_events = [e for e in events if e["role"] == "learning"]
    assert len(learning_events) == 2  # learning 事件出现两次

# ── 22. graph 工厂注入 learning agent ──────────────────────────

def test_graph_injects_learning_agent(monkeypatch):
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent
    monkeypatch.setitem(AGENT_REGISTRY, "learning", LearningAgent)
    agent = _instantiate_agent("learning")
    assert isinstance(agent, LearningAgent)
    assert "LearningLedgerReadView" in agent.views
    assert hasattr(agent, "write_port")  # RetroLedgerWriter 注入
    assert not hasattr(agent, "adapter")

# ── 23. provider 切换 ──────────────────────────

def test_mock_real_switch(monkeypatch):
    assert get_learning_agent_class() is MockLearningAgent
    monkeypatch.setenv("LEARNING_AGENT_PROVIDER", "real")
    assert get_learning_agent_class() is LearningAgent
    monkeypatch.setenv("LEARNING_AGENT_PROVIDER", "mock")
    assert get_learning_agent_class() is MockLearningAgent
