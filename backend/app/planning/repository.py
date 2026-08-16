"""任务存储层（repository）：内存 + JSON 文件持久化

职责边界：只负责「任务」的读写与落盘（原子写入、并发安全），
不含业务编排（洞察/机会/企划卡的业务流程在 service.py）。

键名工具（camelCase ↔ snake_case 契约转换）也收敛在此，
供 opportunity_engine / plan_card_builder / service 复用。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.engine.strict_mode import (
    StrictModeError,
    allow_fixture_tasks,
    is_demo_hidden,
    planning_default_mode,
)
from app.schemas.planning import PlanBrief
from app.schemas.planning_api_v2 import PlanSummaryV2

# ── 键名工具（前后端契约转换）────────────────────────────

def _camel_to_snake(name: str) -> str:
    """camelCase → snake_case 键名转换"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _snake_keys(obj: Any) -> Any:
    """递归转换 dict 的全部键 camelCase → snake_case，列表和标量直通"""
    if isinstance(obj, dict):
        return {_camel_to_snake(k): _snake_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_snake_keys(v) for v in obj]
    return obj


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 任务存储（内存 + 原子文件持久化，并发安全）────────────

_PLANS: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

_STATE_DIR = Path(__file__).resolve().parents[2] / "data" / "state"  # backend/data/state/
_STATE_FILE = _STATE_DIR / "plans_state.json"
# 迁移前旧位置（backend/data/plans_state.json），仅供向后兼容读取
_LEGACY_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "plans_state.json"


def _save_state() -> None:
    """将全部任务状态原子落盘（锁内快照 + 唯一临时文件 + rename，避免并发覆盖）"""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_name(f".plans_state.{uuid.uuid4().hex}.tmp")
    with _lock:
        payload = {}
        for pid, p in _PLANS.items():
            payload[pid] = {
                "plan_id": p["plan_id"],
                "brief": p["brief"],
                "mode": p["mode"],
                "created_at": p["created_at"],
                "status": p["status"],
                "selected_opportunity": p.get("selected_opportunity"),
                "plan_card": p.get("plan_card"),
                "product_proposal": p.get("product_proposal"),
                "revise_logs": p.get("revise_logs", []),
                "archived_at": p.get("archived_at"),
                # 链路中间产物：重启后企划卡依赖机会卡、机会/企划卡复用洞察缓存
                "opportunities": p.get("opportunities", []),
                "insights": p.get("insights"),
                "data_context": p.get("data_context"),
            }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(_STATE_FILE)


def _load_state() -> dict[str, dict[str, Any]]:
    """从 JSON 文件恢复任务状态（不存在或损坏则返回空）

    新路径（data/state/）优先，旧路径（data/plans_state.json）向后兼容读取。
    """
    path = _STATE_FILE
    if not path.is_file() and _LEGACY_STATE_FILE.is_file():
        path = _LEGACY_STATE_FILE
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ── 任务 CRUD ────────────────────────────────────────────

def create_plan(brief: dict[str, Any]) -> dict[str, Any]:
    """① 企划约束：冻结人工输入，经 PlanBrief schema 校验后建档"""
    # 先归一化键名（前端/DEMO_BRIEF 是 camelCase，PlanBrief 无别名会静默丢字段）
    validated = PlanBrief.model_validate(_snake_keys(brief))
    plan_id = f"plan_{datetime.now(timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:4]}"
    configured_mode = planning_default_mode()
    requested_mode = str(brief.get("mode") or configured_mode).strip().lower()
    if requested_mode in {"fixture", "crawled", "live"}:
        mode = requested_mode
    else:
        # 非法 mode（如拼错 crawel）不静默吞错：记 warning 后回退到配置默认
        logging.getLogger(__name__).warning(
            "非法 task mode=%r，回退到默认 %s", requested_mode, configured_mode
        )
        mode = configured_mode
    if mode == "fixture" and not allow_fixture_tasks():
        raise StrictModeError("严格真实模式禁止创建 fixture（演示）任务，请使用 live")
    stored_brief = validated.model_dump()
    stored_brief["mode"] = mode
    plan = {
        "plan_id": plan_id,
        "brief": stored_brief,
        "mode": mode,  # fixture（演示）| crawled（真实采集+LLM 主链路）| live（飞书实时）
        "created_at": _now(),
        "status": "brief_locked",
        "selected_opportunity": None,
        "plan_card": None,
        "product_proposal": None,
        "revise_logs": [],
    }
    with _lock:
        _PLANS[plan_id] = plan
    return plan


def get_plan(plan_id: str) -> dict[str, Any] | None:
    with _lock:
        return _PLANS.get(plan_id)


# ── per-plan 写锁（业务对象锁，非文件锁）────────────────────
# 同一 plan_id 的「读-改-写」串行化，避免并发请求对同一任务的状态推进竞态。
# 与全局 _lock 分层：_lock 保护 _PLANS 字典结构读写；plan 锁保护单任务业务操作。

_plan_locks: dict[str, threading.Lock] = {}
_plan_locks_guard = threading.Lock()


def _plan_lock(plan_id: str) -> threading.Lock:
    with _plan_locks_guard:
        lock = _plan_locks.get(plan_id)
        if lock is None:
            lock = _plan_locks[plan_id] = threading.Lock()
        return lock


@contextmanager
def plan_write_lock(plan_id: str):
    """同一 plan_id 的写操作串行化上下文管理器"""
    with _plan_lock(plan_id):
        yield


def list_plans() -> list[dict[str, Any]]:
    with _lock:
        plans = [_PLANS[k] for k in _PLANS if not (k == "demo" and is_demo_hidden())]
        plans = sorted(plans, key=lambda p: p["created_at"], reverse=True)
    summaries = [
        PlanSummaryV2(
            plan_id=p["plan_id"],
            theme=p["brief"].get("theme", ""),
            category=p["brief"].get("category", ""),
            audience=p["brief"].get("audience", ""),
            status=p["status"],
            created_at=p["created_at"],
            mode=p["mode"],
        )
        for p in plans
    ]
    return [s.model_dump() for s in summaries]


def delete_plan(plan_id: str) -> bool:
    """删除任务：内存移除 + 清理写锁 + 立即落盘；不存在返回 False"""
    with _lock:
        if plan_id not in _PLANS:
            return False
        del _PLANS[plan_id]
    with _plan_locks_guard:
        _plan_locks.pop(plan_id, None)
    _save_state()
    return True
