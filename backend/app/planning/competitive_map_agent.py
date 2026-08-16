"""Competitive Map Agent — 竞品验证层（不重新发现机会，只验证机会池）

定位：把采集到的竞品信息 + 用户决策因素，二次推理成「验证机会池是否成立」的结构：
   需求满足矩阵（竞品 × 需求维度，0-5 评分绑 reason）
   + 机会空位（用户需求 → 当前竞品不足 → 已有机会池方向）

数据纪律（与 consumer_voice_agent 一致）：
- 需求维度不由 LLM 生成，代码从 ConsumerVoice.decisionFactors 提取（约束：用户真实决策）。
- 0-5 评分为 LLM 判断，但必须绑 reason（真实卖点/用户反馈），裸数字被丢弃。
- 竞品名/需求维度/机会池 id 引用全部代码校验，命中不了丢弃，不产假数据。
- 机会空位 supportsOpportunityIds 强绑 opportunityPool（唯一机会来源），不生成新机会。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.planning.consumer_voice_agent import _clean_pain, _fuzzy_index
from app.schemas.planning import CompetitiveMap

_LLM_SYSTEM_PROMPT = """你是名创优品竞品分析 Agent。你的任务是「验证机会池是否成立」，不是重新发现机会。

基于采集到的竞品信息 + 用户决策因素，输出两个结构：

输出纪律：
1. 只输出一个 JSON 对象，不要任何解释文字、不要代码围栏。
2. needSatisfaction 的 competitor 必须从下方【竞品】里原样引用；need 必须从下方【需求维度】里原样引用；
   每个 score（0-5）必须给 1-3 条 reason，说明为什么这个分（引用该竞品的真实卖点 + 用户反馈），
   不给 reason 的评分无效。
3. opportunityGaps 是「用户需求 → 当前竞品不足 → 已有机会池方向」的解释：
   supportsOpportunityIds 必须从下方【机会池】的 id 里选，禁止生成机会池里没有的新机会；
   why 给 1-3 条证据（趋势关键词 / 痛点 / 竞品覆盖不足）。

输出 JSON 结构：
{
  "needSatisfaction": [
    {"competitor": "竞品名", "need": "需求维度", "score": 4, "reason": ["为什么这个分"]}
  ],
  "opportunityGaps": [
    {"userNeed": "用户需求", "competitorGap": "当前竞品不足", "opportunity": "对应机会池方向",
     "supportsOpportunityIds": ["机会池 id"], "why": ["证据"]}
  ]
}"""


def _parse_llm_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _build_matrix_and_gaps(
    data: dict,
    product_names: list[str],
    need_dims: list[str],
    pool_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """纯函数：校验 LLM 输出的需求满足矩阵 + 机会空位（可单测）

    纪律：竞品/需求维度引用必须命中真实数据；评分必须绑 reason（裸数字丢弃）；
    机会空位 supportsOpportunityIds 必须命中机会池 id，不生成机会池外的新机会。
    """
    matrix: list[dict[str, Any]] = []
    for cell in data.get("needSatisfaction", []):
        comp_idx = _fuzzy_index(product_names, str(cell.get("competitor", "")))
        need_idx = _fuzzy_index(need_dims, str(cell.get("need", "")))
        reasons = [str(r) for r in cell.get("reason", []) if r]
        if comp_idx < 0 or need_idx < 0 or not reasons:
            continue  # 引用命中不了 或 裸数字，丢弃
        try:
            score = max(0, min(5, int(cell.get("score", 0))))
        except (TypeError, ValueError):
            continue
        matrix.append({
            "competitor": product_names[comp_idx],
            "need": need_dims[need_idx],
            "score": score,
            "reason": reasons,
        })

    gaps: list[dict[str, Any]] = []
    for g in data.get("opportunityGaps", []):
        sup_ids = [pid for pid in g.get("supportsOpportunityIds", []) if pid in pool_ids]
        if not sup_ids:
            continue  # 不生成机会池外的新机会
        gaps.append({
            "userNeed": str(g.get("userNeed", "")),
            "competitorGap": str(g.get("competitorGap", "")),
            "opportunity": str(g.get("opportunity", "")),
            "supportsOpportunityIds": sup_ids,
            "why": [str(w) for w in g.get("why", []) if w],
        })
    return matrix, gaps


def _serialize(bundle: dict, category: str, need_dims: list[str]) -> str:
    cm = bundle.get("competitiveMap", {})
    pool = bundle.get("opportunityPool", [])
    lines = [f"【品类】{category}"]
    lines.append("【竞品（name｜卖点）】")
    for p in cm.get("products", [])[:8]:
        lines.append(f"- {p.get('name', '')}｜{p.get('sellingPoint', '')}")
    lines.append("【需求维度】")
    lines.append("、".join(need_dims))
    lines.append("【机会池（id｜title）】")
    for o in pool[:6]:
        lines.append(f"- {o.get('id', '')}｜{o.get('title', '')}")
    return "\n".join(lines)


def build_competitive_map_analysis(category: str, bundle: dict, brief: dict) -> dict[str, Any] | None:
    """生成需求满足矩阵 + 机会空位：LLM 写判断，代码校验引用；失败返回 None"""
    from app.engine import llm

    cm = bundle.get("competitiveMap", {})
    cv = bundle.get("consumerVoice", {})
    products = cm.get("products", [])
    pool = bundle.get("opportunityPool", [])
    pool_ids = [o.get("id", "") for o in pool]

    if not products:
        return None

    # 需求维度：代码从 decisionFactors 提取（约束：不 LLM 生成），无则回退痛点短标签
    decision_factors = (cv.get("userProfile") or {}).get("decisionFactors", [])
    need_dims = [str(d) for d in decision_factors if d][:6]
    if not need_dims:
        need_dims = [_clean_pain(p.get("text", "")) for p in cv.get("painPoints", [])[:5]]
    need_dims = [d for d in need_dims if d]
    if not need_dims:
        return None

    product_names = [p.get("name", "") for p in products]

    prompt = _serialize(bundle, category, need_dims)
    data: dict | None = None
    for _ in range(2):
        raw = llm.complete(_LLM_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=4000)
        if raw:
            data = _parse_llm_json(raw)
            if data:
                break
    if not data:
        return None

    matrix, gaps = _build_matrix_and_gaps(data, product_names, need_dims, pool_ids)

    if not matrix and not gaps:
        return None

    result = {
        "needDimensions": need_dims,
        "needSatisfaction": matrix,
        "opportunityGaps": gaps,
    }
    # 契约校验（不覆盖既有字段，仅校验新增字段合法）
    try:
        CompetitiveMap.model_validate({**{k: (cm.get(k) if k in cm else None) for k in
            ("processLog", "products", "gapZone", "priceBands", "sellingPoints")},
            "needDimensions": need_dims, "needSatisfaction": matrix, "opportunityGaps": gaps})
    except ValueError:
        return None
    return result
