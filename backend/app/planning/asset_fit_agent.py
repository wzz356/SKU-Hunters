"""Asset Fit Agent — 机会方向 → 商品化适配（IP/设计语言/颜色/材质/包装）

定位：把机会池的每个方向，映射到名创已有的 IP/设计资产，回答「这个商品机会
为什么适合名创来做、怎么表达」。不重新发现机会，不孤立推荐 IP。

数据纪律：
- ip 必须引用 insightBase.ipPool 里的真实名创资产，无则空（不 LLM 自造名创资产）。
- ip_reason 必须回答「为什么这个机会方向和这个 IP 匹配」（人群/色系/叙事/场景契合），
  禁止「IP 热门/知名度高」这类与机会方向无关的理由。
- opportunityId 强绑机会池 id；命中不了丢弃。
- 颜色/材质/包装/设计语言是商品表达建议（LLM 判断文本），设计语言优先从真实
  designLanguage 提取，缺失时 LLM 可建议（商品表达，非名创资产声明）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.planning.consumer_voice_agent import _fuzzy_index
from app.planning.repository import _snake_keys
from app.schemas.planning import AssetFit

_LLM_SYSTEM_PROMPT = """你是名创优品商品企划的「资产适配」Agent。你的任务是把机会池的方向，
映射到名创已有的 IP/设计资产，回答「这个商品机会为什么适合名创做、怎么表达」。

输出纪律：
1. 只输出一个 JSON 对象，不要任何解释文字、不要代码围栏。
2. opportunityId 必须从下方【机会池】的 id 里选，禁止生成机会池里没有的方向。
3. ip 必须从下方【名创 IP 资产】里原样引用（没有就不填 ip）；禁止自造 IP。
4. ipReason 必须解释「这个机会方向和这个 IP 为什么匹配」：
   人群重叠 / 色系契合 / 叙事契合 / 场景契合 等，禁止写「IP 热门 / 知名度高 / 国民度高」。
5. designLanguage 优先从下方【名创设计语言】里选；列表为空时可自行建议一个贴合该方向的设计语言。
6. color/material/packaging/targetConsumer 是商品表达建议，给具体可执行的方向，不写「年轻化/潮流」这类空话。

输出 JSON 结构：
{
  "fits": [
    {
      "opportunityId": "机会池 id",
      "ip": "名创 IP 资产名（可空）",
      "ipReason": "为什么匹配",
      "targetConsumer": "目标消费者",
      "designLanguage": "设计语言",
      "color": "颜色建议",
      "material": "材质建议",
      "packaging": "包装方向"
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


def _serialize(bundle: dict, category: str) -> str:
    pool = bundle.get("opportunityPool", [])
    ib = bundle.get("insightBase", {})
    cv = bundle.get("consumerVoice", {})
    lines = [f"【品类】{category}"]
    lines.append("【机会池（id｜title｜summary）】")
    for o in pool[:6]:
        lines.append(f"- {o.get('id', '')}｜{o.get('title', '')}｜{o.get('summary', '')[:40]}")
    lines.append("【名创 IP 资产（name｜已有证据）】")
    for ip in ib.get("ipPool", [])[:6]:
        lines.append(f"- {ip.get('name', '')}｜{(ip.get('fit') or [''])[0][:50]}")
    lines.append("【名创设计语言】")
    lines.append("、".join(ib.get("designLanguage", [])) or "（空，可自行建议）")
    lines.append("【用户决策因素】")
    lines.append("、".join((cv.get("userProfile") or {}).get("decisionFactors", [])))
    return "\n".join(lines)


def build_asset_fit(category: str, bundle: dict, brief: dict) -> list[dict[str, Any]] | None:
    """生成资产适配：LLM 写判断，代码校验引用；失败返回 None"""
    from app.engine import llm

    pool = bundle.get("opportunityPool", [])
    ib = bundle.get("insightBase", {})
    ip_pool = ib.get("ipPool", [])
    if not pool:
        return None

    pool_ids = [o.get("id", "") for o in pool]
    ip_names = [ip.get("name", "") for ip in ip_pool]

    prompt = _serialize(bundle, category)
    data: dict | None = None
    for _ in range(2):
        raw = llm.complete(_LLM_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=4000)
        if raw:
            data = _parse_llm_json(raw)
            if data:
                break
    if not data:
        return None

    fits: list[dict[str, Any]] = []
    for f in data.get("fits", []):
        oid = str(f.get("opportunityId", ""))
        if oid not in pool_ids:
            continue  # 机会池外的新方向，丢弃
        ip = str(f.get("ip", ""))
        # ip 必须命中真实 ipPool，否则留空（不 LLM 自造名创资产）
        ip_idx = _fuzzy_index(ip_names, ip) if ip else -1
        if ip and ip_idx < 0:
            ip = ""
        fits.append({
            "opportunityId": oid,
            "ip": ip_names[ip_idx] if ip_idx >= 0 else "",
            "ipReason": str(f.get("ipReason", "")) if ip_idx >= 0 else "",
            "targetConsumer": str(f.get("targetConsumer", "")),
            "designLanguage": str(f.get("designLanguage", "")),
            "color": str(f.get("color", "")),
            "material": str(f.get("material", "")),
            "packaging": str(f.get("packaging", "")),
        })

    if not fits:
        return None

    for f in fits:
        AssetFit.model_validate(_snake_keys(f))
    return fits
