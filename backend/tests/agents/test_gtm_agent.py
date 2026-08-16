"""GTM Agent（GoToMarketAgent）测试 — 真实实现 + provider 切换 + 权限边界 + 确定性规则

覆盖：方案覆盖/顺序、市场与价格原样、缺数据保守转 deferred、
数据源故障不回退 Mock、置信度降级、证据不伪造、schema 校验。
测试使用 fake GTMMarketView 与固定 Artifact，不使用真实飞书凭证。
"""

from __future__ import annotations

import asyncio

from app.agents.gtm_agent import GTMAgent, GoToMarketAgent, get_gtm_agent_class
from app.agents.mock_agents import MockGTMAgent
from app.data.base_adapter import (
    BaseDataAdapter,
    BaseProviderError,
    BaseUnavailable,
    MockBaseProvider,
    RestrictedQueryPort,
)
from app.data.scoped_views import GTMMarketView
from app.schemas import GTMPlan

# ── 测试辅助 ──────────────────────────

def _brief(category="潮玩", market="CN"):
    return {"category": category, "market": market, "budget_range": "mid"}

def _proposal(name, price_band="¥39-59"):
    return {
        "name": name, "concept": "概念", "product_form": "桌面摆件",
        "target_segment": "年轻女性", "price_band": price_band,
        "source_map": [], "differentiation": "差异化",
    }

def _proposal_set(*proposals):
    return {"proposals": list(proposals), "ideation_note": ""}

def _score(proposal_name, confidence="medium", evidence=True):
    return {
        "proposal_name": proposal_name,
        "total_score": 75.0,
        "confidence": confidence,
        "evidence_refs": [{"url": "https://score/1", "title": "s", "snippet": "s"}] if evidence else [],
    }

def _ip_assessment(licensing_risk="待核验", confidence="low", ranking=None, evidence=True):
    return {
        "category": "潮玩", "market": "CN",
        "ip_ranking": ranking or [],
        "licensing_risk": licensing_risk,
        "strategy_note": "",
        "confidence": confidence,
        "evidence_refs": [{"url": "https://ip/1", "title": "i", "snippet": "s"}] if evidence else [],
    }

def _market_signal(keyword="潮玩", heat_index=80.0):
    return {"keyword": keyword, "platform": "小红书", "heat_index": heat_index,
            "record_date": "2026-08-01", "brand": None}

def _market_evidence():
    return [{"url": "https://market/1", "title": "m", "snippet": "s"}]

class _FakeView:
    """可控的 GTMMarketView 假实现"""

    def __init__(self, signals=None, evidence=None, exc=None):
        self._signals = signals if signals is not None else []
        self._evidence = evidence if evidence is not None else []
        self._exc = exc

    def get_market_signals(self, category, as_of=None, snapshot_id=None):
        if self._exc:
            raise self._exc
        return {"signals": self._signals, "evidence": self._evidence}

def _agent(view=None):
    views = {"GTMMarketView": view} if view is not None else {}
    return GoToMarketAgent(views=views)

def _run(agent, context):
    return asyncio.run(agent.run(context))

def _full_context(**overrides):
    ctx = {
        "brief": _brief(),
        "proposal_set": _proposal_set(_proposal("方案A")),
        "opportunity_scores": [_score("方案A")],
        "ip_assessment": _ip_assessment(),
        "feedback": "",
    }
    ctx.update(overrides)
    return ctx

# ── 1. provider 切换 ──────────────────────────

def test_mock_real_switch(monkeypatch):
    assert get_gtm_agent_class() is MockGTMAgent
    monkeypatch.setenv("GTM_AGENT_PROVIDER", "real")
    assert get_gtm_agent_class() is GTMAgent  # LLM 策略版
    monkeypatch.setenv("GTM_AGENT_PROVIDER", "deterministic")
    assert get_gtm_agent_class() is GoToMarketAgent  # 确定性保守版
    monkeypatch.setenv("GTM_AGENT_PROVIDER", "mock")
    assert get_gtm_agent_class() is MockGTMAgent

# ── 2. graph 工厂注入 GTMMarketView ──────────────────────────

def test_graph_gtm_agent_gets_view(monkeypatch):
    from app.engine.graph import AGENT_REGISTRY, _instantiate_agent
    monkeypatch.setitem(AGENT_REGISTRY, "gtm", GoToMarketAgent)
    agent = _instantiate_agent("gtm")
    assert hasattr(agent, "views")
    assert "GTMMarketView" in agent.views
    assert "ConsumerDataView" not in agent.views
    assert "IPDataView" not in agent.views
    assert not hasattr(agent, "adapter")

# ── 3. 不持有 adapter 或其他 View ──────────────────────────

def test_no_adapter_or_other_view():
    agent = _agent(_FakeView())
    assert not hasattr(agent, "adapter")
    assert not hasattr(agent, "_adapter")
    assert "GTMMarketView" in agent.views
    assert "ConsumerDataView" not in agent.views
    assert "IPDataView" not in agent.views
    assert "BusinessSummaryView" not in agent.views
    assert "TrendDataView" not in agent.views

# ── 4. 每个 proposal 生成一个 GTMPlan ──────────────────────────

def test_each_proposal_gets_plan():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    ctx = _full_context(
        proposal_set=_proposal_set(_proposal("A"), _proposal("B")),
        opportunity_scores=[_score("A"), _score("B")],
    )
    plans = _run(_agent(view), ctx)["gtm_plans"]
    assert len(plans) == 2

# ── 5. proposal_name 与顺序一致 ──────────────────────────

def test_proposal_name_and_order():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    ctx = _full_context(
        proposal_set=_proposal_set(_proposal("A"), _proposal("B"), _proposal("C")),
        opportunity_scores=[_score("A"), _score("B"), _score("C")],
    )
    names = [p["proposal_name"] for p in _run(_agent(view), ctx)["gtm_plans"]]
    assert names == ["A", "B", "C"]

# ── 6/7. country / price_band 原样 ──────────────────────────

def test_country_from_brief_market():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    ctx = _full_context(brief=_brief(market="TH"))
    cp = _run(_agent(view), ctx)["gtm_plans"][0]["country_plans"][0]
    assert cp["country"] == "TH"

def test_price_band_from_proposal():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    ctx = _full_context(proposal_set=_proposal_set(_proposal("方案A", price_band="¥39-59")))
    cp = _run(_agent(view), ctx)["gtm_plans"][0]["country_plans"][0]
    assert cp["price_band"] == "¥39-59"

def test_timing_is_pending():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    cp = _run(_agent(view), _full_context())["gtm_plans"][0]["country_plans"][0]
    assert cp["timing"] == "待核验"  # 不写无来源时间

# ── 8. 无市场数据不生成虚假计划 ──────────────────────────

def test_no_market_data_no_fake_plan():
    view = _FakeView(signals=[], evidence=[])
    plan = _run(_agent(view), _full_context())["gtm_plans"][0]
    assert plan["country_plans"] == []
    assert "CN" in plan["deferred_markets"]
    assert plan["confidence"] == "unknown"

# ── 9/10. 数据源故障保守不回退 Mock ──────────────────────────

def test_base_unavailable_conservative(monkeypatch):
    monkeypatch.setenv("GTM_AGENT_PROVIDER", "deterministic")
    assert get_gtm_agent_class() is GoToMarketAgent
    view = _FakeView(exc=BaseUnavailable("无配置"))
    plan = _run(_agent(view), _full_context())["gtm_plans"][0]
    assert plan["country_plans"] == []
    assert plan["confidence"] == "unknown"

def test_base_provider_error_conservative(monkeypatch):
    monkeypatch.setenv("GTM_AGENT_PROVIDER", "deterministic")
    view = _FakeView(exc=BaseProviderError("网络超时"))
    plan = _run(_agent(view), _full_context())["gtm_plans"][0]
    assert plan["country_plans"] == []
    assert plan["confidence"] == "unknown"

# ── 11. 无 brief.market 进入 deferred/caveat ──────────────────────────

def test_no_market_defers():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    plan = _run(_agent(view), _full_context(brief=_brief(market="")))["gtm_plans"][0]
    assert plan["country_plans"] == []
    assert plan["confidence"] == "unknown"
    assert any("缺少目标市场" in c for c in plan["caveats"])

# ── 12. opportunity_score 缺失不伪造 ──────────────────────────

def test_missing_score_no_fabrication():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    ctx = _full_context(opportunity_scores=[_score("其他方案")])  # 不含"方案A"
    plan = _run(_agent(view), ctx)["gtm_plans"][0]
    assert plan["country_plans"] == []  # 转 deferred
    assert "缺少 opportunity_score" in plan["dependencies"]

# ── 13. rejected IP 不描述为确定可上市 ──────────────────────────

def test_rejected_ip_not_claimed_launchable():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    ip = _ip_assessment(ranking=[{"ip_name": "三丽鸥", "rejected": True, "heat_score": 85.0}])
    plan = _run(_agent(view), _full_context(ip_assessment=ip))["gtm_plans"][0]
    for cp in plan["country_plans"]:
        assert "可上市" not in cp["rationale"]

# ── 14. IP 授权待核验产生 caveat/dependency ──────────────────────────

def test_licensing_pending_caveat():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    plan = _run(_agent(view), _full_context(ip_assessment=_ip_assessment(licensing_risk="待核验")))["gtm_plans"][0]
    assert any("IP 授权状态待核验" in c for c in plan["caveats"])
    assert "IP 授权状态" in plan["dependencies"]

# ── 15. 仅有聚合数据 confidence 降级 ──────────────────────────

def test_aggregate_only_confidence_low():
    view = _FakeView(signals=[_market_signal()], evidence=[])  # 有信号但无逐条来源
    ctx = _full_context(
        opportunity_scores=[_score("方案A", confidence="high")],
        ip_assessment=_ip_assessment(confidence="high"),
    )
    plan = _run(_agent(view), ctx)["gtm_plans"][0]
    assert plan["confidence"] == "low"  # 不因上游 high 提升

# ── 16. 无 EvidenceRef 不伪造 URL ──────────────────────────

def test_no_evidence_no_fabrication():
    view = _FakeView(signals=[_market_signal()], evidence=[])
    ctx = _full_context(
        opportunity_scores=[_score("方案A", evidence=False)],
        ip_assessment=_ip_assessment(evidence=False),
    )
    plan = _run(_agent(view), ctx)["gtm_plans"][0]
    assert plan["evidence_refs"] == []  # 不伪造 URL

def test_with_market_evidence_no_missing_source_caveat():
    """有市场 evidence 时：evidence_refs 保留，且不误报“缺少逐条来源”"""
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    plan = _run(_agent(view), _full_context())["gtm_plans"][0]
    urls = [e["url"] for e in plan["evidence_refs"]]
    assert "https://market/1" in urls  # evidence_refs 保留市场证据
    assert not any("缺少逐条来源" in c for c in plan["caveats"])  # 不误报
    assert any("缺少区域/节日/法规数据" in c for c in plan["caveats"])

# ── 17. schema 校验 ──────────────────────────

def test_schema_validation():
    view = _FakeView(signals=[_market_signal()], evidence=_market_evidence())
    plans = _run(_agent(view), _full_context())["gtm_plans"]
    for p in plans:
        GTMPlan.model_validate(p)

# ── 18. full_review 无回归 ──────────────────────────

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

# ── get_market_signals（View 层） ──────────────────────────

def _market_record(record_id, keyword, category, source_url, heat_index=80.0):
    return {
        "record_id": record_id, "keyword": keyword, "platform": "xiaohongshu",
        "category": category, "summary": "s", "heat_index": heat_index,
        "interaction": 100.0, "brand": None, "price_range": None,
        "record_date": "2026-08-01", "source_url": source_url,
        "snapshot_id": "snap-x", "ingested_at": "2026-08-10T10:00:00+00:00",
    }

def _market_view(records):
    return GTMMarketView(
        RestrictedQueryPort(BaseDataAdapter(provider=MockBaseProvider(records=records)))
    )

def test_get_market_signals_structure():
    view = _market_view([_market_record("r1", "潮玩", "潮玩", "https://example.com/m/1")])
    result = view.get_market_signals("潮玩")
    assert "signals" in result and "evidence" in result
    assert result["signals"][0]["keyword"] == "潮玩"
    assert result["evidence"][0]["url"] == "https://example.com/m/1"

def test_get_market_signals_no_source_url():
    view = _market_view([_market_record("r1", "潮玩", "潮玩", None)])
    result = view.get_market_signals("潮玩")
    assert len(result["signals"]) == 1
    assert result["evidence"] == []  # 无 source_url 不伪造

def test_get_market_signals_no_data():
    view = _market_view([_market_record("r1", "保温杯", "保温杯", "https://example.com/m/1")])
    result = view.get_market_signals("潮玩")  # 无"潮玩"记录
    assert result["signals"] == []
    assert result["evidence"] == []

def test_get_market_signals_snapshot_filter():
    view = _market_view([_market_record("r1", "潮玩", "潮玩", "https://example.com/m/1")])
    result = view.get_market_signals("潮玩", snapshot_id="snap-other")
    assert result["signals"] == []  # 快照不匹配 → 空
