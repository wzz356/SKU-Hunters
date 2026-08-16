"""趋势价值打分器测试 — 纯函数，全离线

锁定四件事：
  1. 四维各自的打分规则（动能/契合/转化/窗口）
  2. 数据缺失时的降级语义（中性分，不惩罚）
  3. 总分权重合成与分级阈值（70 机会池 / 50 观察 / 以下淘汰）
  4. 排序与思考过程日志生成
"""

from app.data import trend_scorer
from app.data.trend_scorer import score_trend, score_trends, summarize

# ── 动能 ────────────────────────────────────────────────


def test_momentum_multi_source_hits_and_rank():
    hits = [
        {"source": "weibo", "word": "小风扇走红", "rank": 8, "heat": 999},
        {"source": "baidu", "word": "小风扇推荐", "rank": 15, "heat": 888},
    ]
    dim = trend_scorer._score_momentum("小风扇", hits, 60)
    # 双源 50 + 名次 top10 加 20 + 增速 60/2=30 → 100 封顶
    assert dim["score"] == 100.0
    assert any("weibo" in e for e in dim["evidence"])


def test_momentum_zero_hit_is_not_failure():
    dim = trend_scorer._score_momentum("冷门词", [], None)
    assert dim["score"] == 0.0
    assert "零命中≠无趋势" in dim["evidence"][0]


def test_momentum_growth_capped_at_40():
    dim = trend_scorer._score_momentum("词", [], 200)
    assert dim["score"] == 40.0  # 增速贡献封顶 40


# ── 契合 ────────────────────────────────────────────────


def test_fit_matches_longest_fragment():
    dim = trend_scorer._score_fit("库洛米小风扇")
    # 「库洛米」(3字) 优先于「风扇」(2字)
    assert dim["score"] == 90.0
    assert "库洛米" in dim["evidence"][0]


def test_fit_unknown_keyword_neutral():
    dim = trend_scorer._score_fit("量子力学")
    assert dim["score"] == 40.0
    assert "待人工评估" in dim["evidence"][0]


# ── 转化 ────────────────────────────────────────────────


def test_conversion_intent_ratio():
    suggestions = [
        {"query": "小风扇静音学生", "heat": 100},   # 意图
        {"query": "小风扇超长续航", "heat": 90},    # 意图
        {"query": "小风扇搞笑视频", "heat": 80},    # 娱乐（被排除）
        {"query": "小风扇图片", "heat": 70},        # 娱乐
    ]
    dim = trend_scorer._score_conversion("小风扇", suggestions)
    # 2/4 意图 → 40 + 60*0.5 = 70
    assert dim["score"] == 70.0
    assert "50%" in dim["evidence"][0]


def test_conversion_missing_data_neutral():
    dim = trend_scorer._score_conversion("词", None)
    assert dim["score"] == 50.0
    assert "缺失不惩罚" in dim["evidence"][0]


# ── 窗口 ────────────────────────────────────────────────


def test_window_rising_unexposed_is_best():
    dim = trend_scorer._score_window([], 78)
    assert dim["score"] == 90.0
    assert "窗口最佳" in dim["evidence"][0]


def test_window_peaked_needs_differentiation():
    hits = [{"source": "weibo", "word": "词", "rank": 3}]
    dim = trend_scorer._score_window(hits, 10)
    assert dim["score"] == 55.0
    assert "峰值期" in dim["evidence"][0]


# ── 总分与分级 ──────────────────────────────────────────


def test_total_weighted_and_graded():
    card = score_trend(
        "库洛米小风扇",
        hot_hits=[{"source": "weibo", "word": "库洛米", "rank": 5}],
        suggestions=[{"query": "库洛米风扇", "heat": 1}, {"query": "库洛米静音", "heat": 1}],
        growth_pct=50,
    )
    # 动能：单源25+名次20+增速25=70；契合90；转化 1/2 意图=70；窗口75（爬升已出圈）
    # 总分 = 70*.35 + 90*.25 + 70*.25 + 75*.15 = 24.5+22.5+17.5+11.25 = 75.75
    assert card["total"] == 75.8
    assert card["grade"] == "机会池"
    assert set(card["dimensions"]) == {"momentum", "fit", "conversion", "window"}


def test_grade_thresholds():
    assert score_trend("量子力学")["grade"] == "淘汰"  # 全中性 47.5
    # 无热度信号时契合再高也进不了机会池（模型语义：没声量就不是机会）
    assert score_trend("香薰", growth_pct=30)["grade"] == "淘汰"
    card = score_trend(
        "香薰",
        growth_pct=60,
        hot_hits=[{"source": "baidu", "word": "香薰推荐", "rank": 12}],
        suggestions=[{"query": "香薰家用推荐", "heat": 1}],
    )
    assert card["grade"] in ("机会池", "观察")


def test_score_trends_sorted_desc():
    cards = score_trends([
        {"keyword": "冷门词甲"},
        {"keyword": "库洛米风扇", "growth_pct": 60,
         "suggestions": [{"query": "库洛米风扇联名", "heat": 1}]},
    ])
    assert cards[0]["keyword"] == "库洛米风扇"
    assert cards[0]["total"] > cards[1]["total"]


def test_summarize_log_lines():
    cards = score_trends([
        {"keyword": "库洛米风扇", "growth_pct": 60,
         "suggestions": [{"query": "库洛米风扇联名", "heat": 1}]},
        {"keyword": "冷门词甲"},
    ])
    lines = summarize(cards)
    assert "四维加权" in lines[0]
    assert any("机会池 1 个" in line and "淘汰 1 个" in line for line in lines)


# ── /trend-scan 端点（非破坏式集成）────────────────────────


def test_trend_scan_endpoint_unavailable(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import planning

    monkeypatch.setattr(planning, "_TREND_SCAN_FILE", tmp_path / "missing.json")
    app = FastAPI()
    app.include_router(planning.router)
    resp = TestClient(app).get("/api/v1/trend-scan")
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_trend_scan_endpoint_serves_snapshot(monkeypatch, tmp_path):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import planning

    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(
        {"cards": [{"keyword": "小风扇", "total": 56.9, "grade": "观察"}],
         "process_log": ["line1"]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(planning, "_TREND_SCAN_FILE", snap)
    app = FastAPI()
    app.include_router(planning.router)
    data = TestClient(app).get("/api/v1/trend-scan").json()
    assert data["available"] is True
    assert data["cards"][0]["keyword"] == "小风扇"
