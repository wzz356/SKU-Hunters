"""ACT2_CHALLENGE 验收测试 — 圆桌质询环节

创意官产出 ProposalSet 后，trend/user/ip 三位洞察官对方案发起结构化质询
（背书/修正/反对）。验收要点：
- 质询进入事件流（role=challenge），顺序在 creative 之后、business 之前
- 质询事件保留来源角色与证据（evidence_refs）
- 质询进入最终报告（dissent_records 含 act2 质询记录）
- 质询保留 source_role 与 evidence_refs（ChallengeRecord 契约）
- business/gtm 收到 challenges（下游可见质询）
"""

from app.agents.challenge_agents import (
    CHALLENGE_REGISTRY,
)
from app.engine.graph import run_review
from app.schemas import ChallengeStance

BRIEF = {"category": "解压玩具", "market": "CN", "budget_range": "mid"}


async def _collect(brief=None, ask_human=None):
    return [e async for e in run_review(brief or BRIEF, ask_human=ask_human)]


def _roles(events):
    return [e["role"] for e in events]


async def test_challenge_events_in_flow():
    """三官质询进入事件流，顺序：creative < challenge < business"""
    events = await _collect()
    roles = _roles(events)

    assert roles.count("challenge") == 3
    assert roles.index("creative") < roles.index("challenge")
    assert roles.index("challenge") < roles.index("business")


async def test_challenge_event_carries_source_role():
    """质询事件 content 保留来源角色（趋势官/用户官/IP官）"""
    events = await _collect()
    challenge = [e for e in events if e["role"] == "challenge"]
    contents = "\n".join(e["content"] for e in challenge)
    for label in ("趋势官", "用户官", "IP官"):
        assert label in contents


async def test_challenge_event_carries_evidence():
    """质询事件携带证据（evidence_refs 转字符串）"""
    events = await _collect()
    challenge = [e for e in events if e["role"] == "challenge"]
    assert all(e["evidence"] for e in challenge), "质询事件必须带证据"
    # 每个挑战事件覆盖三个方案，证据至少 1 条
    assert len(challenge[0]["evidence"]) >= 1


async def test_challenge_entries_reach_report():
    """质询进入最终报告：dissent_records 含 act2 质询（3官 × 3方案 = 9 条）"""
    events = await _collect()
    decision = next(e for e in events if e["role"] == "decision")
    report = decision["report"]
    act2 = [
        d for d in report["dissent_records"]
        if d.get("act") == "act2"
    ]
    assert len(act2) == 9
    # 质询记录保留来源角色
    parties = {tuple(d["parties"]) for d in act2}
    assert parties == {("trend",), ("user",), ("ip",)}
    # 每条质询引用对应方案名
    assert all(d["description"].startswith("[质询·") for d in act2)


def test_challenge_record_contract():
    """ChallengeRecord 保留 source_role 与 evidence_refs，stance 合法"""
    import asyncio

    brief = {"category": "解压玩具", "market": "CN", "budget_range": "mid"}

    # 直接构造 context 调用挑战 Agent，验证契约
    async def _probe():
        from app.agents.mock_agents import (
            MockCreativeAgent,
            MockIPAgent,
            MockTrendAgent,
            MockUserAgent,
        )

        # 生成三份 artifact + proposal_set
        fm = await MockTrendAgent().run({"brief": brief})
        us = await MockUserAgent().run({"brief": brief})
        ip = await MockIPAgent().run({"brief": brief})
        ps = await MockCreativeAgent().run({
            "brief": brief, "feature_matrix": fm,
            "user_sentiment": us, "ip_assessment": ip,
        })
        context = {
            "brief": brief,
            "proposal_set": ps,
            "feature_matrix": fm,
            "user_sentiment": us,
            "ip_assessment": ip,
        }
        results = {}
        for key, cls in CHALLENGE_REGISTRY.items():
            out = await cls().run(context)
            results[key] = out["challenges"]
        return results

    results = asyncio.run(_probe())

    assert set(results) == {"trend", "user", "ip"}
    for role, challenges in results.items():
        assert len(challenges) == 3  # 三个方案
        for c in challenges:
            assert c["source_role"] == role
            assert c["stance"] in {s.value for s in ChallengeStance}
            assert c["evidence_refs"], f"{role} 质询必须保留证据"
            assert c["proposal_name"]


def test_business_receives_challenges():
    """business 节点 context 注入 challenges（下游可见质询）"""
    # 验证 graph 中 business_node 的 context 包含 challenges 键
    import inspect

    import app.engine.graph as g

    src = inspect.getsource(g.business_node)
    assert '"challenges"' in src
    assert "state.get(\"challenges\", [])" in src
    src_gtm = inspect.getsource(g.gtm_node)
    assert '"challenges"' in src_gtm
