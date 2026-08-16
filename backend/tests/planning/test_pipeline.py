"""企划管线测试 — 六步链路（真管线、冻数据）

隔离策略：pipeline 的状态在模块级 _PLANS dict + _STATE_FILE 落盘，
每个测试前快照清空 _PLANS、把落盘路径指到 tmp_path，结束后还原，
避免污染真实 backend/data/plans_state.json。

Stage 5 原子动作契约：
    ① 只有产物生成并持久化成功后才推进 status
    ② 失败时状态与旧产物保持不变（回滚）
    ③ 同状态重复请求稳定返回 StateTransitionError（统一 409 策略）
    ④ 非法前置状态被拒绝（严格线性状态机）
    ⑤ archived 只读：禁止 revise，复盘追问用 review_plan
"""

import json

import pytest
from app.planning import fixtures, pipeline, repository
from app.planning.service import StateTransitionError
from pydantic import ValidationError

VALID_BRIEF = {
    "theme": "2027夏季户外生活系列",
    "category": "小风扇",
    "market": "中国大陆",
    "audience": "18-30岁年轻女性",
    "priceRange": [39, 99],
    "costLimit": 25,
}

@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    """每个测试拿到干净的 _PLANS 和临时落盘文件"""
    snapshot = dict(repository._PLANS)
    repository._PLANS.clear()
    monkeypatch.setattr(repository, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(repository, "_STATE_FILE", tmp_path / "plans_state.json")
    monkeypatch.setattr(repository, "_LEGACY_STATE_FILE", tmp_path / "legacy_plans_state.json")
    yield
    repository._PLANS.clear()
    repository._PLANS.update(snapshot)

def _make_plan(brief: dict | None = None) -> dict:
    return pipeline.create_plan(brief or dict(VALID_BRIEF))

def _advance_to_plan_card(plan: dict, opportunity_id: str | None = None) -> dict:
    """推进完整原子动作链：brief_locked → insights_ready → opportunities_ready → plan_card_ready

    opportunity_id 缺省取机会池展开后的第一张卡（引擎不再产出 fixture 固定 id）。
    """
    pipeline.generate_insights(plan)
    opps = pipeline.generate_opportunities(plan)
    return pipeline.generate_plan_card(plan, opportunity_id or opps[0]["id"])

# ── ① 企划约束 ───────────────────────────────────────────

def test_create_plan_validates_and_locks_brief():
    plan = _make_plan()
    assert plan["plan_id"].startswith("plan_")
    assert plan["status"] == "brief_locked"
    assert plan["brief"]["theme"] == "2027夏季户外生活系列"
    assert plan["selected_opportunity"] is None
    assert plan["plan_card"] is None

def test_create_plan_rejects_missing_theme():
    brief = dict(VALID_BRIEF)
    del brief["theme"]
    with pytest.raises(ValidationError):
        pipeline.create_plan(brief)

def test_create_plan_defaults_mode_fixture():
    # 方案1：默认分析路径为 crawled（真实采集+LLM），非 fixture
    plan = _make_plan()
    assert plan["mode"] == "crawled"

def test_create_plan_camelcase_brief_survives_validation():
    """回归：camelCase 键（前端契约）不得被校验静默丢弃（内部存储为 snake_case）"""
    plan = _make_plan({**VALID_BRIEF, "costLimit": 80, "priceRange": [10, 20]})
    assert plan["brief"]["cost_limit"] == 80
    assert plan["brief"]["price_range"] == [10, 20]

def test_list_plans_returns_summaries_sorted_desc():
    p1 = _make_plan()
    p2 = _make_plan({**VALID_BRIEF, "theme": "第二个主题"})
    plans = pipeline.list_plans()
    ids = [p["plan_id"] for p in plans]
    assert set(ids) == {p1["plan_id"], p2["plan_id"]}
    assert all("theme" in p and "status" in p for p in plans)

def test_list_plans_includes_mode_metadata():
    """列表摘要必须暴露 mode，供前端 SourceTag 标注数据来源（crawled/fixture/live）"""
    plan = _make_plan()
    plans = pipeline.list_plans()
    summary = next(p for p in plans if p["plan_id"] == plan["plan_id"])
    assert "mode" in summary
    assert summary["mode"] == "crawled"

# ── ② 五看洞察 ───────────────────────────────────────────

def test_get_insights_returns_five_blocks():
    plan = _make_plan()
    insights = pipeline.get_insights(plan, advance=True)
    assert set(insights) == {
        "trendRadar",
        "consumerVoice",
        "competitiveMap",
        "insightBase",
        "trendGallery",
        "opportunityPool",  # 市场机会池：五看洞察 → 产品决策的中间产物（顶层平级字段）
        "dataSource",       # 数据来源标记：crawled | llm
    }
    assert plan["status"] == "insights_ready"
    # 思考过程呈现：processLog 是导师专项意见要求的字段，必须在
    assert insights["trendRadar"]["processLog"]

def test_get_insights_preserves_archived_status():
    plan = _make_plan()
    _advance_to_plan_card(plan)
    pipeline.archive_plan(plan)
    pipeline.get_insights(plan)
    assert plan["status"] == "archived"

# ── ③ 机会生成 ───────────────────────────────────────────

def test_get_opportunities_returns_three_cards_with_evidence():
    plan = _make_plan()
    cards = pipeline.get_opportunities(plan, advance=True)
    assert len(cards) == 3
    assert plan["status"] == "opportunities_ready"
    for card in cards:
        assert card["id"] and card["title"] and card["priceBand"]
        # 每张方向卡必须挂四方依据链（评委口径：数据驱动决策）
        assert len(card["evidence"]) == 4

# ── ⑤ 商品策略：成本校验边界 ──────────────────────────────

def test_cost_check_margin_exactly_at_redline_passes():
    # 毛利率 = (price - cost) / price = 0.30 恰好过红线
    check = pipeline.cost_check({"pricing": {"price": "100 元"}}, cost_limit=70.0)
    assert check.passed is True
    assert check.margin == pytest.approx(0.30, abs=1e-3)

def test_cost_check_below_redline_fails():
    check = pipeline.cost_check({"pricing": {"price": "39 元"}}, cost_limit=30.0)
    assert check.passed is False
    assert "打回创意环节" in check.reason

def test_cost_check_missing_price_fails():
    check = pipeline.cost_check({"pricing": {"price": "待定"}}, cost_limit=25.0)
    assert check.passed is False
    assert "定价缺失" in check.reason

# ── ④⑤⑥ 企划卡生成 ─────────────────────────────────────

def test_generate_plan_card_assembles_full_card():
    plan = _make_plan()
    card = _advance_to_plan_card(plan)
    assert card is not None
    assert card["name"] == "库洛米表情磁吸小风扇"
    assert card["source"] == "fixture"
    assert card["opportunityId"] == "ip-collect"
    # 企划案必备要素（导师口径：创意 + 视觉 + 节奏 + 价格策略）
    assert card["conceptImage"]
    assert card["schedule"]
    assert card["pricing"]["price"]
    # 成本校验挂在卡上：59 元定价、成本上限 25 → 毛利 57.6% 过红线
    assert card["costCheck"]["passed"] is True
    assert plan["status"] == "plan_card_ready"
    assert plan["selected_opportunity"] == "ip-collect"
    # 思考过程呈现（导师专项）：冻结推理 + 末行实时成本校验
    assert card["processLog"]
    assert card["processLog"][-1].startswith("成本校验：定价 59 元")
    assert "校验通过" in card["processLog"][-1]

def test_generate_plan_card_unknown_opportunity_returns_none():
    plan = _make_plan()
    pipeline.generate_insights(plan)
    pipeline.generate_opportunities(plan)
    assert pipeline.generate_plan_card(plan, "opp_1") is None
    assert plan["plan_card"] is None

def test_generate_plan_card_live_mode_uses_jimeng_with_fallback(monkeypatch):
    calls = {}

    def fake_generate(prompt, fallback):
        calls["prompt"] = prompt
        calls["fallback"] = fallback
        return "https://example.com/generated.png"

    monkeypatch.setattr(pipeline.jimeng, "generate_concept_image", fake_generate)
    plan = _make_plan({**VALID_BRIEF, "mode": "live"})
    card = _advance_to_plan_card(plan, "healing-nature")
    assert card["conceptImage"] == "https://example.com/generated.png"
    assert card["source"] == "live"
    # prompt 组装自设计语言 + 关键词
    assert "植物疗愈桌面风扇" in calls["prompt"]

def test_generate_plan_card_live_mode_falls_back_to_frozen_image(monkeypatch):
    monkeypatch.setattr(
        pipeline.jimeng, "generate_concept_image", lambda prompt, fallback: fallback
    )
    plan = _make_plan({**VALID_BRIEF, "mode": "live"})
    card = _advance_to_plan_card(plan, "outdoor-clip")
    assert card["conceptImage"] == fixtures.PLAN_TEMPLATES["outdoor-clip"]["conceptImage"]

def test_generate_plan_card_cost_overrun_marks_check_failed():
    # 成本上限高于定价 → 毛利率为负，校验必须不通过（打回创意环节）
    plan = _make_plan({**VALID_BRIEF, "costLimit": 80})
    card = _advance_to_plan_card(plan, "ip-collect")  # 定价 59 元
    assert card["costCheck"]["passed"] is False
    assert card["costCheck"]["margin"] < pipeline.MIN_GROSS_MARGIN
    # 思考过程末行如实呈现校验失败（真管线：随约束输入变化）
    assert "低于红线" in card["processLog"][-1]

# ── 改稿沟通 ─────────────────────────────────────────────

def test_revise_plan_fallback_reply_when_llm_unconfigured(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "complete", lambda **kwargs: None)
    plan = _make_plan()
    # 改稿只依赖「已有企划卡」，直接置入，不依赖企划卡 LLM 生成链路
    plan["plan_card"] = {"name": "测试企划卡", "concept": "测试概念"}
    plan["status"] = "plan_card_ready"
    turn = pipeline.revise_plan(plan, "把配色改成薄荷绿")
    assert "冻结数据演示环境" in turn["reply"]
    assert len(plan["revise_logs"]) == 1
    assert plan["revise_logs"][0]["message"] == "把配色改成薄荷绿"

def test_revise_plan_uses_llm_answer_when_available(monkeypatch):
    monkeypatch.setattr(pipeline.llm, "complete", lambda **kwargs: "可以，配色方案将调整为薄荷绿。")
    plan = _make_plan()
    plan["plan_card"] = {"name": "测试企划卡", "concept": "测试概念"}
    plan["status"] = "plan_card_ready"
    turn = pipeline.revise_plan(plan, "把配色改成薄荷绿")
    assert turn["reply"] == "可以，配色方案将调整为薄荷绿。"

# ── 归档 ─────────────────────────────────────────────────

def test_archive_plan_requires_plan_card():
    plan = _make_plan()
    with pytest.raises(StateTransitionError):
        pipeline.archive_plan(plan)

def test_archive_plan_marks_archived_and_readonly_apis_keep_status():
    plan = _make_plan()
    _advance_to_plan_card(plan)
    archived = pipeline.archive_plan(plan)
    assert archived["status"] == "archived"
    assert archived["archived_at"]
    # 归档后再拉洞察/机会，只读接口不得把状态降级回去
    pipeline.get_insights(plan)
    pipeline.get_opportunities(plan)
    assert plan["status"] == "archived"

# ── 状态持久化 ───────────────────────────────────────────

def test_state_roundtrip_save_and_load():
    plan = _make_plan()
    _advance_to_plan_card(plan)
    pipeline._save_state()
    payload = json.loads(repository._STATE_FILE.read_text(encoding="utf-8"))
    assert plan["plan_id"] in payload
    assert payload[plan["plan_id"]]["selected_opportunity"] == plan["selected_opportunity"]
    loaded = pipeline._load_state()
    assert loaded[plan["plan_id"]]["plan_card"]["name"] == plan["plan_card"]["name"]

def test_load_state_tolerates_corrupt_file():
    repository._STATE_FILE.write_text("not json {{{", encoding="utf-8")
    assert pipeline._load_state() == {}

def test_seed_demo_restores_saved_plan():
    saved = {
        "demo": {
            "plan_id": "demo",
            "brief": fixtures.DEMO_BRIEF,
            "mode": "fixture",
            "created_at": "2026-08-12T00:00:00+00:00",
            "status": "archived",
            "selected_opportunity": "ip-collect",
            "plan_card": {"name": "已归档企划卡"},
            "revise_logs": [],
            "archived_at": "2026-08-12T01:00:00+00:00",
        }
    }
    repository._STATE_FILE.write_text(json.dumps(saved), encoding="utf-8")
    pipeline.seed_demo()
    assert pipeline._PLANS["demo"]["status"] == "archived"
    assert pipeline._PLANS["demo"]["plan_card"]["name"] == "已归档企划卡"

def test_seed_demo_creates_fresh_plan_when_no_state():
    pipeline.seed_demo()
    demo = pipeline._PLANS["demo"]
    assert demo["status"] == "brief_locked"
    assert demo["brief"]["theme"] == fixtures.DEMO_BRIEF["theme"]

# ── Stage 5 原子动作契约 ─────────────────────────────────

def test_generate_insights_success_advances_status():
    plan = _make_plan()
    insights = pipeline.generate_insights(plan)
    assert plan["status"] == "insights_ready"
    assert set(insights) == {
        "trendRadar", "consumerVoice", "competitiveMap", "insightBase", "trendGallery",
        "opportunityPool", "dataSource",
    }

def test_generate_insights_failure_does_not_advance_status(monkeypatch):
    """失败回滚：洞察生成抛异常时状态与旧产物不变"""
    plan = _make_plan()

    def boom(category):
        raise RuntimeError("洞察解析失败")

    monkeypatch.setattr("app.planning.service._resolve_insight_bundle", boom)
    with pytest.raises(RuntimeError):
        pipeline.generate_insights(plan)
    assert plan["status"] == "brief_locked"
    assert plan["plan_card"] is None

def test_generate_opportunities_success_advances_status():
    plan = _make_plan()
    pipeline.generate_insights(plan)
    cards = pipeline.generate_opportunities(plan)
    assert plan["status"] == "opportunities_ready"
    assert len(cards) == 3
    assert len(plan["opportunities"]) == 3

def test_generate_opportunities_failure_does_not_advance_status(monkeypatch):
    """失败回滚：机会生成抛异常时状态不变"""
    plan = _make_plan()
    pipeline.generate_insights(plan)

    def boom(category, bundle, brief):
        raise RuntimeError("机会生成失败")

    monkeypatch.setattr("app.planning.service._opportunities_from_bundle", boom)
    with pytest.raises(RuntimeError):
        pipeline.generate_opportunities(plan)
    assert plan["status"] == "insights_ready"

def test_generate_plan_card_failure_does_not_advance_status(monkeypatch):
    """失败回滚：企划卡组装抛异常时状态与产物不变"""
    plan = _make_plan()
    pipeline.generate_insights(plan)
    pipeline.generate_opportunities(plan)

    def boom(plan_arg, template, opportunity, opportunity_id):
        raise RuntimeError("企划卡组装失败")

    monkeypatch.setattr("app.planning.service._assemble_fixture_plan_card", boom)
    with pytest.raises(RuntimeError):
        pipeline.generate_plan_card(plan, "ip-collect")  # fixture 模板路径
    assert plan["status"] == "opportunities_ready"
    assert plan["plan_card"] is None
    assert plan["selected_opportunity"] is None

def test_repeat_request_raises_transition_error():
    """同状态重复请求：统一稳定返回 StateTransitionError（409 策略）"""
    plan = _make_plan()
    pipeline.generate_insights(plan)  # brief_locked → insights_ready
    with pytest.raises(StateTransitionError) as exc:
        pipeline.generate_insights(plan)
    assert exc.value.expected == "brief_locked"
    assert exc.value.actual == "insights_ready"

def test_generate_opportunities_before_insights_raises():
    plan = _make_plan()  # brief_locked，非法前置状态
    with pytest.raises(StateTransitionError):
        pipeline.generate_opportunities(plan)

def test_generate_plan_card_before_opportunities_raises():
    plan = _make_plan()
    pipeline.generate_insights(plan)  # insights_ready，非法前置状态
    with pytest.raises(StateTransitionError):
        pipeline.generate_plan_card(plan, "ip-collect")

def test_archive_before_plan_card_raises():
    plan = _make_plan()
    pipeline.generate_insights(plan)
    pipeline.generate_opportunities(plan)  # opportunities_ready，非法前置状态
    with pytest.raises(StateTransitionError):
        pipeline.archive_plan(plan)

def test_revise_on_archived_raises():
    """archived 只读：禁止改稿"""
    plan = _make_plan()
    _advance_to_plan_card(plan)
    pipeline.archive_plan(plan)
    with pytest.raises(StateTransitionError):
        pipeline.revise_plan(plan, "把配色改成薄荷绿")

def test_review_plan_is_readonly():
    """复盘追问独立只读：不修改 plan、不写 revise_logs、不推进状态"""
    plan = _make_plan()
    _advance_to_plan_card(plan)
    pipeline.archive_plan(plan)
    logs_before = list(plan["revise_logs"])
    status_before = plan["status"]
    result = pipeline.review_plan(plan, "这个定价的依据是什么？")
    assert "question" in result and "answer" in result
    # 只读：状态、产物、改稿日志均不变
    assert plan["status"] == status_before == "archived"
    assert plan["revise_logs"] == logs_before
