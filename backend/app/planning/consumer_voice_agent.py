"""Consumer Voice Agent — 用户决策画像 + 痛点归因链

定位：把采集到的「消费者原声」二次推理成服务机会池的决策结构：
   用户决策画像（谁/什么场景/什么任务/为什么买/看什么下单）
   + 痛点归因链（原声 → 需求归因 → 机会方向，supportsOpportunityIds 引用机会池 id）

数据纪律（与 insight_enrichment / opportunity_discovery 一致）：
- LLM 只写判断文本（用户群一句话、四要素短语、需求归因、优先级、机会方向映射），
  引用与数字一律代码构建：painPoint/consumerVoice/evidenceSource 只引用真实采集数据，
  supportsOpportunityIds 只命中真实机会池 id，命中不了就丢弃，不产假数据。
- 无采集数据 / LLM 不可用 / 输出不合契约 → 返回 None，前端不渲染归因链块。
- 不做人口属性画像（年龄/性别/职业），避免 LLM 幻觉。
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas.planning import PainPointChain

_PLATFORM_KW = [
    "小红书", "抖音", "微博", "什么值得买", "B站", "哔哩", "淘宝",
    "知乎", "豆瓣", "Instagram", "巨量算数", "新浪", "天猫", "京东", "微信",
]

# 相似度阈值：LLM 引原声/痛点时允许轻微改写/截断，但过低的匹配（自造词）丢弃
_FUZZY_THRESHOLD = 0.5


def _norm(text: str) -> str:
    """归一化（去标点空白），用于模糊匹配真实引用"""
    return re.sub(r"[\s/·\-—_（）()【】\[\]「」:：,，。.、+%]", "", text or "")


def _fuzzy_index(candidates: list[str], target: str) -> int:
    """在候选列表里找 target 的最匹配下标（字符级相似度）；找不到返回 -1

    用 SequenceMatcher 而非子串包含：LLM 引真实痛点时可能轻微改写或截断，
    相似度 ≥ 阈值才算命中；纯自造词相似度低，被丢弃。
    """
    nt = _norm(target)
    if len(nt) < 2:
        return -1
    best_i, best_ratio = -1, 0.0
    for i, c in enumerate(candidates):
        nc = _norm(c)
        if not nc:
            continue
        ratio = SequenceMatcher(None, nt, nc).ratio()
        if ratio > best_ratio:
            best_i, best_ratio = i, ratio
    return best_i if best_ratio >= _FUZZY_THRESHOLD else -1


def _fuzzy_quote_index(quotes: list[str], target: str) -> int:
    """在原声列表里找 target 的下标（归一化子串包含）；找不到返回 -1

    原声要求「原样引用」，LLM 只会截断不改写，故用子串包含（截断片段是全文子串），
    而非相似度（相似度会因长短悬殊被压到阈值下）。
    """
    nt = _norm(target)
    if len(nt) < 4:
        return -1
    for i, q in enumerate(quotes):
        nq = _norm(q)
        if nq and nt in nq:
            return i
    return -1


def _extract_platform(source: str) -> str:
    """从原声 source / 痛点文本提取平台名（真实，命中不了返回空，前端显示「社媒」兜底）"""
    if not source:
        return ""
    for kw in _PLATFORM_KW:
        if kw in source:
            return kw
    return ""


def _clean_pain(text: str, limit: int = 24) -> str:
    """清洗痛点文本为短标签（去前缀、截断）"""
    t = re.sub(r"^用户痛点[-—]?", "", text or "")
    t = re.split(r"[,，:：/（(]", t)[0].strip()
    return t[:limit]


def _pain_voice(full: str) -> str:
    """从痛点文本里取「原声部分」：采集格式常为 短标签：证据+原声（如雨伞）

    雨伞采集把原声嵌在痛点文本里（'雨伞不结实…吐槽合集：小红书+微博大量吐槽…'），
    而 quotes 字段存的是趋势/竞品数据；小风扇则相反。回退时取冒号后的真实原声。
    """
    parts = re.split(r"[：:]", full or "", maxsplit=1)
    return parts[1].strip() if len(parts) > 1 and parts[1].strip() else (full or "")


# ── LLM prompt ────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """你是名创优品消费者洞察 Agent。基于采集到的消费者原声，输出「用户决策画像 + 痛点归因链」，
让机会池的每个方向都有「为什么用户会买」的证据。

输出纪律：
1. 只输出一个 JSON 对象，不要任何解释文字、不要代码围栏。
2. 不做人口属性画像（年龄/性别/职业）；userProfile 只写决策相关四要素。
3. painPoint 必须从下方【痛点候选】里选（原样引用，不要自造新痛点）；
   consumerVoice 必须从下方【原声候选】里选（原样引用，不要改写原声）；
   supportsOpportunityIds 必须从下方【机会方向】的 id 里选，不要自造 id。
4. priority 1-5：越值得优先解决的痛点分越高；只列真正值得进机会池的痛点（3-5 条）。
5. demandInterpretation 是需求归因：这个痛点背后用户真正想要什么。

输出 JSON 结构：
{
  "userProfile": {
    "userSegment": "用户群一句话",
    "usageScenario": ["核心场景短语"],
    "userTask": ["使用任务短语"],
    "purchaseMotivation": ["购买动机短语"],
    "decisionFactors": ["决策因素短语"]
  },
  "chains": [
    {
      "painPoint": "引用的痛点",
      "priority": 5,
      "consumerVoice": ["引用的原声"],
      "demandInterpretation": "需求归因",
      "supportsOpportunityIds": ["机会方向 id"]
    }
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


def _serialize(bundle: dict, category: str, brief: dict) -> str:
    """把痛点/原声/机会池压缩成 LLM 可读的候选清单（只列真实字段）"""
    cv = bundle.get("consumerVoice", {})
    pool = bundle.get("opportunityPool", [])

    lines = [f"【品类】{category}", f"【目标人群】{brief.get('audience', '') or '大众'}"]
    lines.append("【痛点候选（painPoint 引用冒号前的短标签）】")
    for p in cv.get("painPoints", [])[:8]:
        full = p.get("text", "")
        lines.append(f"- {_clean_pain(full)}｜{full[:80]}")
    lines.append("【原声候选（原样引用，不要改写）】")
    for q in cv.get("quotes", [])[:8]:
        lines.append(f"- {q.get('text', '')}")
    lines.append("【机会方向（id｜title）】")
    for o in pool[:6]:
        lines.append(f"- {o.get('id', '')}｜{o.get('title', '')}")
    return "\n".join(lines)


def _build_evidence(pain_text: str, voices: list[str], sources: list[str]) -> dict[str, Any]:
    """证据：平台从痛点全文 + 原声 source 提取，关键词从痛点提取，count = 真实原声条数"""
    platform = ""
    for src in [pain_text] + list(sources):
        p = _extract_platform(src)
        if p:
            platform = p
            break
    return {
        "platform": platform,
        "keywords": [k for k in re.split(r"[/,，、]", _clean_pain(pain_text, 24)) if k][:4],
        "count": len(voices) or None,
    }


def build_consumer_voice_chains(category: str, bundle: dict, brief: dict) -> dict[str, Any] | None:
    """生成决策画像 + 痛点归因链：LLM 写判断，代码校验引用；失败返回 None

    Returns:
        {"userProfile": {...}, "painPointChains": [...]} camelCase；失败 None
    """
    from app.engine import llm

    cv = bundle.get("consumerVoice", {})
    pains = [p.get("text", "") for p in cv.get("painPoints", [])]
    pain_labels = [_clean_pain(t) for t in pains]
    quotes = [q.get("text", "") for q in cv.get("quotes", [])]
    quote_sources = [q.get("source", "") for q in cv.get("quotes", [])]
    pool = bundle.get("opportunityPool", [])
    pool_ids = [o.get("id", "") for o in pool]
    pool_by_id = {o.get("id", ""): o for o in pool}

    if not pains:
        return None

    prompt = _serialize(bundle, category, brief)
    data: dict | None = None
    for _ in range(2):  # 瞬时限流/输出不合契约重试一次（与 opportunity_discovery 一致）
        raw = llm.complete(_LLM_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=4000)
        if raw:
            data = _parse_llm_json(raw)
            if data:
                break
    if not data:
        return None

    # userProfile：LLM 写短语，代码只做兜底清空
    up = data.get("userProfile") or {}
    user_profile = {
        "userSegment": str(up.get("userSegment", "")),
        "usageScenario": [str(x) for x in up.get("usageScenario", []) if x][:6],
        "userTask": [str(x) for x in up.get("userTask", []) if x][:6],
        "purchaseMotivation": [str(x) for x in up.get("purchaseMotivation", []) if x][:6],
        "decisionFactors": [str(x) for x in up.get("decisionFactors", []) if x][:6],
    }

    # 归因链：引用全部代码校验，命中不了就丢弃，不产假数据
    chains: list[dict[str, Any]] = []
    for c in data.get("chains", []):
        pain_idx = _fuzzy_index(pain_labels, str(c.get("painPoint", "")))
        if pain_idx < 0:
            continue
        voices: list[str] = []
        quote_matched = False
        for v in c.get("consumerVoice", []):
            qi = _fuzzy_quote_index(quotes, str(v))
            if qi >= 0:
                voices.append(quotes[qi])
                quote_matched = True
        if not voices:
            # 无匹配 quotes → 回退到痛点文本里的原声（采集侧把原声嵌在痛点里，如雨伞）
            voices = [_pain_voice(pains[pain_idx])]
        sup_ids = [
            pid for pid in c.get("supportsOpportunityIds", [])
            if pid in pool_ids
        ]
        evidence = _build_evidence(pains[pain_idx], voices, quote_sources)
        if not quote_matched:
            evidence["count"] = None  # 回退的原声无真实条数，不编造
        chains.append({
            "priority": int(c.get("priority", 0) or 0),
            "painPoint": pain_labels[pain_idx],
            "consumerVoice": voices,
            "demandInterpretation": str(c.get("demandInterpretation", "")),
            "supportsOpportunityIds": sup_ids,
            "evidenceSource": evidence,
        })

    if not chains:
        return None

    chains.sort(key=lambda x: -x["priority"])
    # 契约校验（纯结构，不含数字严格校验）
    for ch in chains:
        PainPointChain.model_validate(ch)
    return {"userProfile": user_profile, "painPointChains": chains[:5]}
