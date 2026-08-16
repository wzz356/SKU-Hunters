"""五看洞察解析器（insight resolver）：按品类解析洞察——真实社媒证据优先，LLM 生成兜底

职责边界：只负责「洞察数据从哪来」（真实证据 vs LLM 生成的选择与组装），
不负责机会生成、企划卡等下游业务。

数据纪律：
- 有社媒采集数据的品类 → 真实证据，dataSource="crawled"
- 无采集数据的品类 → LLM 按品类现场生成，dataSource="llm"，process_log 如实标注
- LLM 未配置/输出连续不合契约 → 抛 LLMGenerationError，不产任何假数据
- 禁止回退到其他品类的冻结数据（无小风扇 fallback）
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from app.planning.repository import _snake_keys
from app.schemas.planning import InsightBundle


class LLMGenerationError(Exception):
    """LLM 生成失败：未配置 Key、调用失败或输出连续不合契约（不产假数据，直接报错）"""


def _resolve_insight_bundle(category: str, brief: dict | None = None) -> dict[str, Any]:
    """按品类取五看洞察：真实社媒证据优先；无采集数据走 LLM 生成

    Returns:
        五看洞察 bundle（camelCase），顶层带 dataSource 标记（crawled | llm）

    Raises:
        LLMGenerationError: 无采集数据且 LLM 不可用/输出不合契约
    """
    brief = brief or {}
    if brief.get("mode") == "live":
        # live 任务：只允许 feishu，失败显式报错；拒绝静默回退 fixture/crawled/llm
        provider = os.getenv("BASE_PROVIDER_MODE", "disabled").strip().lower()
        if provider != "feishu":
            raise LLMGenerationError(
                f"live 任务「{category}」要求 feishu 数据源，但 BASE_PROVIDER_MODE={provider}，拒绝回退 fixture/crawled/llm"
            )
        from app.planning.live_insights import build_live_insight_bundle

        try:
            return build_live_insight_bundle(category, brief)
        except Exception as exc:
            raise LLMGenerationError(f"品类「{category}」的飞书实时洞察不可用：{exc}") from exc

    if brief.get("mode") == "fixture":
        # fixture 任务：显式返回演示数据（冻结 fixtures 五看洞察），标 dataSource=fixture
        # 禁止 mode=fixture 却携带 dataSource=crawled/llm 的混合状态
        from app.planning.fixtures import (
            COMPETITIVE_MAP,
            CONSUMER_VOICE,
            INSIGHT_BASE,
            TREND_GALLERY,
            TREND_RADAR,
        )

        return {
            "trendRadar": {
                **TREND_RADAR,
                "heatCurve": _load_heat_curve(),
                "processLog": ["演示数据（fixture）：冻结 fixtures.py 五看洞察，非真实采集"],
            },
            "consumerVoice": CONSUMER_VOICE,
            "competitiveMap": COMPETITIVE_MAP,
            "insightBase": INSIGHT_BASE,
            "trendGallery": TREND_GALLERY,
            "dataSource": "fixture",
        }

    try:
        from app.insights.loaders.social_evidence import SocialEvidenceLoader
        bundle = SocialEvidenceLoader().get_insight_bundle(category)
        # heatCurve 只注入真实快照且限快照所属品类；不匹配留 None（HeatCurve | None 契约允许）
        bundle["trendRadar"]["heatCurve"] = _load_heat_curve(category)
        bundle["dataSource"] = "crawled"
    except FileNotFoundError:
        bundle = _llm_insight_bundle(category, brief or {})
    _attach_enrichment(category, bundle, brief or {})
    return bundle


def _attach_enrichment(category: str, bundle: dict, brief: dict) -> None:
    """洞察增强（五段式驾驶舱）：crawled 与 llm 两条路径统一挂 enrichment

    失败返回 None 时不挂键 → 前端回退基础视图（不产假数据）。
    """
    from app.planning.insight_enrichment import build_enrichment

    enrichment = build_enrichment(category, bundle, brief)
    if enrichment is not None:
        bundle["enrichment"] = enrichment


def _load_heat_curve(category: str = "") -> dict[str, Any] | None:
    """从 Google Trends 冻结快照注入热度曲线（仅快照关键词与品类匹配时注入）

    快照是单品类冻结数据：串品类注入会把快照关键词带进其他品类的趋势图，
    故关键词与品类互不包含时返回 None（HeatCurve | None 契约允许）。
    """
    try:
        # 快照分目录：优先 data/snapshot/，旧路径向后兼容
        base = Path(__file__).resolve().parents[2] / "data"
        path = base / "snapshot" / "google_trends_snapshot.json"
        if not path.is_file():
            path = base / "google_trends_snapshot.json"
        if not path.is_file():
            return None
        snap = json.loads(path.read_text(encoding="utf-8"))
        keywords = [s.get("name", "") for s in snap.get("series", [])]
        if category and not any(k and (k in category or category in k) for k in keywords):
            return None
        return {"weeks": snap["weeks"], "series": snap["series"]}
    except (OSError, ValueError, KeyError):
        return None


# ── LLM 洞察生成（无采集数据品类）─────────────────────────────

_LLM_SYSTEM_PROMPT = """你是 SKU Hunters 新品企划工作室的市场分析 Agent。商品经理会给定一个品类，
你要输出该品类的「五看洞察」。只输出严格 JSON，不要输出任何解释文字、不要使用 markdown 代码围栏。

纪律：
1. 只分析给定品类，禁止套用其他品类（如小风扇）的内容；
2. 内容基于你的知识做合理推断，数值为估计值，不得冒充真实采集统计；
3. 每个模块的 processLog 第一条必须是「数据源：LLM 推理生成（该品类暂无社媒采集数据）」；
4. consumerVoice.quotes 的 source 字段一律填「LLM 推理」，不得伪造真实用户昵称/链接；
5. competitiveMap.products 的 imageUrl 一律填空字符串。

输出 JSON 结构（字段名与类型必须严格一致）：
{
  "trendRadar": {
    "processLog": ["..."],
    "signals": [{"name": "趋势名", "metric": "量化描述", "period": "时间范围", "domains": ["领域"], "opportunity": "机会点"}],
    "heatCurve": {"weeks": ["W1", "..."], "series": [{"name": "序列名", "data": [0.0]}]},
    "hotWords": ["热词"]
  },
  "consumerVoice": {
    "processLog": ["..."],
    "painPoints": [{"text": "痛点", "count": 0}],
    "scenes": [{"name": "场景", "value": 0}],
    "quotes": [{"text": "典型用户声音", "source": "LLM 推理"}],
    "summary": "一句话总结"
  },
  "competitiveMap": {
    "processLog": ["..."],
    "products": [{"name": "代表性竞品", "price": 0.0, "imageUrl": "", "sellingPoint": "卖点", "design": 7.5}],
    "gapZone": {"x": [价格下, 价格上], "y": [设计感下, 设计感上], "label": "机会空白描述"},
    "priceBands": [{"band": "价格带", "pct": 0.0}],
    "sellingPoints": [{"word": "卖点词"}]
  },
  "insightBase": {
    "hitProducts": [{"name": "品类历史爆品", "index": 0, "factors": ["爆品因素"], "note": "备注"}],
    "ipPool": [{"name": "适配IP", "status": "合作中|洽谈中", "heat": "↑|→", "fit": ["适配理由"]}],
    "designLanguage": ["名创设计语言关键词"]
  },
  "trendGallery": {
    "colors": [{"name": "流行色", "hex": "#RRGGBB", "source": "LLM 推理"}],
    "patterns": [{"name": "流行花纹", "source": "LLM 推理", "note": ""}],
    "shapes": [{"name": "流行形态", "source": "LLM 推理", "note": ""}],
    "expressions": [{"name": "表情语言趋势", "emoji": "", "note": ""}]
  }
}

数量要求：signals 3-5 条，painPoints 4-6 条，scenes 4-6 个，quotes 3-5 条，
products 5-8 个（design 评分 0-10），priceBands 4-6 段（pct 总和约 100），
sellingPoints 5-8 个，hitProducts 2-4 个，ipPool 2-4 个，colors/patterns/shapes/expressions 各 3-5 个。"""


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


def _llm_insight_bundle(category: str, brief: dict) -> dict[str, Any]:
    """无采集数据品类：LLM 现场生成五看洞察（schema 校验不过重试 1 次，仍失败抛错）"""
    from app.engine import llm

    user_prompt = (
        f"【品类】{category}\n"
        f"【目标市场】{brief.get('market', '中国大陆')}\n"
        f"【目标人群】{brief.get('audience', '') or '大众'}\n"
        f"【零售价格带】{brief.get('price_range', brief.get('priceRange', ''))}\n"
        f"【企划主题】{brief.get('theme', '')}\n\n"
        f"请输出「{category}」品类的五看洞察 JSON。"
    )

    last_error = "LLM 未返回内容"
    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else (
            f"{user_prompt}\n\n上次输出未通过契约校验：{last_error}。请严格按结构重新输出。"
        )
        raw = llm.complete(_LLM_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=6000)
        if not raw:
            last_error = "LLM 未配置或调用失败"
            continue
        data = _parse_llm_json(raw)
        if data is None:
            last_error = "输出不是合法 JSON"
            continue
        try:
            InsightBundle.model_validate(_snake_keys(data))
        except ValueError as e:
            last_error = f"schema 校验失败：{str(e)[:200]}"
            continue
        data["dataSource"] = "llm"
        return data

    raise LLMGenerationError(f"品类「{category}」无采集数据，LLM 洞察生成失败：{last_error}")
