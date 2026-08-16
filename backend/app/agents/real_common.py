"""真 LLM Agent 公共件 — 四委员（user/ip/business/gtm）共用

三件事：
  1. parse_llm_json：容错解析 LLM 输出（剥围栏、截取首个 JSON 对象）
  2. provider_enabled：注册表开关——分开关优先，AGENT_PROVIDER 总开关兜底
  3. min_confidence：置信度沿链路衰减取最低（自 mock_agents 迁入，单一来源）

设计纪律（与 trend_agent/creative_agent 一致）：
- 数字与溯源字段一律代码构建，LLM 只写判断性文本
- 任何环节失败返回 None → 调用方回退对应 MockAgent，会议不阻塞
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from app.schemas import Confidence


def parse_llm_json(raw: str) -> dict[str, Any] | None:
    """容错解析：剥 ```json 围栏、截取首个 { 到 }；失败返回 None"""
    text = re.sub(r"```(?:json)?|```", "", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def provider_enabled(env_name: str) -> bool:
    """真 Agent 开关：分开关（如 USER_AGENT_PROVIDER）优先，
    未设时看总开关 AGENT_PROVIDER；值 "real" 启用，默认/未知值走 Mock。
    """
    val = (os.getenv(env_name) or os.getenv("AGENT_PROVIDER", "mock")).strip().lower()
    return val == "real"


def min_confidence(values: list[str]) -> Confidence:
    """置信度取最低值——沿链路衰减，不放大（与 mock_agents._min_confidence 同源）"""
    order = [Confidence.UNKNOWN, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]
    if not values:
        return Confidence.UNKNOWN
    return min((Confidence(v) for v in values), key=order.index)


def fuzzy_get(mapping: dict[str, Any], name: str) -> Any | None:
    """按方案名取 LLM 输出条目：先精确，再归一化模糊匹配。

    LLM 抄方案名时偶尔会丢/改标点（"挂脖/手持" → "挂脖手持"），
    归一化（去标点空白）后双向包含即算命中；都没有返回 None。
    """
    if not name:
        return None
    hit = mapping.get(name)
    if hit is not None:
        return hit
    norm = re.sub(r"[\s/·\-—_（）()【】\[\]「」:：,，。.]", "", name)
    if not norm:
        return None
    for k, v in mapping.items():
        nk = re.sub(r"[\s/·\-—_（）()【】\[\]「」:：,，。.]", "", k)
        if nk and (norm in nk or nk in norm):
            return v
    return None
