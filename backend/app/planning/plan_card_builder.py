"""新品企划卡组装器（plan card builder）：机会卡 → 完整企划卡（LLM 动态生成）

职责边界：纯函数，输入 plan + opportunity，输出企划卡 dict；
不修改 plan（selected_opportunity/plan_card/status 的落盘由 service 编排）。

数据纪律：
- 企划卡内容一律由 LLM 基于「用户需求 + 机会卡 + 五看洞察」现场生成，无固定模板；
- 定价数字由代码从机会带推导 + cost_check 真实规则校验，不交给 LLM 编；
- LLM 未配置/输出连续不合契约 → 抛 LLMGenerationError，不产任何假数据。
"""

from __future__ import annotations

import re
from typing import Any

from app.planning.cost_rules import cost_check
from app.planning.insight_resolver import LLMGenerationError, _parse_llm_json
from app.planning.repository import _snake_keys
from app.schemas.planning import PlanCard, ProductProposal
from app.services import jimeng


def _find_opportunity(plan: dict, opportunity_id: str) -> dict | None:
    """只从 plan 里已生成保存的机会卡找（无 fixture 兜底）"""
    for o in plan.get("opportunities", []):
        if o.get("id") == opportunity_id:
            return o
    return None


def _derive_price_from_band(price_band: str) -> float:
    """价格带字符串 → 建议定价（取区间中值，保证成本校验有真实数字）"""
    nums = re.findall(r"\d+(?:\.\d+)?", price_band or "")
    if len(nums) >= 2:
        return round((float(nums[0]) + float(nums[1])) / 2, 1)
    if len(nums) == 1:
        return float(nums[0])
    return 59.0


def _concept_prompt_dynamic(opportunity: dict, brief: dict) -> str:
    """动态企划卡即梦 prompt：机会卡标题 + 方向 + 关键词 → 视觉描述"""
    return (
        f"产品概念渲染图，{opportunity.get('title', '')}，{opportunity.get('direction', '')}风格，"
        f"关键词：{'、'.join(opportunity.get('keywords', []) or [])}，"
        f"名创优品风格，干净背景，柔光，高质感"
    )


# ── LLM 企划卡生成 ─────────────────────────────────────────

_LLM_CARD_SYSTEM_PROMPT = """你是 SKU Hunters 新品企划工作室的创意总监。商品经理已选定机会方向，
你要输出一张完整的新品企划卡。只输出严格 JSON，不要输出任何解释文字、不要使用 markdown 代码围栏。

纪律：
1. 只围绕给定品类与选定机会方向创作，禁止套用其他品类（如小风扇）的内容；
2. 概念、功能、设计语言必须呼应所给机会卡与洞察材料，不空谈；
3. schedule 用「T-3月 / T-2月 / T-1月 / T0」四个节点；
4. validation 给 3 条可量化的上市验证指标；
5. 不要输出价格数字（定价由系统规则计算）。

输出 JSON 结构（字段名与类型必须严格一致）：
{
  "name": "产品名称（含品类词，易记）",
  "concept": "一句话概念（30 字以内）",
  "designLanguage": "设计语言描述（风格/配色/形态，50 字以内）",
  "keywords": ["设计关键词 3-5 个"],
  "features": ["核心功能点 3-5 条，每条 20 字以内"],
  "fusion": "跨品类融合说明（40 字以内）",
  "pricingReason": "定价理由（结合机会带与竞品空白，50 字以内）",
  "schedule": [{"time": "T-3月", "action": "动作"}],
  "validation": ["可量化验证指标 3 条"]
}"""


def _insights_digest(insights: dict | None) -> str:
    """五看洞察 → LLM 材料摘要（只取要点，控制 prompt 长度）"""
    if not insights:
        return "（无洞察材料，仅依据机会卡创作）"
    tr = insights.get("trendRadar", {})
    cv = insights.get("consumerVoice", {})
    cm = insights.get("competitiveMap", {})
    tg = insights.get("trendGallery", {})
    gap = cm.get("gapZone") or {}
    lines = ["【五看洞察摘要】"]
    sigs = [f"  · {s.get('name', '')}（{s.get('metric', '')}）" for s in tr.get("signals", [])[:3]]
    if sigs:
        lines.append("趋势信号：\n" + "\n".join(sigs))
    pains = [f"  · {p.get('text', '')}" for p in cv.get("painPoints", [])[:3]]
    if pains:
        lines.append("用户痛点：\n" + "\n".join(pains))
    if gap.get("label"):
        lines.append(f"竞品空白：{gap['label']}")
    colors = [c.get("name", "") for c in tg.get("colors", [])[:3] if isinstance(c, dict)]
    if colors:
        lines.append(f"当季流行色：{'、'.join(colors)}")
    return "\n".join(lines)


def _llm_plan_card_fields(plan: dict, opportunity: dict) -> dict[str, Any]:
    """LLM 生成企划卡内容字段（schema 校验不过重试 1 次，仍失败抛 LLMGenerationError）"""
    from app.engine import llm

    brief = plan["brief"]
    category = brief.get("category", "")
    evidence_text = "；".join(
        f"{e.get('from', '')}——{e.get('text', '')}"
        for e in opportunity.get("evidence", [])[:4]
    )
    user_prompt = (
        f"【品类】{category}\n"
        f"【企划主题】{brief.get('theme', '')}\n"
        f"【目标市场】{brief.get('market', '中国大陆')}　【目标人群】{brief.get('audience', '') or '大众'}\n"
        f"【零售价格带】{brief.get('price_range', brief.get('priceRange', ''))}\n\n"
        f"【选定机会方向】\n"
        f"标题：{opportunity.get('title', '')}\n"
        f"方向：{opportunity.get('direction', '')}\n"
        f"卖点：{opportunity.get('pitch', '')}\n"
        f"关键词：{'、'.join(opportunity.get('keywords', []) or [])}\n"
        f"依据：{evidence_text}\n\n"
        f"{_insights_digest(plan.get('insights'))}\n\n"
        f"请输出「{category}」企划卡 JSON。"
    )

    last_error = "LLM 未返回内容"
    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else (
            f"{user_prompt}\n\n上次输出未通过契约校验：{last_error}。请严格按结构重新输出。"
        )
        raw = llm.complete(_LLM_CARD_SYSTEM_PROMPT, prompt, temperature=0.5, max_tokens=4000)
        if not raw:
            last_error = "LLM 未配置或调用失败"
            continue
        data = _parse_llm_json(raw)
        if data is None:
            last_error = "输出不是合法 JSON"
            continue
        missing = [k for k in ("name", "concept", "features", "schedule", "validation") if not data.get(k)]
        if missing:
            last_error = f"缺必填字段：{'、'.join(missing)}"
            continue
        return data

    raise LLMGenerationError(f"企划卡 LLM 生成失败：{last_error}")


def _build_dynamic_plan_card(plan: dict, opportunity: dict) -> dict:
    """动态企划卡：LLM 生成内容 + 代码管定价/成本校验/即梦出图

    无论 mode 都尝试即梦出图，未配置/失败自动降级占位（fail-soft）。
    LLM 生成失败抛 LLMGenerationError（API 层映射 503），不产假数据。
    """
    brief = plan["brief"]
    cost_limit = float(brief.get("cost_limit", brief.get("costLimit", 25)))
    opp_id = opportunity.get("id", "")
    direction = opportunity.get("direction", "")
    price_band = opportunity.get("priceBand", "49-99 元")
    price = _derive_price_from_band(price_band)

    fields = _llm_plan_card_fields(plan, opportunity)

    concept_image = jimeng.generate_concept_image(
        prompt=_concept_prompt_dynamic(opportunity, brief),
        fallback=None,
    )

    check = cost_check({"pricing": {"price": f"{price:g} 元"}}, cost_limit)

    process_log = [
        f"承接方向「{direction}」：锁定核心创意",
        "LLM 创意设计：基于机会卡 + 五看洞察生成概念/功能/节奏",
        f"即梦文生图：{'概念图已生成' if concept_image else '未配置或生成失败，自动降级占位'}",
        f"定价推导：{price_band} 机会带 → 建议 {price:g} 元",
    ]
    if check.price is not None:
        process_log.append(
            f"成本校验：定价 {check.price:g} 元 / 成本上限 {check.cost_limit:g} 元 → {check.reason}"
        )
    else:
        process_log.append(f"成本校验：{check.reason}")

    card = {
        "name": str(fields.get("name", "")),
        "conceptImage": concept_image or "",
        "concept": str(fields.get("concept", "")),
        "designLanguage": str(fields.get("designLanguage", "")),
        "keywords": [str(k) for k in fields.get("keywords", [])][:5],
        "features": [str(f) for f in fields.get("features", [])][:5],
        "fusion": str(fields.get("fusion", "")),
        "pricing": {
            "price": f"{price:g} 元",
            "reason": str(fields.get("pricingReason", "")) or f"落在 {price_band} 机会带",
        },
        "schedule": [
            {"time": str(s.get("time", "")), "action": str(s.get("action", ""))}
            for s in fields.get("schedule", [])[:4] if isinstance(s, dict)
        ],
        "validation": [str(v) for v in fields.get("validation", [])][:3],
        "processLog": process_log,
        "costCheck": check.model_dump(),
        "opportunityId": opp_id,
        "source": "llm",
    }
    _ = PlanCard.model_validate(_snake_keys(card))
    return card


# ── 新品企划案（Product Proposal，面向评委的六模块呈现）───────────────

_PROPOSAL_SYSTEM_PROMPT = """你是名创优品商品企划总监。基于已选定的机会方向 + 资产适配结果，
输出「新品企划案」的创意与商业文本。只输出严格 JSON，不要解释文字、不要代码围栏。

纪律：
1. 设计语言/颜色/材质已由资产适配给定（见材料），你只在此基础上生成 pattern（花纹）与 moodboardPrompt，
   禁止凭空生成「植物/蝴蝶/玻璃瓶」这类与给定设计语言无关的随机审美。
2. 不输出任何财务数字（成本/毛利由系统规则核算）；business 只写 SKU 策略、渠道打法、上市节奏。
3. specification 给 3-5 条 module→solution；growthPath 给 3-4 条 stage→action，可执行、不空谈。

输出 JSON 结构：
{
  "name": "产品名称（含品类词，易记）",
  "slogan": "一句话定位（15字内）",
  "concept": "一句话概念（30字内）",
  "pattern": "花纹/图案描述（基于给定设计语言+颜色+材质）",
  "moodboardPrompt": "情绪板英文 prompt（绑定IP+设计语言+颜色+材质，用于出图）",
  "specification": [{"module": "功能模块", "solution": "实现方案"}],
  "skuStrategy": "SKU 策略（如 基础款/IP联名款/限定礼盒款）",
  "launchPlan": "上市节奏（阶段化）",
  "growthPath": [{"stage": "阶段", "action": "动作"}]
}"""


def _llm_proposal_fields(plan: dict, opportunity: dict, asset: dict) -> dict[str, Any]:
    """LLM 生成企划案创意/商业文本（设计语言/颜色/材质不走 LLM，来自 assetFit）"""
    from app.engine import llm

    brief = plan["brief"]
    category = brief.get("category", "")
    user_prompt = (
        f"【品类】{category}\n"
        f"【选定机会方向】{opportunity.get('title', '')}｜{opportunity.get('pitch', '')}\n"
        f"【目标人群】{opportunity.get('targetUser', '')}　【场景】{opportunity.get('scenario', '')}\n"
        f"【用户痛点】{opportunity.get('painPoint', '')}\n"
        f"【竞品空白】{opportunity.get('competitorGap', '')}\n"
        f"【资产适配】IP={asset.get('ip', '')}；设计语言={asset.get('designLanguage', '')}；"
        f"颜色={asset.get('color', '')}；材质={asset.get('material', '')}\n\n"
        f"请输出企划案 JSON。"
    )

    last_error = "LLM 未返回内容"
    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else (
            f"{user_prompt}\n\n上次输出未通过契约校验：{last_error}。请严格按结构重新输出。"
        )
        raw = llm.complete(_PROPOSAL_SYSTEM_PROMPT, prompt, temperature=0.5, max_tokens=4000)
        if not raw:
            last_error = "LLM 未配置或调用失败"
            continue
        data = _parse_llm_json(raw)
        if data is None:
            last_error = "输出不是合法 JSON"
            continue
        if not data.get("slogan") or not data.get("specification"):
            last_error = "缺 slogan/specification"
            continue
        return data
    raise LLMGenerationError(f"企划案 LLM 生成失败：{last_error}")


def _trend_evidence(insights: dict | None) -> str:
    """背景趋势证据：取趋势信号名（代码，不 LLM）"""
    if not insights:
        return ""
    sigs = [s.get("name", "") for s in insights.get("trendRadar", {}).get("signals", [])[:3]]
    return "、".join(s for s in sigs if s)


def _build_product_proposal(plan: dict, opportunity: dict) -> dict:
    """新品企划案：消费机会卡 + 资产适配 + LLM 创意/商业 + 即梦图 + 成本校验

    不重新发现机会；设计（颜色/材质/设计语言）来自 assetFit，不 LLM 随机审美；
    成本/定价来自 cost_check 规则，不编财务数字。
    """
    brief = plan["brief"]
    asset = opportunity.get("assetFit") or {}
    price_band = opportunity.get("priceBand", "49-99 元")
    price = _derive_price_from_band(price_band)
    cost_limit = float(brief.get("cost_limit", brief.get("costLimit", 25)))

    fields = _llm_proposal_fields(plan, opportunity, asset)

    # 即梦图 prompt 绑定 Opportunity + AssetFit + 设计语言 + 颜色 + 材质
    image_prompt = (
        f"{opportunity.get('title', '')}，{asset.get('designLanguage', '')}风格，"
        f"{asset.get('color', '')}，{asset.get('material', '')}，"
        f"{opportunity.get('scenario', '')}场景，产品设计渲染图，名创优品风格，柔光高质感"
    )
    image_url = jimeng.generate_concept_image(prompt=image_prompt, fallback=None)

    check = cost_check({"pricing": {"price": f"{price:g} 元"}}, cost_limit)

    proposal = {
        "name": str(fields.get("name", "")) or opportunity.get("title", ""),
        "opportunityId": opportunity.get("id", ""),
        "background": {
            "marketOpportunity": opportunity.get("pitch", ""),
            "userNeed": "；".join(x for x in (opportunity.get("painPoint", ""), opportunity.get("competitorGap", "")) if x),
            "trendEvidence": _trend_evidence(plan.get("insights")),
        },
        "positioning": {
            "targetUser": opportunity.get("targetUser", ""),
            "scenario": opportunity.get("scenario", ""),
            "priceRange": price_band,
            "slogan": str(fields.get("slogan", "")),
        },
        "design": {
            "concept": str(fields.get("concept", "")),
            "designLanguage": asset.get("designLanguage", ""),
            "color": asset.get("color", ""),
            "material": asset.get("material", ""),
            "pattern": str(fields.get("pattern", "")),
            "moodboardPrompt": str(fields.get("moodboardPrompt", "")),
            "imageUrl": image_url or "",
        },
        "specification": [
            {"module": str(s.get("module", "")), "solution": str(s.get("solution", ""))}
            for s in fields.get("specification", []) if isinstance(s, dict)
        ][:5],
        "business": {
            # 成本目标 = 成本上限约束（来自 brief，非真实制造成本），真实成本待供应链核算
            "costTarget": f"成本上限 {cost_limit:g} 元" if cost_limit > 0 else "待供应链核算",
            "retailPrice": f"{price:g} 元",
            "skuStrategy": str(fields.get("skuStrategy", "")),
            "launchPlan": str(fields.get("launchPlan", "")),
        },
        "growthPath": [
            {"stage": str(g.get("stage", "")), "action": str(g.get("action", ""))}
            for g in fields.get("growthPath", []) if isinstance(g, dict)
        ][:4],
    }
    _ = ProductProposal.model_validate(_snake_keys(proposal))
    return proposal
