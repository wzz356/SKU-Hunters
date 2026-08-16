"""图编排测试 — 锁定 B 工作流交付标准

- 事件流顺序：三洞察官(任意序) → Gate1 → 创意官 → 商业/全球化 → 决策 → Gate2 → 学习官
- 机会值是一笔可追溯的算术（mock 数据 92/78/85/60/70 → 81.7）
- interrupt/resume：修改回退重跑、疑问 qa 小环
- Decision Engine：置信度衰减、定档阈值、C3 分歧记录
"""

import pytest
from app.engine.decision_engine import DecisionEngine
from app.engine.graph import run_review

BRIEF = {"category": "解压玩具", "market": "CN", "budget_range": "mid"}

# mock 商业官对 Top1 提案的期望总分：92*.35+78*.25+85*.20+60*.10+70*.10
EXPECTED_TOP_SCORE = 81.7


async def _collect(brief=None, ask_human=None):
    return [e async for e in run_review(brief or BRIEF, ask_human=ask_human)]


def _roles(events):
    return [e["role"] for e in events]


async def test_full_review_event_sequence():
    """自动确认下，事件顺序符合五幕结构，分数算术正确"""
    events = await _collect()
    roles = _roles(events)

    # 三洞察官先并行发言（内部顺序不限），且都在 Gate1 之前
    assert set(roles[:3]) == {"trend", "user", "ip"}
    assert roles.index("act1_gate") < roles.index("creative")
    assert roles.index("creative") < roles.index("business")
    assert roles.index("decision") < roles.index("human_gate")
    assert roles[-1] == "learning"  # 学习官建档收尾

    # 决策事件：Top1 分数是一笔可追溯的算术
    decision = next(e for e in events if e["role"] == "decision")
    assert decision["score"] == pytest.approx(EXPECTED_TOP_SCORE)

    # 每个委员事件都是四键契约
    for e in events:
        assert {"role", "content", "evidence", "score"} <= set(e)


async def test_insight_events_carry_evidence():
    """无证据不得发言：洞察官事件必须带证据链"""
    events = await _collect()
    for role in ("trend", "user", "ip"):
        event = next(e for e in events if e["role"] == role)
        assert event["evidence"], f"{role} 事件缺少证据"


async def test_act1_gate_modify_reruns_insights():
    """Gate1 修改 → 三洞察官重跑（最便宜的回退点）"""
    calls = []

    async def ask(gate):
        calls.append(gate["gate"])
        if gate["gate"] == "act1_gate" and calls.count("act1_gate") == 1:
            return {"action": "modify", "suggestion": "聚焦办公室场景"}
        return {"action": "confirm"}

    events = await _collect(ask_human=ask)
    roles = _roles(events)

    # 洞察官跑了两轮
    assert roles.count("trend") == 2
    # Gate1 被问了两遍（修改后重新确认）
    assert calls.count("act1_gate") == 2


async def test_gate_question_loops_back_without_rerun():
    """疑问 → qa 作答 → 回到同一个门，不重跑任何委员"""
    answers = iter([
        {"action": "question", "question": "趋势增速的数据源是什么？"},
        {"action": "confirm"},
        {"action": "confirm"},
        {"action": "done"},  # 复盘窗直接结束
    ])

    async def ask(gate):
        return next(answers)

    events = await _collect(ask_human=ask)
    roles = _roles(events)

    assert "qa" in roles                      # qa 节点作答了
    assert roles.count("trend") == 1          # 但没有重跑洞察官
    assert roles.index("qa") < roles.index("creative")  # 问答发生在 Gate1 放行前


async def test_human_gate_modify_reroutes_to_business_only():
    """Gate2 参数微调 → 只回退商业官重算，创意官不动（最小失效）"""
    calls = []

    async def ask(gate):
        calls.append(gate["gate"])
        if gate["gate"] == "human_gate" and calls.count("human_gate") == 1:
            return {"action": "modify", "suggestion": "价格带压到 29-39",
                    "scope": "business"}
        return {"action": "confirm"}

    events = await _collect(ask_human=ask)
    roles = _roles(events)

    assert roles.count("business") == 2   # 商业官重算
    assert roles.count("creative") == 1   # 创意官不重跑


# ── 复盘窗 + reject ─────────────────────────────

async def test_retro_chat_loop_then_archive():
    """首次复盘入口：chat 可多轮；done 后学习官二过，把对话轮数追加入档"""
    asked = []

    async def ask(gate):
        asked.append(gate["gate"])
        if gate["gate"] == "retro":
            n = asked.count("retro")
            if n <= 2:
                return {"action": "chat", "content": f"第 {n} 个问题"}
            return {"action": "done"}
        return {"action": "confirm"}

    events = await _collect(ask_human=ask)
    roles = _roles(events)

    assert roles.count("retro") >= 2      # 复盘作答事件存在
    assert roles[-1] == "learning"
    appended = events[-1]
    assert "复盘对话 2 轮已追加入档" in appended["content"]
    assert appended["snapshot"]["retro_turns"] == 2


async def test_reject_archives_bad_case():
    """reject：否决立项 → 不打回、先归档为 bad case → 再开首次复盘入口"""
    async def ask(gate):
        if gate["gate"] == "human_gate":
            return {"action": "reject", "reason": "IP 窗口期赶不上 Q4 上架"}
        return {"action": "done" if gate["gate"] == "retro" else "confirm"}

    events = await _collect(ask_human=ask)
    roles = _roles(events)

    # 否决后不重跑任何委员，直接归档
    assert roles.count("business") == 1
    # 归档先于复盘（归档不是封存，复盘是归档后的入口）
    assert roles.index("learning") < roles.index("retro")
    # 归档事件标记 bad case，人决策留痕
    learning = next(e for e in events if e["role"] == "learning")
    assert "bad case" in learning["content"]
    assert "reject" in learning["content"]
    assert learning["snapshot"]["status"] == "rejected"


async def test_reweight_takes_effect_on_rerun():
    """reweight（modify + custom_weights）→ 商业官按新权重重算，分数可验证"""
    # 全部押注趋势热度：Top1 = 92×1.0 = 92.0
    new_weights = {"trend_heat": 1.0, "user_demand": 0.0, "ip_fit": 0.0,
                   "competition": 0.0, "history_analog": 0.0}

    asked = []

    async def ask(gate):
        asked.append(gate["gate"])
        if gate["gate"] == "human_gate" and asked.count("human_gate") == 1:
            return {"action": "modify", "suggestion": "只看趋势",
                    "custom_weights": new_weights}
        if gate["gate"] == "retro":
            return {"action": "done"}
        return {"action": "confirm"}

    events = await _collect(ask_human=ask)
    business = [e for e in events if e["role"] == "business"]
    assert len(business) == 2
    assert business[-1]["score"] == pytest.approx(92.0)


async def test_decision_event_carries_full_report():
    """decision 事件附带完整建议书（report 键），四键契约不变"""
    events = await _collect()
    decision = next(e for e in events if e["role"] == "decision")
    assert {"role", "content", "evidence", "score"} <= set(decision)
    report = decision["report"]
    assert report["decision"] == "approve"
    assert report["proposal"]["name"]
    assert "dissent_records" in report


# ── Decision Engine 单元 ──────────────────────

def _proposal_set_dict():
    base = {
        "concept": "c", "product_form": "摆件", "target_segment": "s",
        "price_band": "¥39-59", "differentiation": "d",
        "source_map": [
            {"artifact": a, "claim": "c", "supports": "s"}
            for a in ("FeatureMatrix", "UserSentiment", "IPAssessment")
        ],
    }
    return {"proposals": [
        {**base, "name": "P1"}, {**base, "name": "P2"}, {**base, "name": "P3"},
    ]}


def _score_dict(name, dim_score, confidence="high"):
    dims = [
        {"dimension": d, "score": dim_score, "source_agent": "mock",
         "basis": "b"}
        for d in ("trend_heat", "user_demand", "ip_fit", "competition",
                  "history_analog")
    ]
    return {
        "proposal_name": name, "dimension_scores": dims,
        "weights_used": {}, "total_score": dim_score,  # 等分时总分=分项
        "star_rating": 4, "upstream_confidence": confidence,
    }


def test_decision_thresholds():
    """≥80 approve / 60~80 hold / <60 reject"""
    engine = DecisionEngine()
    proposals = _proposal_set_dict()
    cases = [(85.0, "approve"), (65.0, "hold"), (50.0, "reject")]
    for total, expected in cases:
        scores = [_score_dict("P1", total), _score_dict("P2", 30.0)]
        rec = engine.synthesize(proposals, scores)
        assert rec.decision.value == expected, f"总分 {total} 定档错误"


def test_confidence_attenuates_not_amplifies():
    """上游 LOW → 建议书不得高于 LOW（衰减不放大）"""
    engine = DecisionEngine()
    scores = [_score_dict("P1", 85.0, confidence="low")]
    rec = engine.synthesize(_proposal_set_dict(), scores)
    assert rec.confidence.value == "low"
    assert any("降权" in c for c in rec.conditions)


def test_close_call_records_c3_dissent():
    """Top1 与第二名分差 < 10 → 写入 C3 评分分歧，不调和"""
    engine = DecisionEngine()
    scores = [_score_dict("P1", 85.0), _score_dict("P2", 80.0)]
    rec = engine.synthesize(_proposal_set_dict(), scores)
    assert any(
        c.conflict_type.value == "c3_score_divergence"
        for c in rec.dissent_records
    )
    assert rec.runner_ups  # 落选方案留痕
