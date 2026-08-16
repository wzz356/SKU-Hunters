"""Context 契约测试 — business/gtm 必需 Artifact 的强制校验

覆盖：
1. business context 含三官 Artifact
2. gtm context 含 opportunity_scores / ip_assessment
3/4. 缺失任意必需 Artifact 明确失败
5. Artifact 为 JSON-safe dict（model_dump 结果，非 Pydantic 模型）
6. risk_warnings=[] 不触发失败
7. context 不暴露 BaseDataAdapter / Scoped View / 原始 connector
8/9. Mock 流程无回归、无 InvalidUpdateError（集成）
10. 契约失败时不发生 Agent 调用
"""

from __future__ import annotations

import asyncio

import pytest
from app.agents.mock_agents import (
    MockBusinessAgent,
    MockCreativeAgent,
    MockGTMAgent,
    MockIPAgent,
    MockTrendAgent,
    MockUserAgent,
)
from app.data.base_adapter import BaseDataAdapter
from app.data.scoped_views import _ReadView
from app.engine import graph
from app.engine.context_contract import (
    ContextContractError,
    validate_business_context,
    validate_gtm_context,
)
from app.schemas import Weights
from pydantic import BaseModel

BRIEF = {"category": "解压玩具", "market": "CN", "budget_range": "mid"}


def _run(coro):
    return asyncio.run(coro)


def _full_state() -> dict:
    """构造含三官 Artifact + proposal_set + opportunity_scores 的完整 state"""
    async def _build():
        fm = await MockTrendAgent().run({"brief": BRIEF})
        us = await MockUserAgent().run({"brief": BRIEF})
        ipa = await MockIPAgent().run({"brief": BRIEF})
        ps = await MockCreativeAgent().run({"brief": BRIEF})
        return {
            "brief": BRIEF,
            "weights": Weights().model_dump(),
            "feature_matrix": fm,
            "user_sentiment": us,
            "ip_assessment": ipa,
            "proposal_set": ps,
            "challenges": [],
            "opportunity_scores": [{"proposal_name": "P1", "total_score": 80.0}],
        }
    return _run(_build())


class _CapturingAgent:
    """捕获 run(context) 的假 agent，可委托给真实 mock agent 生成合法产物"""

    def __init__(self, delegate=None):
        self.delegate = delegate
        self.context = None
        self.run_called = False

    async def run(self, context):
        self.context = context
        self.run_called = True
        if self.delegate is not None:
            return await self.delegate.run(context)
        return {"opportunity_scores": []}


def _capture(monkeypatch, delegate):
    agent = _CapturingAgent(delegate)
    monkeypatch.setattr(graph, "_instantiate_agent", lambda key: agent)
    return agent


# ── 单元：validate 函数 ──────────────────────────

def test_validate_business_context_ok():
    ctx = {"feature_matrix": {"s": 1}, "user_sentiment": {"s": 1}, "ip_assessment": {"s": 1}}
    validate_business_context(ctx)  # 不抛异常


def test_validate_gtm_context_ok():
    ctx = {"opportunity_scores": [{"p": 1}], "ip_assessment": {"s": 1}}
    validate_gtm_context(ctx)  # 不抛异常


@pytest.mark.parametrize("missing", ["feature_matrix", "user_sentiment", "ip_assessment"])
def test_business_missing_artifact_fails(missing):
    ctx = {"feature_matrix": {"s": 1}, "user_sentiment": {"s": 1}, "ip_assessment": {"s": 1}}
    del ctx[missing]
    with pytest.raises(ContextContractError):
        validate_business_context(ctx)


@pytest.mark.parametrize("missing", ["opportunity_scores", "ip_assessment"])
def test_gtm_missing_artifact_fails(missing):
    ctx = {"opportunity_scores": [{"p": 1}], "ip_assessment": {"s": 1}}
    del ctx[missing]
    with pytest.raises(ContextContractError):
        validate_gtm_context(ctx)


def test_business_none_artifact_fails():
    ctx = {"feature_matrix": None, "user_sentiment": {"s": 1}, "ip_assessment": {"s": 1}}
    with pytest.raises(ContextContractError):
        validate_business_context(ctx)


def test_business_wrong_type_artifact_fails():
    ctx = {"feature_matrix": "not-a-dict", "user_sentiment": {"s": 1}, "ip_assessment": {"s": 1}}
    with pytest.raises(ContextContractError):
        validate_business_context(ctx)


def test_business_empty_dict_artifact_fails():
    """空 dict 不能掩盖缺失"""
    ctx = {"feature_matrix": {}, "user_sentiment": {"s": 1}, "ip_assessment": {"s": 1}}
    with pytest.raises(ContextContractError):
        validate_business_context(ctx)


def test_gtm_empty_list_scores_fails():
    """空 list 不能掩盖缺失"""
    ctx = {"opportunity_scores": [], "ip_assessment": {"s": 1}}
    with pytest.raises(ContextContractError):
        validate_gtm_context(ctx)


def test_risk_warnings_empty_is_legal():
    """risk_warnings=[] 是 OpportunityScore 内部合法值，不触发契约失败"""
    # opportunity_scores 元素含 risk_warnings=[]，契约只校验 opportunity_scores 是非空 list
    ctx = {
        "opportunity_scores": [{"proposal_name": "P1", "risk_warnings": []}],
        "ip_assessment": {"s": 1},
    }
    validate_gtm_context(ctx)  # 不抛异常


# ── 节点：business/gtm 捕获 context ──────────────

def test_business_node_context_has_three_artifacts(monkeypatch):
    agent = _capture(monkeypatch, MockBusinessAgent())
    _run(graph.business_node(_full_state()))
    ctx = agent.context
    assert "feature_matrix" in ctx
    assert "user_sentiment" in ctx
    assert "ip_assessment" in ctx


def test_gtm_node_context_has_upstream(monkeypatch):
    agent = _capture(monkeypatch, MockGTMAgent())
    _run(graph.gtm_node(_full_state()))
    ctx = agent.context
    assert "opportunity_scores" in ctx
    assert "ip_assessment" in ctx
    assert "feedback" in ctx  # 所有 Agent 都应收 feedback（可为空串）


def test_artifact_is_json_safe_dict(monkeypatch):
    """Artifact 是 JSON-safe dict（model_dump 结果），非 Pydantic 模型"""
    agent = _capture(monkeypatch, MockBusinessAgent())
    _run(graph.business_node(_full_state()))
    ctx = agent.context
    for key in ("feature_matrix", "user_sentiment", "ip_assessment"):
        assert isinstance(ctx[key], dict)
        assert not isinstance(ctx[key], BaseModel)


def test_context_no_internal_objects(monkeypatch):
    """context 不暴露 BaseDataAdapter / Scoped View / 原始 connector"""
    agent = _capture(monkeypatch, MockBusinessAgent())
    _run(graph.business_node(_full_state()))
    ctx = agent.context

    def _walk(value):
        assert not isinstance(value, BaseDataAdapter)
        assert not isinstance(value, _ReadView)
        if isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)

    _walk(ctx)
    # 也不应有 adapter/view/connector 命名的键
    assert "adapter" not in ctx
    assert "views" not in ctx
    assert "connector" not in ctx


def test_contract_failure_blocks_agent_call(monkeypatch):
    """契约失败时，Agent.run 不被调用，不静默推进"""
    agent = _capture(monkeypatch, None)  # delegate=None，若被调用会返回空 scores
    state = _full_state()
    del state["feature_matrix"]  # 制造缺失
    with pytest.raises(ContextContractError):
        _run(graph.business_node(state))
    assert agent.run_called is False  # Agent 未被调用


# ── 集成：Mock 流程无回归 ──────────────────────

async def test_full_review_no_regression():
    """完整 review 流程：Mock 流程无回归，无 InvalidUpdateError"""
    from app.engine.graph import run_review

    async def ask(gate):
        if gate["gate"] == "retro":
            return {"action": "done"}
        return {"action": "confirm"}

    events = [e async for e in run_review(BRIEF, ask_human=ask)]
    roles = [e["role"] for e in events]
    assert "business" in roles
    assert "global" in roles  # gtm 事件 role 为 global
    assert roles.index("business") < roles.index("global")  # business 先于 gtm（串行）
    assert roles[-1] == "learning"
