"""创意官输出契约测试 — 四项确定性校验 + 重试/降级策略

覆盖 source_map 覆盖、方案互异、价格带预算、product_form 依据，以及
真实 CreativeAgent 的重试上限与无 Key 降级、Mock 流程不回归。
"""

from __future__ import annotations

import asyncio

import pytest
from app.agents.creative_agent import CreativeAgent, get_creative_agent_class
from app.agents.creative_contract import (
    ContractError,
    parse_price_band,
    validate_price_bands,
    validate_product_form_basis,
    validate_proposal_distinctness,
    validate_proposals,
    validate_source_map_coverage,
)
from app.agents.mock_agents import (
    MockCreativeAgent,
    MockIPAgent,
    MockTrendAgent,
    MockUserAgent,
)

# ── 测试数据 ──────────────────────────

def _fm() -> dict:
    return {"summary": "桌面场景讨论量走高", "evidence_refs": []}

def _us() -> dict:
    return {
        "summary": "工位收纳困难，收藏+解压是购买动机",
        "pain_points": [{"description": "盲盒没地方放，工位收纳困难"}],
        "motivation_tags": ["收藏", "工位装饰", "解压"],
    }

def _ip() -> dict:
    return {"summary": "成熟形态快反", "ip_ranking": [{"ip_name": "Chiikawa"}]}

def _full_source_map() -> list[dict]:
    return [
        {"artifact": "FeatureMatrix", "claim": "c", "supports": "形态"},
        {"artifact": "UserSentiment", "claim": "c", "supports": "人群"},
        {"artifact": "IPAssessment", "claim": "c", "supports": "IP"},
    ]

def _proposal(name, product_form, target_segment, price_band, source_map=None) -> dict:
    return {
        "name": name,
        "concept": "c",
        "product_form": product_form,
        "target_segment": target_segment,
        "price_band": price_band,
        "source_map": source_map or _full_source_map(),
        "differentiation": "d",
    }

def _brief(budget="mid") -> dict:
    return {"category": "解压玩具", "market": "CN", "budget_range": budget}


# ── source_map 覆盖 ──────────────────────────

def test_source_map_full_coverage():
    proposals = [_proposal("P1", "收纳", "学生", "¥39-59")]
    validate_proposals(proposals, _brief(), _fm(), _us(), _ip())  # 不抛


def test_source_map_missing_artifact():
    proposals = [_proposal("P1", "收纳", "学生", "¥39-59", source_map=[
        {"artifact": "FeatureMatrix", "claim": "c", "supports": "形态"},
        {"artifact": "UserSentiment", "claim": "c", "supports": "人群"},
        # 缺 IPAssessment
    ])]
    with pytest.raises(ContractError):
        validate_source_map_coverage(proposals, _fm(), _us(), _ip())


def test_source_map_unknown_artifact():
    proposals = [_proposal("P1", "收纳", "学生", "¥39-59", source_map=[
        {"artifact": "FeatureMatrix", "claim": "c", "supports": "形态"},
        {"artifact": "UserSentiment", "claim": "c", "supports": "人群"},
        {"artifact": "NonexistentArtifact", "claim": "c", "supports": "IP"},
    ])]
    with pytest.raises(ContractError):
        validate_source_map_coverage(proposals, _fm(), _us(), _ip())


def test_source_map_empty_artifact_fails():
    """三官 Artifact 为空 → 失败（空 Artifact 不得生成方案）"""
    proposals = [_proposal("P1", "收纳", "学生", "¥39-59")]
    with pytest.raises(ContractError):
        validate_source_map_coverage(proposals, None, _us(), _ip())


# ── 方案互异 ──────────────────────────

def test_insufficient_distinctness():
    """仅一维差异（product_form 不同）→ 失败"""
    proposals = [
        _proposal("P1", "收纳", "学生", "¥39-59"),
        _proposal("P2", "盲盒", "学生", "¥39-59"),  # 仅 product_form 不同
    ]
    with pytest.raises(ContractError):
        validate_proposal_distinctness(proposals)


def test_sufficient_distinctness():
    """两维差异（product_form + target_segment）→ 通过"""
    proposals = [
        _proposal("P1", "收纳", "学生", "¥39-59"),
        _proposal("P2", "盲盒", "白领", "¥39-59"),  # product_form + target_segment 不同
    ]
    validate_proposal_distinctness(proposals)  # 不抛


# ── 价格带预算 ──────────────────────────

def test_price_band_in_budget():
    proposals = [_proposal("P1", "收纳", "学生", "¥39-59")]
    validate_price_bands(proposals, "mid")  # ¥39-59 在 ¥29-69 内


def test_price_band_over_budget():
    proposals = [_proposal("P1", "收纳", "学生", "¥99-129")]
    with pytest.raises(ContractError):
        validate_price_bands(proposals, "mid")


def test_invalid_price_string():
    proposals = [_proposal("P1", "收纳", "学生", "贵")]
    with pytest.raises(ContractError):
        validate_price_bands(proposals, "mid")


def test_parse_price_band():
    assert parse_price_band("¥39-59") == (39.0, 59.0)
    assert parse_price_band("59-39") == (39.0, 59.0)  # 无序也能解析
    assert parse_price_band("贵") is None


# ── product_form 依据 ──────────────────────────

def test_product_form_has_basis():
    proposals = [_proposal("P1", "收纳", "学生", "¥39-59")]
    validate_product_form_basis(proposals, _us())  # "收纳" 在信号里


def test_product_form_no_basis():
    proposals = [_proposal("P1", "香薰夜灯", "学生", "¥39-59")]
    with pytest.raises(ContractError):
        validate_product_form_basis(proposals, _us())  # "香薰夜灯" 无依据


# ── 真实 CreativeAgent：重试 / 降级 ──────────────────────────

async def _real_mock_context() -> dict:
    """用真实 Mock 三官产物构造 context（含 Mock 的 product_form 形态词）"""
    brief = _brief()
    fm = await MockTrendAgent().run({"brief": brief})
    us = await MockUserAgent().run({"brief": brief})
    ip = await MockIPAgent().run({"brief": brief})
    return {"brief": brief, "feature_matrix": fm, "user_sentiment": us, "ip_assessment": ip}


def _context() -> dict:
    return {
        "brief": _brief(),
        "feature_matrix": _fm(),
        "user_sentiment": _us(),
        "ip_assessment": _ip(),
    }


def _llm_json(forms) -> str:
    import json
    proposals = [
        {"name": f"{f}系列", "concept": f, "product_form": f,
         "target_segment": f"人群{i}", "price_band": "¥39-49", "differentiation": "d"}
        for i, f in enumerate(forms)
    ]
    return json.dumps({"proposals": proposals, "ideation_note": "t"})


def test_llm_invalid_output_raises_contract_error(monkeypatch):
    """LLM 返回非法 ProposalSet（product_form 无依据）→ 抛 ContractError，不直接放行"""
    monkeypatch.setattr(
        "app.engine.llm.complete",
        lambda *a, **k: _llm_json(["香薰夜灯", "咖啡机", "扫地机器人"]),
    )
    agent = CreativeAgent()
    with pytest.raises(ContractError):
        asyncio.run(agent.run(_context()))


def test_retry_count_is_bounded(monkeypatch):
    """重试次数有上限：持续非法输出只重试 _MAX_RETRIES 次后抛错"""
    calls = {"n": 0}

    def fake_complete(*a, **k):
        calls["n"] += 1
        return _llm_json(["香薰夜灯", "咖啡机", "扫地机器人"])  # 始终非法

    monkeypatch.setattr("app.engine.llm.complete", fake_complete)
    agent = CreativeAgent()
    with pytest.raises(ContractError):
        asyncio.run(agent.run(_context()))
    assert calls["n"] == 3  # _MAX_RETRIES 次后抛错，不无限重试


def test_no_key_falls_back_to_mock(monkeypatch):
    """无 Key（complete 返回 None）→ 降级 Mock，且 Mock 产物通过契约校验"""
    monkeypatch.setattr("app.engine.llm.complete", lambda *a, **k: None)
    agent = CreativeAgent()
    context = asyncio.run(_real_mock_context())
    result = asyncio.run(agent.run(context))
    assert "proposals" in result  # 降级 Mock 返回合法 ProposalSet（已过契约校验）


def test_mock_agent_is_default(monkeypatch):
    """默认 provider=mock，get_creative_agent_class 返回 MockCreativeAgent
    （清环境变量：本地 .env / 上游测试可能设了 real 开关，默认值判定须与环境无关）"""
    monkeypatch.delenv("CREATIVE_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    assert get_creative_agent_class() is MockCreativeAgent


async def test_full_review_no_regression():
    """完整 review 流程无回归（Mock 默认）"""
    from app.engine.graph import run_review

    async def ask(gate):
        if gate["gate"] == "retro":
            return {"action": "done"}
        return {"action": "confirm"}

    events = [e async for e in run_review(
        {"category": "解压玩具", "market": "CN", "budget_range": "mid"}, ask_human=ask
    )]
    roles = [e["role"] for e in events]
    assert "creative" in roles
    assert roles[-1] == "learning"


def test_creative_node_rejects_invalid_output(monkeypatch):
    """creative_node 边界校验：非法输出（product_form 无依据）抛 ContractError，不能进入 business"""
    from app.engine import graph

    class _BadAgent:
        async def run(self, context):
            return {
                "proposals": [
                    {"name": f"{f}系列", "concept": "c", "product_form": f,
                     "target_segment": f"人群{i}", "price_band": "¥39-49",
                     "source_map": _full_source_map(), "differentiation": "d"}
                    for i, f in enumerate(["香薰夜灯", "咖啡机", "扫地机器人"])
                ],
                "ideation_note": "t",
            }

    monkeypatch.setattr(graph, "_instantiate_agent", lambda key: _BadAgent())
    state = {
        "brief": _brief(),
        "feature_matrix": _fm(),
        "user_sentiment": _us(),  # 不含"香薰夜灯/咖啡机/扫地机器人"
        "ip_assessment": _ip(),
    }
    with pytest.raises(ContractError):
        asyncio.run(graph.creative_node(state))
