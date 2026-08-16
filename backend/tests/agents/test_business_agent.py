"""商业官 BusinessEvaluationAgent 测试 — 真实实现 + 纯函数 + provider 切换

覆盖五维评分公式、确定性算术、权限边界、数据缺失保守策略、provider 切换。
测试使用 fake BusinessSummaryView 与固定 Artifact，不使用真实飞书凭证。
"""

from __future__ import annotations

import asyncio

import pytest
from app.agents.business_agent import (
    BusinessAgent,
    BusinessEvaluationAgent,
    clamp,
    get_business_agent_class,
    score_competition,
    score_history_analog,
    score_ip_fit,
    score_trend_heat,
    score_user_demand,
)
from app.agents.mock_agents import MockBusinessAgent
from app.data.base_adapter import BaseUnavailable
from app.engine.context_contract import validate_gtm_context
from app.schemas import OpportunityScore

# ── 测试辅助 ──────────────────────────

_WEIGHTS = {
    "trend_heat": 0.35, "user_demand": 0.25, "ip_fit": 0.20,
    "competition": 0.10, "history_analog": 0.10,
}

def _brief(category="潮玩", market="CN"):
    return {"category": category, "market": market, "budget_range": "mid"}

def _proposal(name, concept="", source_map=None):
    return {
        "name": name, "concept": concept, "product_form": "桌面摆件",
        "target_segment": "年轻女性", "price_band": "¥39-59",
        "source_map": source_map or [], "differentiation": "差异化",
    }

def _feature_matrix(heats):
    trends = [
        {"keyword": f"kw{i}", "heat_index": h, "platform": "小红书",
         "region": "CN", "lifecycle": "rising"}
        for i, h in enumerate(heats)
    ]
    return {
        "category": "潮玩", "region": "CN", "trends": trends, "summary": "",
        "analysis_date": "2026-08-01",
        "evidence_refs": [{"url": "https://t/1", "title": "t", "snippet": "s"}],
    }

def _user_sentiment(pain_freqs, tags, neutral=0.3):
    pain_points = [
        {"description": f"痛点{i}", "frequency": f, "severity": "medium"}
        for i, f in enumerate(pain_freqs)
    ]
    return {
        "product_category": "潮玩",
        "sentiment": {"positive": 0.5, "neutral": neutral, "negative": 0.2},
        "pain_points": pain_points, "motivation_tags": tags, "summary": "s",
        "evidence_refs": [{"url": "https://u/1", "title": "u", "snippet": "s"}],
    }

def _ip_assessment(ranking):
    return {
        "category": "潮玩", "market": "CN", "ip_ranking": ranking,
        "licensing_risk": "待核验", "strategy_note": "",
        "evidence_refs": [{"url": "https://i/1", "title": "i", "snippet": "s"}],
    }

def _ip_candidate(ip_name, heat_score, rejected=False):
    return {
        "ip_name": ip_name, "heat_score": heat_score,
        "lifecycle_stage": "unknown", "window_estimate": "待核验",
        "regional_fit": 0.0, "rejected": rejected,
        "reject_reason": "区域适配数据缺失" if rejected else None,
    }

class _FakeView:
    """可控的 BusinessSummaryView 假实现"""

    def __init__(self, brand_conc=None, hit_products=None, exc=None):
        self._brand_conc = brand_conc if brand_conc is not None else {}
        self._hit_products = hit_products if hit_products is not None else []
        self._exc = exc

    def get_brand_concentration(self, category, as_of=None, snapshot_id=None):
        if self._exc:
            raise self._exc
        return self._brand_conc

    def get_hit_products(self, category, as_of=None, snapshot_id=None):
        if self._exc:
            raise self._exc
        return self._hit_products

def _agent(view=None):
    views = {"BusinessSummaryView": view} if view is not None else {}
    return BusinessEvaluationAgent(views=views)

def _run(agent, context):
    return asyncio.run(agent.run(context))

def _full_context(**overrides):
    ctx = {
        "brief": _brief(),
        "weights": _WEIGHTS,
        "proposal_set": {"proposals": [_proposal("三丽鸥联名摆件", "三丽鸥 IP 联名")], "ideation_note": ""},
        "feature_matrix": _feature_matrix([90.0, 80.0]),
        "user_sentiment": _user_sentiment([0.5, 0.3], ["治愈系", "社交属性"]),
        "ip_assessment": _ip_assessment([_ip_candidate("三丽鸥", 85.0)]),
        "upstream_confidences": ["medium", "medium", "medium"],
        "feedback": "",
    }
    ctx.update(overrides)
    return ctx

# ── 纯函数测试 ──────────────────────────

def test_clamp():
    assert clamp(150.0) == 100.0
    assert clamp(-10.0) == 0.0
    assert clamp(50.0) == 50.0

def test_score_trend_heat_peak():
    s, w = score_trend_heat([{"heat_index": 90.0}, {"heat_index": 75.0}])
    assert s == pytest.approx(90.0)
    assert w == []

def test_score_trend_heat_empty():
    s, w = score_trend_heat([])
    assert s == 0.0
    assert w  # 有 warning

def test_score_user_demand():
    s, w = score_user_demand(
        [{"frequency": 0.5}, {"frequency": 0.3}], ["治愈系", "社交属性"], {"neutral": 0.3}
    )
    # avg_freq=0.4 → 0.4*70=28 + 2*10=20 = 48
    assert s == pytest.approx(48.0)
    assert w == []

def test_score_user_demand_neutral_placeholder():
    s, w = score_user_demand([{"frequency": 0.5}], ["治愈系"], {"neutral": 1.0})
    assert s == pytest.approx(45.0)  # 0.5*70 + 1*10
    assert any("中性占位" in x for x in w)

def test_score_ip_fit_matched():
    proposal = _proposal("三丽鸥联名", "三丽鸥 IP")
    ranking = [_ip_candidate("三丽鸥", 85.0)]
    s, w = score_ip_fit(proposal, {"ip_ranking": ranking})
    assert s == pytest.approx(85.0)
    assert w == []

def test_score_ip_fit_rejected():
    proposal = _proposal("三丽鸥联名", "三丽鸥 IP")
    ranking = [_ip_candidate("三丽鸥", 85.0, rejected=True)]
    s, w = score_ip_fit(proposal, {"ip_ranking": ranking})
    assert s == 0.0  # rejected 不产生正向分
    assert w

def test_score_ip_fit_no_match():
    proposal = _proposal("某方案", "无 IP 引用")
    ranking = [_ip_candidate("三丽鸥", 85.0)]
    s, w = score_ip_fit(proposal, {"ip_ranking": ranking})
    assert s == 0.0
    assert w

def test_score_competition():
    s, w = score_competition({"几素": 3, "哈尔斯": 2})
    assert s == pytest.approx(80.0)  # 100 - 2*10
    assert w == []

def test_score_competition_empty():
    s, w = score_competition({})
    assert s == 0.0
    assert w

def test_score_history_analog():
    s, w = score_history_analog([{"heat_index": 70.0}, {"heat_index": 60.0}])
    assert s == pytest.approx(65.0)
    assert w == []

def test_score_history_analog_empty():
    s, w = score_history_analog([])
    assert s == 0.0
    assert w

# ── Agent 测试 ──────────────────────────

def test_valid_opportunity_score():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    result = _run(_agent(view), _full_context())
    scores = result["opportunity_scores"]
    assert len(scores) == 1
    # 直接 model_validate 验证合法
    OpportunityScore.model_validate(scores[0])
    assert scores[0]["proposal_name"] == "三丽鸥联名摆件"

def test_dimensions_in_range():
    view = _FakeView(brand_conc={"a": 1, "b": 1, "c": 1}, hit_products=[{"heat_index": 100.0}])
    result = _run(_agent(view), _full_context())
    dims = result["opportunity_scores"][0]["dimension_scores"]
    assert len(dims) == 5
    for d in dims:
        assert 0.0 <= d["score"] <= 100.0

def test_total_matches_weights():
    # trend=90, demand=48, ip=85, competition=80, history=65
    view = _FakeView(brand_conc={"几素": 3, "哈尔斯": 2}, hit_products=[{"heat_index": 70.0}, {"heat_index": 60.0}])
    result = _run(_agent(view), _full_context())
    score = result["opportunity_scores"][0]
    total = score["total_score"]
    expected = 90 * 0.35 + 48 * 0.25 + 85 * 0.20 + 80 * 0.10 + 65 * 0.10
    assert total == pytest.approx(expected, abs=0.5)

def test_proposal_name_from_proposal_set():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    proposals = [_proposal("方案A"), _proposal("方案B")]
    ctx = _full_context(proposal_set={"proposals": proposals, "ideation_note": ""})
    result = _run(_agent(view), ctx)
    names = [s["proposal_name"] for s in result["opportunity_scores"]]
    assert names == ["方案A", "方案B"]  # 不凭空新增，数量与顺序一致

def test_rejected_ip_no_positive_fit():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    ctx = _full_context(ip_assessment=_ip_assessment([_ip_candidate("三丽鸥", 85.0, rejected=True)]))
    result = _run(_agent(view), ctx)
    dims = result["opportunity_scores"][0]["dimension_scores"]
    ip_fit = next(d for d in dims if d["dimension"] == "ip_fit")
    assert ip_fit["score"] == 0.0

def test_view_unavailable_no_fabrication():
    view = _FakeView(exc=BaseUnavailable("无配置"))
    result = _run(_agent(view), _full_context())
    dims = result["opportunity_scores"][0]["dimension_scores"]
    comp = next(d for d in dims if d["dimension"] == "competition")
    hist = next(d for d in dims if d["dimension"] == "history_analog")
    assert comp["score"] == 0.0
    assert hist["score"] == 0.0
    # 有 risk_warning 标注数据缺口
    risks = result["opportunity_scores"][0]["risk_warnings"]
    assert any("competition" in r["source_dimension"] for r in risks)

def test_no_trend_conservative_zero():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    ctx = _full_context(feature_matrix=_feature_matrix([]))
    result = _run(_agent(view), ctx)
    dims = result["opportunity_scores"][0]["dimension_scores"]
    trend = next(d for d in dims if d["dimension"] == "trend_heat")
    assert trend["score"] == 0.0
    risks = result["opportunity_scores"][0]["risk_warnings"]
    assert any("trend_heat" in r["source_dimension"] for r in risks)

def test_no_history_conservative_zero():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[])
    result = _run(_agent(view), _full_context())
    dims = result["opportunity_scores"][0]["dimension_scores"]
    hist = next(d for d in dims if d["dimension"] == "history_analog")
    assert hist["score"] == 0.0
    risks = result["opportunity_scores"][0]["risk_warnings"]
    assert any("history_analog" in r["source_dimension"] for r in risks)

def test_risk_warnings_empty_legal():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    result = _run(_agent(view), _full_context())
    assert result["opportunity_scores"][0]["risk_warnings"] == []

def test_no_adapter_access():
    agent = _agent(_FakeView())
    assert not hasattr(agent, "adapter")
    assert not hasattr(agent, "_adapter")
    assert not hasattr(agent, "base_adapter")

def test_no_other_view_access():
    agent = _agent(_FakeView())
    assert "BusinessSummaryView" in agent.views
    assert "ConsumerDataView" not in agent.views
    assert "IPDataView" not in agent.views
    assert "TrendDataView" not in agent.views

def test_view_injection():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    agent = _agent(view)
    assert agent.views["BusinessSummaryView"] is view

# ── provider 切换 ──────────────────────────

def test_mock_real_switch(monkeypatch):
    assert get_business_agent_class() is MockBusinessAgent
    monkeypatch.setenv("BUSINESS_AGENT_PROVIDER", "real")
    assert get_business_agent_class() is BusinessAgent  # LLM 评审版
    monkeypatch.setenv("BUSINESS_AGENT_PROVIDER", "deterministic")
    assert get_business_agent_class() is BusinessEvaluationAgent  # 确定性评分版
    monkeypatch.setenv("BUSINESS_AGENT_PROVIDER", "mock")
    assert get_business_agent_class() is MockBusinessAgent

def test_real_mode_no_fallback(monkeypatch):
    monkeypatch.setenv("BUSINESS_AGENT_PROVIDER", "deterministic")
    assert get_business_agent_class() is BusinessEvaluationAgent
    view = _FakeView(exc=BaseUnavailable("无配置"))
    result = _run(_agent(view), _full_context())
    dims = result["opportunity_scores"][0]["dimension_scores"]
    comp = next(d for d in dims if d["dimension"] == "competition")
    # 真实实现返回保守 0，而非 Mock 的固定 60
    assert comp["score"] == 0.0

def test_view_failed_degrades_confidence():
    """BusinessSummaryView 数据源故障 → confidence 从 high 降级为 low，不维持高可信"""
    view = _FakeView(exc=BaseUnavailable("无配置"))
    ctx = _full_context(upstream_confidences=["high", "high", "high"])
    result = _run(_agent(view), ctx)
    score = result["opportunity_scores"][0]
    assert score["confidence"] == "low"
    assert score["upstream_confidence"] == "high"  # 上游保留
    assert any("数据源不可用" in c for c in score["caveats"])

def test_aggregate_only_has_caveat_and_degrade():
    """商业维度仅有聚合数据、缺逐条来源 → caveat + confidence 降级"""
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    ctx = _full_context(upstream_confidences=["high", "high", "high"])
    result = _run(_agent(view), ctx)
    score = result["opportunity_scores"][0]
    assert score["confidence"] == "low"
    assert any("仅有聚合数据" in c for c in score["caveats"])

def test_both_aggregate_views_empty_degrades_confidence():
    """品牌与历史爆款聚合均为空 → confidence 降级，分别标注两个维度的数据缺失"""
    view = _FakeView()  # brand_conc={}, hit_products=[]
    ctx = _full_context(upstream_confidences=["high", "high", "high"])
    result = _run(_agent(view), ctx)
    score = result["opportunity_scores"][0]
    assert score["confidence"] == "low"
    assert score["upstream_confidence"] == "high"
    caveats = score["caveats"]
    assert any("品牌集中度数据缺失" in c for c in caveats)
    assert any("历史爆款数据缺失" in c for c in caveats)

# ── graph 集成 ──────────────────────────

def test_graph_business_node_runs(monkeypatch):
    from app.engine import connector_gateway
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent

    monkeypatch.setattr(connector_gateway, "_base_adapter", None)
    monkeypatch.setenv("BASE_PROVIDER_MODE", "mock")
    monkeypatch.setitem(AGENT_REGISTRY, "business", BusinessEvaluationAgent)

    agent = _instantiate_agent("business")
    assert isinstance(agent, BusinessEvaluationAgent)
    ctx = _full_context(brief=_brief(category="小风扇"))
    result = _run(agent, ctx)
    scores = result["opportunity_scores"]
    assert len(scores) == 1
    OpportunityScore.model_validate(scores[0])
    # fixture 中"小风扇"品类 1 个品牌 → competition=90
    dims = scores[0]["dimension_scores"]
    comp = next(d for d in dims if d["dimension"] == "competition")
    assert comp["score"] == pytest.approx(90.0)

def test_graph_business_agent_gets_view(monkeypatch):
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent

    monkeypatch.setitem(AGENT_REGISTRY, "business", BusinessEvaluationAgent)
    agent = _instantiate_agent("business")
    assert hasattr(agent, "views")
    assert "BusinessSummaryView" in agent.views
    assert "ConsumerDataView" not in agent.views
    assert "IPDataView" not in agent.views

def test_business_output_consumed_by_gtm():
    view = _FakeView(brand_conc={"几素": 3}, hit_products=[{"heat_index": 70.0}])
    result = _run(_agent(view), _full_context())
    scores = result["opportunity_scores"]
    # gtm 契约要求 opportunity_scores 非空 list + ip_assessment dict
    validate_gtm_context({
        "opportunity_scores": scores,
        "ip_assessment": _ip_assessment([_ip_candidate("三丽鸥", 85.0)]),
    })

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
    assert "business" in roles
    assert roles[-1] == "learning"
