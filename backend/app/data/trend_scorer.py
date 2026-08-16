"""趋势价值打分器 — 从"这个词在榜上吗"到"这个趋势值不值得名创做"

定位：趋势感知链路的决策层。聚合器（hot_topics）只回答"有没有信号"，
本模块回答"信号有没有价值"——四维打分 + 显式依据链，输出趋势卡：
每个分数都能点开看到它依据了哪条真实数据（AI 幻觉防线：
LLM 只做表达，事实来自数据源，打分规则是显式的）。

四维模型（与机会生成的"四维打分"口径衔接）：
  动能 Momentum   35% — 在涨还是已凉：热搜命中/名次 + 离线增速
  契合 Fit        25% — 名创能做吗：品类词库匹配 + 价格带适配
  转化 Conversion 25% — 围观还是掏钱：电商联想词的购买意图强度
  窗口 Window     15% — 还来得及吗：生命周期阶段 × 开品周期倒排

分级：≥70 机会池 / 50-70 观察 / <50 淘汰（对应思考过程里"淘汰7个保留3个"）。

设计纪律：本模块是纯函数，不触网——数据由调用方采集后传入，
单测可完全离线。所有打分规则确定性可复现，可回测。
"""

from __future__ import annotations

from typing import Any

# ── 判定词库（显式规则，可审计可回测）─────────────────────

# 名创品类契合词库：碎片 → (契合基础分, 理由)
FIT_LEXICON: dict[str, tuple[int, str]] = {
    "库洛米": (90, "三丽鸥头部 IP，名创 IP 联名主航道"),
    "三丽鸥": (90, "名创核心 IP 合作方"),
    "玉桂狗": (85, "三丽鸥 IP，衍生品成熟"),
    "风扇": (75, "便携小电器，客单价落在 10-100 元价格带"),
    "香薰": (80, "家居情绪消费，名创优势品类"),
    "收纳": (75, "家居收纳基本盘品类"),
    "露营": (70, "户外场景延伸，需做轻量便携款适配"),
    "工位": (70, "桌面场景，与收纳/摆件/3C 配件协同"),
    "桌面": (72, "桌面美学场景，装饰属性契合"),
    "文具": (75, "文创基本盘"),
    "玩偶": (80, "潮玩毛绒主航道"),
    "水杯": (72, "餐厨水具基本盘"),
    "防晒": (68, "季节个护，窗口性强"),
}

# 购买意图后缀（联想词带这些 = 用户在挑货，不是在看热闹）
INTENT_SUFFIXES = (
    "静音", "续航", "新款", "便携", "充电", "学生", "宿舍", "办公",
    "礼物", "联名", "正品", "价格", "推荐", "测评", "平替", "家用",
    "大风力", "迷你", "手持", "支架", "灯",
)

# 娱乐意图后缀（联想词带这些 = 围观流量，转化弱）
ENTERTAINMENT_SUFFIXES = ("视频", "搞笑", "图片", "表情包", "梗", "头像", "壁纸", "文案")

# 分级阈值
GRADE_OPPORTUNITY = 70  # 机会池
GRADE_WATCH = 50        # 观察区


# ── 四维打分（每维返回分数 + 依据链）───────────────────────


def _score_momentum(
    keyword: str,
    hot_hits: list[dict[str, Any]],
    growth_pct: float | None,
) -> dict[str, Any]:
    """动能：热搜命中（源数 × 名次）+ 离线增速"""
    score = 0.0
    evidence: list[str] = []

    if hot_hits:
        sources = sorted({h["source"] for h in hot_hits})
        score += min(50, 25 * len(sources))  # 多源交叉命中强于单源
        best_rank = min(h.get("rank") or 99 for h in hot_hits)
        rank_bonus = 20 if best_rank <= 10 else 10 if best_rank <= 30 else 5
        score += rank_bonus
        evidence.append(
            f"热搜命中 {'/'.join(sources)}（最高 #{best_rank}）→ {score:.0f} 分"
        )
    else:
        evidence.append("当日热搜未命中（零命中≠无趋势，看其他维度）")

    if growth_pct is not None:
        growth_score = min(40, max(0, growth_pct / 2))  # +80% 增速封顶 40 分
        score += growth_score
        evidence.append(f"预采集增速 {growth_pct:+.0f}% → 动能 +{growth_score:.0f} 分")

    return {"score": round(min(100, score), 1), "evidence": evidence}


def _score_fit(keyword: str) -> dict[str, Any]:
    """契合：品类词库匹配（最长碎片优先）"""
    for frag in sorted(FIT_LEXICON, key=len, reverse=True):
        if frag in keyword:
            base, reason = FIT_LEXICON[frag]
            return {"score": float(base), "evidence": [f"命中品类词「{frag}」：{reason}"]}
    return {"score": 40.0, "evidence": ["未命中名创品类词库，契合待人工评估"]}


def _score_conversion(
    keyword: str,
    suggestions: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """转化：电商联想词的购买意图占比"""
    if not suggestions:
        return {"score": 50.0, "evidence": ["无电商联想数据，给中性分（缺失不惩罚）"]}

    queries = [s["query"] for s in suggestions]
    intent_hits = [
        q for q in queries
        if any(suf in q for suf in INTENT_SUFFIXES)
        and not any(ent in q for ent in ENTERTAINMENT_SUFFIXES)
    ]
    ratio = len(intent_hits) / max(len(queries), 1)
    score = 40 + 60 * ratio
    evidence = [f"电商联想 {len(queries)} 条，购买意图 {len(intent_hits)} 条（{ratio:.0%}）"]
    if intent_hits:
        evidence.append(f"意图词示例：{'、'.join(intent_hits[:3])}")
    return {"score": round(score, 1), "evidence": evidence}


def _score_window(
    hot_hits: list[dict[str, Any]],
    growth_pct: float | None,
) -> dict[str, Any]:
    """窗口：生命周期阶段判定（萌芽/爬升最佳，峰值次之，衰退最差）"""
    if growth_pct is not None and growth_pct >= 50 and not hot_hits:
        stage, score = "爬升期（未出圈，窗口最佳）", 90.0
    elif growth_pct is not None and growth_pct >= 50 and hot_hits:
        stage, score = "爬升期（已出圈，窗口尚可）", 75.0
    elif hot_hits and (growth_pct is None or growth_pct < 20):
        stage, score = "峰值期（大众已熟知，需差异化切入）", 55.0
    elif growth_pct is not None and growth_pct >= 20:
        stage, score = "萌芽期（信号弱，适合轻量试水）", 65.0
    else:
        stage, score = "信号不足，无法判定生命周期", 50.0
    return {"score": score, "evidence": [f"生命周期：{stage}"]}


# ── 总分合成 ─────────────────────────────────────────────

WEIGHTS = {"momentum": 0.35, "fit": 0.25, "conversion": 0.25, "window": 0.15}
DIM_LABELS = {"momentum": "动能", "fit": "契合", "conversion": "转化", "window": "窗口"}


def score_trend(
    keyword: str,
    *,
    hot_hits: list[dict[str, Any]] | None = None,
    suggestions: list[dict[str, Any]] | None = None,
    growth_pct: float | None = None,
) -> dict[str, Any]:
    """给单个趋势关键词打四维分，返回趋势卡（含依据链）

    Args:
        keyword: 趋势关键词，如 "小风扇"
        hot_hits: 热搜聚合器命中条目（hot_topics.match_keywords 的 hits）
        suggestions: 电商联想词（TaobaoSuggestConnector.get_suggestions）
        growth_pct: 预采集的增速信号（%），无则传 None

    Returns:
        {"keyword", "total", "grade", "dimensions": {dim: {score, evidence}},
         "weights"} — total 为加权总分，grade ∈ 机会池/观察/淘汰
    """
    hits = hot_hits or []
    dims = {
        "momentum": _score_momentum(keyword, hits, growth_pct),
        "fit": _score_fit(keyword),
        "conversion": _score_conversion(keyword, suggestions),
        "window": _score_window(hits, growth_pct),
    }
    total = sum(dims[d]["score"] * WEIGHTS[d] for d in dims)
    grade = (
        "机会池" if total >= GRADE_OPPORTUNITY
        else "观察" if total >= GRADE_WATCH
        else "淘汰"
    )
    return {
        "keyword": keyword,
        "total": round(total, 1),
        "grade": grade,
        "dimensions": dims,
        "weights": WEIGHTS,
    }


def score_trends(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量打分并按总分排序（机会池在前）

    Args:
        candidates: [{"keyword": ..., "hot_hits": [...], "suggestions": [...],
                      "growth_pct": ...}, ...]（字段同 score_trend）
    """
    cards = [score_trend(c["keyword"], **{k: v for k, v in c.items() if k != "keyword"})
             for c in candidates]
    return sorted(cards, key=lambda c: c["total"], reverse=True)


def summarize(cards: list[dict[str, Any]]) -> list[str]:
    """生成思考过程日志行（与机会生成 processLog 同款呈现口径）"""
    kept = [c for c in cards if c["grade"] == "机会池"]
    watching = [c for c in cards if c["grade"] == "观察"]
    dropped = [c for c in cards if c["grade"] == "淘汰"]
    lines = [f"趋势价值打分完成：{len(cards)} 个候选趋势，四维加权（动能35/契合25/转化25/窗口15）"]
    for c in cards[:5]:
        top_dim = max(c["dimensions"].items(), key=lambda kv: kv[1]["score"])
        lines.append(
            f"「{c['keyword']}」{c['total']} 分 → {c['grade']}"
            f"（最强维度：{DIM_LABELS[top_dim[0]]} {top_dim[1]['score']:.0f}）"
        )
    lines.append(
        f"筛选结果：机会池 {len(kept)} 个 / 观察 {len(watching)} 个 / 淘汰 {len(dropped)} 个"
    )
    return lines
