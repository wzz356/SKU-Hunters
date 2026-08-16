"""洞察增强 Agent（Insight Enrichment Agent）— 五段式驾驶舱数据源

定位：把已解析的五看洞察 bundle 二次推理成「五段式决策视图」所需的增强结构，
    全品类统一走本 Agent，品类间无特殊分支（小风扇不是特殊页面）。

数据纪律（与 trend_agent / opportunity_discovery 一致）：
- LLM 只写判断性文本（marketJudgment / verdict / 话题聚类 / 季节节奏），
  数字与溯源字段一律代码构建，禁止 LLM 编造数字。
- 采集侧没有的样本量（records）/ 同比增速（growthPct）如实留 None，
  前端按 None 回退为排名列表展示，不伪造。
- 任何环节失败（无 Key / 输出不合契约）→ 返回 None，
  前端回退基础视图，不产任何假数据。

与 opportunity pool 的边界：enrichment 不含机会池；机会池由 Opportunity Discovery
单独产出并挂 bundle.opportunityPool，前端统一从那里消费，禁止二次生成。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.planning import EnrichmentResult

# ── 子品类势头关键词（品类无关，从信号 metric 文本推导，不做品类硬编码）──
_SURGE_KW = ["爆发", "暴涨", "翻倍", "激增", "破圈", "增速第一", "同比第1", "百亿"]
_RISING_KW = ["增长", "增速", "跑赢", "上升", "扩容", "高增", "过万", "月销", "↑"]
_EMERGING_KW = ["回潮", "迁移", "升级", "新兴", "新赛道", "结构性新增", "→"]


def _derive_momentum(metric: str) -> str:
    """从信号 metric 文本推导势头（surge > rising > emerging > stable）

    优先识别正增长百分比（同比 +X%）：涨幅越大势头越强；无数字再按语义关键词。
    品类无关，不硬编码品类词。
    """
    if not metric:
        return "stable"
    pcts = re.findall(r"[+＋]\s*(\d+(?:\.\d+)?)\s*%", metric)
    if pcts:
        max_pct = max(float(p) for p in pcts)
        return "surge" if max_pct >= 100 else "rising"
    if any(k in metric for k in _SURGE_KW):
        return "surge"
    if any(k in metric for k in _RISING_KW):
        return "rising"
    if any(k in metric for k in _EMERGING_KW):
        return "emerging"
    return "stable"


# ── LLM prompt ────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """你是名创优品资深商品企划经理，负责「洞察增强」（Insight Enrichment）。
基于已解析的五看洞察信号（趋势/用户/竞品），对品类做二次推理，输出五段式决策视图所需的判断文本。

输出纪律：
1. 只输出一个 JSON 对象，不要输出任何其他文字、不要用代码围栏。
2. 只分析给定品类，禁止套用其他品类（如小风扇）的内容。
3. 数字一律不写：话题条数、样本量、同比增速等由代码构建，你只写判断性文字与话题名。
4. topicClusters 的每个 topic.name 必须从下方提供的【话题候选】里选取，不得自造新词；
   按需求类型聚类为 2-3 组（如 功能需求 / 场景需求 / 情绪与内容，可按品类实际调整）。
5. subCategoryTrends 只写 name 与 note：name 从【趋势信号】的信号名里选取（可按重要性排序），
   note 直接抄该信号对应的 source（溯源，不改写）。
6. seasonPlan.cycle 给 3-4 个上市节奏阶段（phase/months/action），launchSuggestion 一句话。

输出 JSON 结构：
{
  "marketJudgment": "一句话战略判断：这个品类市场正在发生什么根本变化",
  "trendSummary": {
    "verdict": "一句话趋势总览判断",
    "keywords": ["从话题候选挑选 5-8 个"]
  },
  "topicClusters": [{"type": "需求类型", "topics": [{"name": "真实话题词"}]}],
  "subCategoryTrends": [{"name": "信号名", "note": "该信号的 source"}],
  "seasonPlan": {
    "cycle": [{"phase": "阶段", "months": "月份", "action": "动作"}],
    "launchSuggestion": "上市建议"
  }
}"""


def _parse_llm_json(raw: str) -> dict | None:
    """容错解析 LLM 输出：剥代码围栏，截取首个 JSON 对象"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _serialize_signals(bundle: dict, category: str, brief: dict) -> str:
    """把 bundle 压缩成 LLM 可读信号摘要（只列真实字段，不加工、不编数）"""
    tr = bundle.get("trendRadar", {})
    cv = bundle.get("consumerVoice", {})
    cm = bundle.get("competitiveMap", {})

    lines = [f"【品类】{category}", f"【目标人群】{brief.get('audience', '') or '大众'}"]
    lines.append("【趋势信号】")
    for s in tr.get("signals", [])[:8]:
        lines.append(f"- {s.get('name', '')}｜{s.get('metric', '')}｜来源：{s.get('source', s.get('period', ''))}")
    lines.append("【话题候选（hot_words + 痛点关键词 + 信号名）】")
    candidates = list(tr.get("hotWords", []))[:15]
    for p in cv.get("painPoints", [])[:8]:
        short = re.split(r"[,，:：/（(]|(用户痛点-)", p.get("text", ""))[0].strip()[:14]
        if short and short not in candidates:
            candidates.append(short)
    for s in tr.get("signals", [])[:8]:
        # 信号名去「/」后的数据尾巴，保留概念主体（如「UPF50+ 三折伞 / 防晒黑科技」→「UPF50+ 三折伞」）
        name = re.split(r"[/／]", s.get("name", ""))[0].strip()[:14]
        if name and name not in candidates:
            candidates.append(name)
    lines.append("、".join(candidates))
    if cv.get("summary"):
        lines.append(f"【用户洞察摘要】{cv['summary']}")
    if cm.get("products"):
        lines.append(f"【竞品数】{len(cm['products'])} 个")
    return "\n".join(lines)


def _build_metrics(bundle: dict) -> list[dict[str, str]]:
    """趋势总览核心指标：真实采集计数（代码构建，LLM 不碰）"""
    tr = bundle.get("trendRadar", {})
    cv = bundle.get("consumerVoice", {})
    cm = bundle.get("competitiveMap", {})
    return [
        {"label": "趋势信号", "value": f"{len(tr.get('signals', []))} 条", "direction": "flat",
         "note": "来自社媒采集 trend_signals"},
        {"label": "用户痛点", "value": f"{len(cv.get('painPoints', []))} 条", "direction": "flat",
         "note": "高频未满足需求聚类"},
        {"label": "竞品样本", "value": f"{len(cm.get('products', []))} 个", "direction": "flat",
         "note": "价格 × 设计感矩阵"},
    ]


def _build_subcategory_trends(bundle: dict) -> list[dict[str, Any]]:
    """子品类趋势：从真实趋势信号推导（name/source 采集侧真实，records/growthPct 无则 None）"""
    tr = bundle.get("trendRadar", {})
    out: list[dict[str, Any]] = []
    for s in tr.get("signals", []):
        name = s.get("name", "")
        if not name:
            continue
        out.append({
            "name": name,
            "records": None,          # 采集侧无样本量，不编造
            "growthPct": None,        # 采集侧无同比增速，不编造
            "momentum": _derive_momentum(s.get("metric", "")),
            "note": s.get("source", s.get("period", "")),
        })
    return out


def build_enrichment(category: str, bundle: dict, brief: dict) -> dict[str, Any] | None:
    """生成洞察增强：LLM 写判断文本 + 代码构建数字；失败返回 None（前端回退基础视图）

    Returns:
        camelCase 增强 dict（挂 bundle.enrichment）；LLM 不可用/不合契约返回 None
    """
    from app.engine import llm

    user_prompt = _serialize_signals(bundle, category, brief) + "\n\n请输出该品类的洞察增强 JSON。"

    llm_data: dict = {}
    for _ in range(2):  # 瞬时限流/输出不合契约重试一次
        raw = llm.complete(_LLM_SYSTEM_PROMPT, user_prompt, temperature=0.4, max_tokens=4000)
        if raw:
            data = _parse_llm_json(raw)
            if isinstance(data, dict):
                llm_data = data
                break

    # 代码构建数字字段（无论 LLM 是否成功，数字都以真实计数为准）
    metrics = _build_metrics(bundle)
    sub_category_trends = _build_subcategory_trends(bundle)

    if not llm_data:
        # LLM 不可用：仍可产出「数字真实、判断留空」的增强，五段式结构完整，
        # 但判断文本（marketJudgment/verdict/clusters/seasonPlan）为空 → 视为失败返回 None，
        # 前端回退基础视图，避免展示无判断的残缺五段式。
        return None

    enrichment = {
        "marketJudgment": str(llm_data.get("marketJudgment", "")),
        "trendSummary": {
            "verdict": str((llm_data.get("trendSummary") or {}).get("verdict", "")),
            "metrics": metrics,
            "keywords": list((llm_data.get("trendSummary") or {}).get("keywords", [])),
        },
        "topicClusters": [
            {
                "type": str(c.get("type", "")),
                "topics": [{"name": str(t.get("name", "")), "count": None}
                           for t in c.get("topics", []) if t.get("name")],
            }
            for c in llm_data.get("topicClusters", [])
        ],
        "subCategoryTrends": sub_category_trends,
        "seasonPlan": {
            "cycle": [
                {"phase": str(p.get("phase", "")), "months": str(p.get("months", "")),
                 "action": str(p.get("action", ""))}
                for p in (llm_data.get("seasonPlan") or {}).get("cycle", [])
            ],
            "launchSuggestion": str((llm_data.get("seasonPlan") or {}).get("launchSuggestion", "")),
        },
    }

    # 契约校验（不含数字字段的严格校验，只保证结构可被前端消费）
    try:
        EnrichmentResult.model_validate(enrichment)
    except ValueError:
        return None
    return enrichment
