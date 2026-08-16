"""
多维表格归档同步 — 企划卡归档后自动写入飞书多维表格（企划资产库）

设计文档：docs/guides/feishu-ai-guide.md §2.3
- 事件驱动：归档成功后由 API 层后台任务触发，不是定时任务
- 字段映射以 schemas/planning.py 真实契约为准：
  brief 为 snake_case（PlanBrief.model_dump），plan_card 为 camelCase（前端契约）
- fail-soft：同步失败不影响归档本身，只打 error log
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests

from .auth import FeishuAuth
from .config import FeishuConfig

logger = logging.getLogger(__name__)

# 飞书 API 正常响应 <2s；10s 无响应视为对端挂死，放弃本次同步（fail-soft 兜底）
_REQ_TIMEOUT = 10

# ── 表结构定义（字段名, 飞书字段类型）────────────────────────
# 飞书字段类型：1=多行文本, 5=日期
FIELD_SPEC: list[tuple[str, int]] = [
    ("plan_id", 1),         # 主列：任务唯一标识（pipeline 任务字典）
    ("theme", 1),           # PlanBrief.theme
    ("category", 1),        # PlanBrief.category
    ("market", 1),          # PlanBrief.market
    ("price_range", 1),     # PlanBrief.price_range → "39-99"
    ("ip_strategy", 1),     # PlanBrief.ip_strategy → "、".join
    ("launch_window", 1),   # PlanBrief.launch_window
    ("concept", 1),         # PlanCard.concept
    ("pricing_price", 1),   # PlanCard.pricing.price（如 "59 元"）
    ("pricing_reason", 1),  # PlanCard.pricing.reason
    ("schedule", 1),        # PlanCard.schedule → 多行文本 "time action"
    ("status", 1),          # pipeline 任务字典，固定 archived
    ("archived_at", 5),     # pipeline 任务字典，ISO → 毫秒时间戳
    ("source_plan_id", 1),  # PlanCard.source_plan_id（复用来源，空为原创）
    ("过会纪要", 1),         # 智能纪要阶段回写，归档时留空
]


def _iso_to_ms(iso_str: str) -> int | None:
    """ISO8601 字符串 → 毫秒时间戳（飞书日期字段要求）"""
    try:
        return int(datetime.fromisoformat(iso_str).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def build_fields(plan: dict[str, Any]) -> dict[str, Any]:
    """把归档任务（pipeline plan dict）映射为多维表格记录字段

    plan 结构：plan_id / brief(snake) / plan_card(camel) / status / archived_at
    """
    brief = plan.get("brief") or {}
    card = plan.get("plan_card") or {}
    pricing = card.get("pricing") or {}
    schedule = card.get("schedule") or []

    price_range = brief.get("price_range") or []
    price_text = "-".join(str(int(p)) for p in price_range) if price_range else ""
    schedule_text = "\n".join(
        f"{item.get('time', '')} {item.get('action', '')}".strip()
        for item in schedule
    )

    fields: dict[str, Any] = {
        "plan_id": plan.get("plan_id", ""),
        "theme": brief.get("theme", ""),
        "category": brief.get("category", ""),
        "market": brief.get("market", ""),
        "price_range": price_text,
        "ip_strategy": "、".join(brief.get("ip_strategy") or []),
        "launch_window": brief.get("launch_window", ""),
        "concept": card.get("concept", ""),
        "pricing_price": pricing.get("price", ""),
        "pricing_reason": pricing.get("reason", ""),
        "schedule": schedule_text,
        "status": plan.get("status", ""),
        "source_plan_id": card.get("sourcePlanId", ""),
    }
    archived_ms = _iso_to_ms(plan.get("archived_at", ""))
    if archived_ms is not None:
        fields["archived_at"] = archived_ms
    return fields


class BitableSync:
    """多维表格同步器：字段自检 + 记录写入"""

    def __init__(self, auth: FeishuAuth, app_token: str, table_id: str):
        self.auth = auth
        self.app_token = app_token
        self.table_id = table_id
        self.base = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps"
            f"/{app_token}/tables/{table_id}"
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth.get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _list_fields(self) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{self.base}/fields", headers=self._headers(), timeout=_REQ_TIMEOUT
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取多维表格字段失败: {data}")
        return data["data"]["items"]

    def ensure_fields(self) -> None:
        """字段自检：缺失的字段用 API 创建（幂等，重复执行无副作用）

        特殊处理：多维表格主列不可删除/新增，若 plan_id 不存在，
        把默认主列（第一个字段）重命名为 plan_id。
        """
        existing = self._list_fields()
        names = {f["field_name"] for f in existing}

        if "plan_id" not in names and existing:
            primary = existing[0]
            resp = requests.put(
                f"{self.base}/fields/{primary['field_id']}",
                headers=self._headers(),
                # 飞书更新字段接口要求同时携带 type，否则报 field validation failed
                json={"field_name": "plan_id", "type": primary["type"]},
                timeout=_REQ_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"重命名主列为 plan_id 失败: {data}")
            names.add("plan_id")

        for name, ftype in FIELD_SPEC:
            if name in names:
                continue
            payload: dict[str, Any] = {"field_name": name, "type": ftype}
            if ftype == 5:
                payload["property"] = {"date_formatter": "yyyy/MM/dd HH:mm"}
            resp = requests.post(
                f"{self.base}/fields", headers=self._headers(), json=payload,
                timeout=_REQ_TIMEOUT,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"创建字段 {name} 失败: {data}")

    def create_record(self, plan: dict[str, Any]) -> dict[str, Any]:
        """把归档任务写入多维表格，新增一行"""
        resp = requests.post(
            f"{self.base}/records",
            headers=self._headers(),
            json={"fields": build_fields(plan)},
            timeout=_REQ_TIMEOUT,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"写入多维表格记录失败: {data}")
        return data["data"]["record"]


_syncer: BitableSync | None = None


def _get_syncer() -> BitableSync | None:
    """懒加载同步器；未配置 app_token/table_id 或应用凭证时返回 None"""
    global _syncer
    if _syncer is not None:
        return _syncer
    config = FeishuConfig.from_env()
    if not (config.app_id and config.app_secret):
        logger.warning("飞书凭证未配置，跳过多维表格同步")
        return None
    if not (config.bitable_app_token and config.bitable_table_id):
        logger.warning("多维表格 app_token/table_id 未配置，跳过同步")
        return None
    _syncer = BitableSync(
        FeishuAuth(config), config.bitable_app_token, config.bitable_table_id
    )
    return _syncer


def sync_plan_to_bitable(plan: dict[str, Any]) -> bool:
    """归档钩子入口：字段自检（首次）+ 写入一行。失败只记日志，不抛异常"""
    try:
        syncer = _get_syncer()
        if syncer is None:
            return False
        syncer.ensure_fields()
        record = syncer.create_record(plan)
        logger.info("企划 %s 已同步到多维表格，record_id=%s",
                    plan.get("plan_id"), record.get("record_id"))
        return True
    except Exception:
        logger.exception("多维表格同步失败（归档本身不受影响），plan_id=%s",
                         plan.get("plan_id"))
        return False
