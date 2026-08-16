"""机会发现引擎（opportunity discovery）：五看洞察 → 市场机会池（Opportunity Pool）

职责边界：纯函数，输入 brief + 洞察 bundle，输出「候选机会池」+ 过程日志；
不展开机会卡（那是 opportunity_engine 的职责），不修改 plan、不做状态推进。

数据纪律：
- 机会池是「五看洞察 → 产品决策」的中间产物，挂在 InsightBundle 顶层；
  洞察驾驶舱 Block5 与机会生成必须消费同一份 pool，禁止二次生成。
- LLM 优先：strict JSON + pydantic 校验 + 1 次重试（沿用 insight_resolver 纪律）。
- fallback = signal-ranking：趋势强度 × 用户需求 × 竞品空位 打分排序，
  无品类硬编码；过程日志如实标注降级，Demo 可展示鲁棒决策能力。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.planning.repository import _snake_keys
from app.schemas.planning import OpportunityPoolItem

# ── LLM prompt ────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """你是名创优品资深商品经理，负责「市场机会发现」（Opportunity Discovery）。
基于输入的五看洞察信号（趋势/用户/竞品/内部资产），收敛出 3-4 个值得进入的市场机会方向，按推荐优先级排序。

输出纪律：
1. 只输出一个 JSON 对象，不要输出任何其他文字、不要用代码围栏。
2. title 必须是「具体的产品方向」（如 复古桌面风扇、户外便携风扇、静音办公风扇），
   禁止输出产品策略分类词（如 智能风扇、IP风扇、功能风扇 这类空泛标签）。
3. opportunityType 表示「机会来源类型」（市场为什么存在这个机会），不是产品形态：
   - design_value：设计价值（颜值/设计语言升级带来的溢价空间）
   - scenario_growth：场景增长（新场景/场景扩容带来的增量）
   - pain_point_solution：痛点解决（未被满足的高频痛点）
   - emotional_consumption：情绪消费（情绪价值/社交货币驱动）
   - technology_upgrade：技术升级（新技术下放带来的体验跃迁）
4. evidenceSource 的 fact 必须来自输入信号中的真实数据，禁止编造数字。
5. reasoning 是推理链：signal（市场信号）→ interpretation（解读）→ opportunity（机会含义）。
6. confidence 0-100：信号越强、多方证据越交叉，置信度越高；单信号支撑的方向不超过 70。

JSON 结构：
{
  "pool": [
    {
      "id": "kebab-case 唯一标识",
      "title": "具体产品方向",
      "rank": 1,
      "confidence": 85,
      "opportunityType": "design_value",
      "summary": "一句话市场判断",
      "evidenceSource": [{"source": "trend|consumer|competitor|internal", "fact": "输入信号中的事实"}],
      "reasoning": [{"signal": "...", "interpretation": "...", "opportunity": "..."}]
    }
  ]
}
pool 3-4 个，rank 从 1 开始连续编号；每个 evidenceSource 2-3 条、reasoning 1-2 条。"""

# ── signal-ranking fallback ───────────────────────────────────

# 机会来源类型的通用语义关键词（品类无关，不是品类硬编码）
_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("technology_upgrade", ["智能", "AI", "ai", "自动", "感应", "物联", "APP", "app", "数显", "语音", "制冷", "半导体"]),
    ("design_value", ["复古", "颜值", "ins", "设计", "配色", "造型", "可爱", "联名", "外观", "好看"]),
    ("emotional_consumption", ["治愈", "解压", "情绪", "梗", "社交", "礼物", "仪式", "陪伴", "体面"]),
    ("scenario_growth", ["露营", "户外", "办公", "桌面", "通勤", "宿舍", "旅行", "车载", "演唱会", "睡眠", "地铁"]),
]

_SCENE_VALUE_BONUS = 20   # 场景分布 value（0-100）按此系数折算进打分
_PAIN_COUNT_BONUS = 15    # 痛点频次系数
_GAP_BONUS = 10           # 竞品空白区已定位的加成


def _parse_heat(metric: str) -> float:
    """从 metric 文本解析趋势强度：量级（万+/千+）× 态势（high/rising）系数"""
    if not metric:
        return 10.0
    score = 10.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", metric)
    if m:
        wan = float(m.group(1))
        score = max(score, min(100.0, 20 + wan / 25))  # 1000万+ ≈ 60，2000万+ ≈ 100
    elif re.search(r"\d+\s*千", metric):
        score = max(score, 25.0)
    if "high" in metric:
        score *= 1.3
    elif "rising" in metric:
        score *= 1.15
    return score


def _match_type(text: str) -> str | None:
    """按通用语义关键词匹配机会来源类型，未命中返回 None（品类无关）"""
    for otype, keywords in _TYPE_KEYWORDS:
        if any(k in text for k in keywords):
            return otype
    return None


# 机会方向名的价值修饰词（品类无关）：让标题读作「机会方向」而非「品类标签」
_TYPE_TITLE_PREFIX = {
    "design_value": "高颜值",
    "emotional_consumption": "治愈系",
    "technology_upgrade": "智能",
}


def _opportunity_title(core: str, otype: str, matched: bool, category: str) -> str:
    """信号词 → 机会方向名：场景/价值/痛点 + 产品形态（如 通勤场景风扇、风感优化风扇）

    matched=False 表示类型来自分支默认（功能型趋势信号），用「趋势款」保留机会语义。
    """
    if otype == "scenario_growth":
        return f"{core}场景{category}"
    if otype == "pain_point_solution":
        return f"{core}优化{category}"
    if not matched:
        return f"{core}趋势款{category}"
    prefix = _TYPE_TITLE_PREFIX.get(otype, "")
    if prefix and prefix in core:
        prefix = ""
    return f"{prefix}{core}{category}" if prefix else f"{core}{category}"


def _clean(text: str, limit: int = 12) -> str:
    """清洗信号文本为方向名片段：去 #、去「用户痛点-」前缀、截断"""
    t = re.sub(r"^#+", "", text or "")
    t = re.sub(r"^用户痛点[-—]?", "", t)
    return t.strip()[:limit]


def _fallback_pool(category: str, bundle: dict) -> list[dict[str, Any]]:
    """signal-ranking 降级：趋势强度 × 用户需求 × 竞品空位 打分排序生成候选池

    候选锚点来自 bundle 真实信号（趋势信号/场景分布/痛点频次），
    不做品类硬编码；信号稀疏的品类产出自然变少、置信度自然变低。
    """
    tr = bundle.get("trendRadar", {})
    cv = bundle.get("consumerVoice", {})
    cm = bundle.get("competitiveMap", {})

    signals = tr.get("signals", [])
    scenes = cv.get("scenes", [])
    pains = cv.get("painPoints", [])
    gap = cm.get("gapZone") or {}
    gap_label = gap.get("label", "") if isinstance(gap, dict) else str(gap)
    has_gap = bool(gap_label)

    candidates: list[dict[str, Any]] = []

    # ① 场景锚点：场景分布是「在哪用」的最直接信号
    for sc in scenes:
        name = sc.get("name", "")
        if not name:
            continue
        value = sc.get("value", 0) or 0
        score = value / 100 * 60 + (_GAP_BONUS if has_gap else 0)
        matched = _match_type(name)
        otype = matched or "scenario_growth"
        candidates.append({
            "anchor": name,
            "title": _opportunity_title(_clean(name.split('/')[0]), otype, matched is not None, category),
            "score": score, "type": otype,
            "fact": f"使用场景分布：{name}（占比 {value}%）",
        })

    # ② 趋势锚点：热度信号最强的方向
    for sig in signals:
        name = sig.get("name", "")
        if not name:
            continue
        heat = _parse_heat(sig.get("metric", ""))
        score = heat + (_GAP_BONUS if has_gap else 0)
        matched = _match_type(name)
        otype = matched or "design_value"
        candidates.append({
            "anchor": name,
            "title": _opportunity_title(_clean(name), otype, matched is not None, category),
            "score": score, "type": otype,
            "fact": f"趋势信号：{name}（{sig.get('metric', '')}，{sig.get('period', '')}）",
        })

    # ③ 痛点锚点：高频痛点是「未满足需求」的信号
    for pain in pains:
        text = pain.get("text", "")
        if not text:
            continue
        count = pain.get("count", 0) or 0
        score = count * _PAIN_COUNT_BONUS + 15 + (_GAP_BONUS if has_gap else 0)
        candidates.append({
            "anchor": text,
            "title": _opportunity_title(_clean(text), "pain_point_solution", True, category),
            "score": score, "type": "pain_point_solution",
            "fact": f"用户痛点：{_clean(text, 20)}（{count} 条）",
        })

    if not candidates:
        return []

    # 去重（同类型同锚点合并）→ 打分排序 → 取 Top4
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in sorted(candidates, key=lambda x: -x["score"]):
        key = c["title"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    top = unique[:4]

    top_score = top[0]["score"] if top else 1
    pool: list[dict[str, Any]] = []
    for i, c in enumerate(top):
        confidence = int(55 + 30 * (c["score"] / top_score)) if top_score else 55
        evidence = [{"source": "consumer" if "痛点" in c["fact"] or "场景" in c["fact"] else "trend",
                     "fact": c["fact"]}]
        if has_gap:
            evidence.append({"source": "competitor", "fact": f"竞品空白区：{gap_label[:50]}"})
        pool.append({
            "id": f"opp-{i + 1}",
            "title": c["title"],
            "rank": i + 1,
            "confidence": min(confidence, 88),
            "opportunityType": c["type"],
            "summary": f"基于「{_clean(c['anchor'], 16)}」信号的市场机会（信号排序推导）",
            "evidenceSource": evidence,
            "reasoning": [{
                "signal": c["fact"],
                "interpretation": "该信号在采集数据中强度靠前，代表真实存在的市场需求",
                "opportunity": f"围绕该方向做{category}存在进入空间",
            }],
        })
    return pool


# ── LLM 路径 ──────────────────────────────────────────────────

def _parse_llm_json(raw: str) -> dict | None:
    """解析 LLM 输出为 dict：容错去代码围栏，非 JSON 返回 None"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _serialize_signals(bundle: dict, brief: dict, category: str) -> str:
    """把五看 bundle 压缩成 LLM 可读的信号摘要（只列真实字段，不加工）"""
    tr = bundle.get("trendRadar", {})
    cv = bundle.get("consumerVoice", {})
    cm = bundle.get("competitiveMap", {})
    ib = bundle.get("insightBase", {})

    lines = [
        f"【品类】{category}",
        f"【目标人群】{brief.get('audience', '') or '大众'}",
        f"【零售价格带】{brief.get('price_range', brief.get('priceRange', ''))}",
        f"【企划主题】{brief.get('theme', '')}",
        "",
        "【趋势信号】",
    ]
    for s in tr.get("signals", [])[:8]:
        lines.append(f"- {s.get('name', '')}（{s.get('metric', '')}，{s.get('period', '')}）")
    if tr.get("hotWords"):
        lines.append(f"【热词】{'、'.join(tr['hotWords'][:10])}")
    lines.append("【用户痛点】")
    for p in cv.get("painPoints", [])[:6]:
        lines.append(f"- {p.get('text', '')}（{p.get('count', 0)} 条）")
    lines.append("【使用场景】")
    for sc in cv.get("scenes", [])[:6]:
        lines.append(f"- {sc.get('name', '')}（占比 {sc.get('value', 0)}%）")
    if cv.get("summary"):
        lines.append(f"【用户洞察摘要】{cv['summary']}")
    gap = cm.get("gapZone") or {}
    gap_label = gap.get("label", "") if isinstance(gap, dict) else str(gap)
    if gap_label:
        lines.append(f"【竞品空白区】{gap_label}")
    if cm.get("priceBands"):
        bands = " / ".join(b.get("band", "") for b in cm["priceBands"][:5])
        lines.append(f"【竞品价格带分布】{bands}")
    if ib.get("ipPool"):
        ips = "、".join(ip.get("name", "") for ip in ib["ipPool"][:4])
        lines.append(f"【名创 IP 资产】{ips}")
    return "\n".join(lines)


def _llm_pool(category: str, bundle: dict, brief: dict) -> tuple[list[dict[str, Any]] | None, str]:
    """LLM 生成候选机会池：strict JSON + schema 校验 + 1 次重试

    Returns:
        (pool, error)：成功时 pool 为 camelCase dict 列表；失败时 pool=None，error 为原因
    """
    from app.engine import llm

    user_prompt = (
        _serialize_signals(bundle, brief, category)
        + f"\n\n请输出「{category}」品类的市场机会池 JSON。"
    )

    last_error = "LLM 未返回内容"
    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else (
            f"{user_prompt}\n\n上次输出未通过契约校验：{last_error}。请严格按结构重新输出。"
        )
        raw = llm.complete(
            system_prompt=_LLM_SYSTEM_PROMPT,
            user_prompt=prompt,
            temperature=0.4,
            max_tokens=4000,
        )
        if not raw:
            last_error = "LLM 未配置或调用失败"
            continue
        data = _parse_llm_json(raw)
        if data is None:
            last_error = "输出不是合法 JSON"
            continue
        items = data.get("pool")
        if not isinstance(items, list) or not items:
            last_error = "缺少 pool 数组"
            continue
        try:
            validated = [OpportunityPoolItem.model_validate(_snake_keys(it)) for it in items]
        except ValueError as e:
            last_error = f"schema 校验失败：{str(e)[:200]}"
            continue
        if len(validated) < 3:
            last_error = "有效机会方向不足 3 个"
            continue
        # 重排 rank 保证从 1 连续；转回 camelCase dict 供持久化与前端消费
        pool = []
        for i, item in enumerate(validated[:4]):
            d = item.model_dump()
            d["rank"] = i + 1
            pool.append(_camel_keys(d))
        return pool, ""

    return None, last_error


def _camel_keys(obj: Any) -> Any:
    """dict/list 递归转 camelCase（与 bundle 存储约定一致）"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            parts = k.split("_")
            camel = parts[0] + "".join(p.title() for p in parts[1:])
            out[camel] = _camel_keys(v)
        return out
    if isinstance(obj, list):
        return [_camel_keys(x) for x in obj]
    return obj


# ── 入口 ──────────────────────────────────────────────────────

def build_opportunity_pool(category: str, bundle: dict, brief: dict) -> tuple[list[dict[str, Any]], list[str]]:
    """生成市场机会池：LLM 优先，失败走 signal-ranking 降级

    Returns:
        (pool, process_log)：pool 为 camelCase dict 列表（挂 bundle.opportunityPool），
        process_log 如实记录 LLM / fallback 路径。
    """
    pool, error = _llm_pool(category, bundle, brief)
    if pool:
        log = [
            "AI Discovery：综合五看洞察信号，LLM 推理生成候选市场机会池",
            f"输出候选机会 {len(pool)} 个，按推荐优先级排序："
            + " / ".join(f"#{p['rank']} {p['title']}（置信度 {p['confidence']}%）" for p in pool),
        ]
        return pool, log

    # ── signal-ranking fallback ──
    pool = _fallback_pool(category, bundle)
    tr = bundle.get("trendRadar", {})
    cv = bundle.get("consumerVoice", {})
    cm = bundle.get("competitiveMap", {})
    gap = cm.get("gapZone") or {}
    gap_label = gap.get("label", "") if isinstance(gap, dict) else str(gap)
    log = [
        f"AI Discovery：LLM 生成失败（{error}）",
        "Fallback：基于 趋势强度 × 用户需求 × 竞品空位 的信号排序，自动生成候选机会池",
        f"信号提取：趋势信号 ×{len(tr.get('signals', []))} / 用户痛点 ×{len(cv.get('painPoints', []))}"
        f" / 使用场景 ×{len(cv.get('scenes', []))}，竞品空白{'已定位' if gap_label else '未定位'}",
        f"输出候选机会 {len(pool)} 个（按综合信号强度排序，无品类硬编码）",
    ]
    return pool, log
