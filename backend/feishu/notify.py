"""
企划就绪通知 — Aily 发起企划后，pipeline 产出机会卡 → 推送飞书消息卡片

设计文档：docs/guides/feishu-ai-guide.md §2.2 / §4.1
- Aily 插件调用有超时限制（10-30s），API 立即返回，pipeline 在后台跑
- 跑完由后端主动调飞书 API 推卡片（不是 Aily 回调）
- 卡片只放摘要 + 跳转前端（深度交互在前端完成，见分工原则）
- fail-soft：推送失败不影响 pipeline 结果
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .auth import FeishuAuth
from .bot import FeishuBot
from .config import FeishuConfig

logger = logging.getLogger(__name__)


def build_opportunities_card(
    plan: dict[str, Any],
    opportunities: list[dict[str, Any]],
    frontend_base: str,
) -> dict[str, Any]:
    """机会卡就绪通知卡片：三行摘要 + 跳转按钮（卡片样式沿用 v1 模板风格）"""
    brief = plan.get("brief") or {}
    theme = brief.get("theme", "")
    category = brief.get("category", "")

    opp_lines = []
    for i, o in enumerate(opportunities[:3], 1):
        emoji = o.get("emoji", "")
        title = o.get("title") or o.get("direction") or f"方向 {i}"
        pitch = o.get("pitch", "")
        price_band = o.get("priceBand") or o.get("price_band", "")
        band = f"（{price_band}）" if price_band else ""
        opp_lines.append(f"**{i}. {emoji}{title}**{band}\n{pitch}")
    opps_text = "\n\n".join(opp_lines)

    task_url = f"{frontend_base}/tasks/{plan.get('plan_id', '')}"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "✨ 机会卡已生成"},
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**企划主题**：{theme}\n**品类**：{category}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"AI 已产出 {len(opportunities[:3])} 张机会卡，请前往企划工作室选定方向：\n\n{opps_text}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "进入企划工作室"},
                        "type": "primary",
                        "url": task_url,
                    }
                ],
            },
        ],
    }


def build_archive_card(plan: dict[str, Any], frontend_base: str) -> dict[str, Any]:
    """企划案归档卡片：企划卡摘要 + 跳转按钮（归档后推群，宣告产出落地）"""
    brief = plan.get("brief") or {}
    card = plan.get("plan_card") or {}
    pricing = card.get("pricing") or {}
    check = card.get("costCheck") or {}
    schedule = card.get("schedule") or []

    theme = brief.get("theme", "")
    category = brief.get("category", "")
    name = card.get("name", "")
    concept = card.get("concept", "")
    price = pricing.get("price", "")
    reason = pricing.get("reason", "")
    schedule_text = "；".join(
        f"{s.get('time', '')} {s.get('action', '')}".strip() for s in schedule[:3]
    )
    margin = check.get("margin")
    check_text = "✅ 通过" if check.get("passed") else "⚠️ 未通过"
    if margin is not None:
        check_text += f"（毛利率 {margin:.0%}）"

    task_url = f"{frontend_base}/tasks/{plan.get('plan_id', '')}"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📦 企划案已归档"},
            "template": "violet",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{name}**\n{concept}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**企划主题**：{theme}　**品类**：{category}\n"
                        f"**定价**：{price}（{reason}）\n"
                        f"**上新节奏**：{schedule_text}\n"
                        f"**成本校验**：{check_text}"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "已同步至「企划资产库」多维表格，可随时复盘追问。",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看企划案"},
                        "type": "primary",
                        "url": task_url,
                    }
                ],
            },
        ],
    }


def notify_opportunities_ready(
    plan: dict[str, Any], opportunities: list[dict[str, Any]]
) -> bool:
    """推送"机会卡已生成"卡片到配置的飞书群。失败只记日志，不抛异常"""
    try:
        chat_id = os.getenv("FEISHU_NOTIFY_CHAT_ID", "")
        if not chat_id:
            logger.warning("FEISHU_NOTIFY_CHAT_ID 未配置，跳过机会卡推送")
            return False
        config = FeishuConfig.from_env()
        if not (config.app_id and config.app_secret):
            logger.warning("飞书凭证未配置，跳过机会卡推送")
            return False
        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
        bot = FeishuBot(FeishuAuth(config))
        card = build_opportunities_card(plan, opportunities, frontend_base)
        resp = bot.send_card(chat_id, card)
        if resp.get("code") != 0:
            logger.error("机会卡推送失败: %s", resp)
            return False
        logger.info("机会卡已推送，plan_id=%s", plan.get("plan_id"))
        return True
    except Exception:
        logger.exception("机会卡推送异常（pipeline 结果不受影响），plan_id=%s",
                         plan.get("plan_id"))
        return False


def notify_plan_archived(plan: dict[str, Any]) -> bool:
    """归档后推送企划案摘要卡片到通知群。失败只记日志，不抛异常"""
    try:
        chat_id = os.getenv("FEISHU_NOTIFY_CHAT_ID", "")
        if not chat_id:
            logger.warning("FEISHU_NOTIFY_CHAT_ID 未配置，跳过归档推送")
            return False
        config = FeishuConfig.from_env()
        if not (config.app_id and config.app_secret):
            logger.warning("飞书凭证未配置，跳过归档推送")
            return False
        frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
        bot = FeishuBot(FeishuAuth(config))
        resp = bot.send_card(chat_id, build_archive_card(plan, frontend_base))
        if resp.get("code") != 0:
            logger.error("归档卡片推送失败: %s", resp)
            return False
        logger.info("归档卡片已推送，plan_id=%s", plan.get("plan_id"))
        return True
    except Exception:
        logger.exception("归档卡片推送异常（归档本身不受影响），plan_id=%s",
                         plan.get("plan_id"))
        return False
