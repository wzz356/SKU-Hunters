"""API 路由 — 对应 docs/api/endpoints.md 约定（D1 冻结 + D2/D3/D5 增补）

编排层已接入：POST /reviews 后台驱动 run_review 事件流，
人工决策经 asyncio.Future 桥接进图的 interrupt。
D5：SQLite 持久化——会议终态自动落盘，重启后历史数据恢复。
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app import store

from ..config import WEIGHT_TEMPLATES
from ..engine.graph import retro_answer, run_review
from ..schemas.brief import Brief, Weights

router = APIRouter(prefix="/api/v1", tags=["committee"])

# 内存主存储：session_id → 运行中会话（与 SQLite 终态落盘互补）
_SESSIONS: dict[str, dict[str, Any]] = {}
_session_locks: dict[str, asyncio.Lock] = {}


async def _session_lock(session_id: str) -> asyncio.Lock:
    """同一 session 的复盘写操作串行化（避免 retro_turns 覆盖 / retro_logs 丢失）"""
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = _session_locks[session_id] = asyncio.Lock()
    return lock

# role → current_act 映射
_ROLE_ACT = {
    "trend": "act1_insights", "user": "act1_insights", "ip": "act1_insights",
    "act1_gate": "act1_gate",
    "creative": "act2_ideation", "challenge": "act2_challenge",
    "business": "act3_dual_review", "global": "act3_dual_review",
    "decision": "act4_decision",
    "human_gate": "human_gate",
    "retro": "act5_retro", "learning": "act5_retro",
    "qa": "act1_gate",
}

_DIGEST_ROLES = {"trend": "趋势官", "user": "用户官", "ip": "IP官",
                 "business": "商业官", "challenge": "质询", "decision": "立项建议"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _restore_archived():
    """启动时把 SQLite 里已归档的会话回灌内存（列表/历史复盘用）"""
    for row in store.list_all():
        sid = row["session_id"]
        if sid not in _SESSIONS:
            full = store.get(sid) or {}
            _SESSIONS[sid] = {
                "brief": full.get("brief", {"category": row.get("category", "")}),
                "created_at": row.get("created_at", ""),
                "current_act": "act5_retro",
                "status": row.get("status", "completed"),
                "live_feed": full.get("live_feed", []),
                "pending_gate": None,
                "gate_future": None,
                "report": full.get("report"),
                "archive": full.get("archive"),
                "retro_logs": full.get("retro_logs", []),
                "digest_parts": full.get("digest_parts", []),
                "final_action": "approve" if row.get("status") == "approved" else None,
                "error": None,
            }


_restore_archived()


def _persist(sid: str):
    """终态落盘（只写不变部分；pending_gate/gate_future 是运行时对象不入库）"""
    s = _SESSIONS.get(sid)
    if not s: return
    store.create_or_update(
        sid,
        brief=s["brief"],
        created_at=s["created_at"],
        current_act=s["current_act"],
        status=s["status"],
        live_feed=s["live_feed"],
        report=s.get("report"),
        archive=s.get("archive"),
        digest_parts=s.get("digest_parts", []),
        final_action=s.get("final_action"),
        error=s.get("error"),
    )



def _persist_snapshot(sid: str, snapshot: dict, question: str, answer: str):
    """线程内落盘：只写 store，不读 _SESSIONS（数据已由调用方在事件循环中复制）"""
    store.add_retro_log(sid, question, answer)
    store.create_or_update(sid, **snapshot)


async def _drive(session_id: str, brief: dict[str, Any]):
    session = _SESSIONS[session_id]

    async def ask_human(gate_info: dict[str, Any]) -> dict[str, Any]:
        session["pending_gate"] = gate_info
        session["status"] = "awaiting_human"
        session["gate_future"] = asyncio.get_running_loop().create_future()
        decision = await session["gate_future"]
        session["pending_gate"] = None
        session["status"] = "running"
        return decision

    try:
        async for event in run_review(brief, ask_human=ask_human, session_id=session_id):
            session["live_feed"].append({**event, "timestamp": _now()})
            session["current_act"] = _ROLE_ACT.get(event["role"], session["current_act"])
            if speaker := _DIGEST_ROLES.get(event["role"]):
                session["digest_parts"].append(f"{speaker}：{event['content']}")
            if report := event.get("report"):
                session["report"] = report
            if snapshot := event.get("snapshot"):
                if session["archive"] is None:
                    session["archive"] = snapshot
                    session["status"] = "rejected" if snapshot.get("status") == "rejected" else "approved"
                else:
                    session["archive"]["retro_turns"] = snapshot.get("retro_turns", 0)
        if session["status"] not in ("approved", "rejected"):
            session["status"] = {"approve": "approved", "reject": "rejected"}.get(
                session.get("final_action"), "completed"
            )
        session["current_act"] = "act5_retro"
    except Exception as e:  # noqa: BLE001 — 会议失败要可见，不能静默吞掉
        session["status"] = "failed"
        session["error"] = str(e)[:500]
    finally:
        _persist(session_id)


@router.post("/reviews", status_code=201)
async def create_review(payload: dict):
    try:
        brief = Brief(**payload.get("brief", {}))
    except ValidationError as e:
        raise HTTPException(422, detail={"error": {"code": "BRIEF_INVALID", "message": str(e)}})

    session_id = f"sess_{datetime.now(timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:4]}"
    _SESSIONS[session_id] = {
        "brief": brief.model_dump(),
        "created_at": _now(),
        "current_act": "brief_locked",
        "status": "running",
        "live_feed": [],
        "pending_gate": None,
        "gate_future": None,
        "report": None,
        "archive": None,
        "retro_logs": [],
        "digest_parts": [],
        "final_action": None,
        "error": None,
    }
    asyncio.create_task(_drive(session_id, brief.model_dump()))
    return {"session_id": session_id, "status": "created"}


@router.get("/reviews")
async def list_reviews():
    return {
        "reviews": [
            {
                "session_id": sid,
                "category": s["brief"].get("category", ""),
                "market": s["brief"].get("market", ""),
                "status": s["status"],
                "created_at": s["created_at"],
                "archive": s["archive"],
                "retro_turns": (s["archive"] or {}).get("retro_turns", 0),
            }
            for sid, s in sorted(_SESSIONS.items(), key=lambda kv: kv[1]["created_at"], reverse=True)
        ]
    }


def _get_session(session_id: str) -> dict[str, Any]:
    session = _SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, detail={"error": {"code": "SESSION_NOT_FOUND", "message": session_id}})
    return session


@router.get("/reviews/{session_id}")
async def get_review(session_id: str):
    session = _get_session(session_id)
    return {
        "session_id": session_id,
        "current_act": session["current_act"],
        "status": session["status"],
        "live_feed": session["live_feed"],
        "pending_gate": session["pending_gate"],
        "conflicts": (session["report"] or {}).get("dissent_records", []),
        "archive": session["archive"],
        "retro_logs": session["retro_logs"],
        "error": session["error"],
    }


@router.get("/reviews/{session_id}/report")
async def get_report(session_id: str):
    session = _get_session(session_id)
    if not session["report"]:
        raise HTTPException(404, detail={"error": {"code": "REPORT_NOT_READY", "message": "会议尚未到达决策"}})
    return {"session_id": session_id, **session["report"]}


@router.post("/reviews/{session_id}/decision")
async def submit_decision(session_id: str, payload: dict):
    session = _get_session(session_id)
    future = session.get("gate_future")
    if not session["pending_gate"] or future is None or future.done():
        raise HTTPException(409, detail={"error": {"code": "SESSION_NOT_AT_GATE", "message": "当前不在人工决策点"}})

    action = payload.get("action")
    reason = payload.get("reason", "")
    if action in ("approve", "reject") and not reason:
        raise HTTPException(422, detail={"error": {"code": "DECISION_REASON_REQUIRED", "message": "approve/reject 必须填写理由"}})

    decision: dict[str, Any]
    if action == "approve":
        decision = {"action": "confirm", "reason": reason}
    elif action == "reject":
        decision = {"action": "reject", "reason": reason}
    elif action == "revise":
        decision = {"action": "modify", "suggestion": reason, "scope": payload.get("scope", "business")}
    elif action == "reweight":
        try:
            Weights.model_validate(payload.get("custom_weights") or {})
            assert payload.get("custom_weights")
        except (ValidationError, AssertionError):
            raise HTTPException(422, detail={"error": {"code": "WEIGHT_SUM_INVALID", "message": "五维权重之和必须为 1.0"}})
        decision = {"action": "modify", "suggestion": reason or "重定权重", "scope": "business", "custom_weights": payload["custom_weights"]}
    elif action == "question":
        question = payload.get("question", "").strip()
        if not question:
            raise HTTPException(422, detail={"error": {"code": "QUESTION_REQUIRED", "message": "question 必填"}})
        decision = {"action": "question", "question": question}
    elif action == "chat":
        decision = {"action": "chat", "content": payload.get("content", "")}
    elif action == "done":
        decision = {"action": "done"}
    else:
        raise HTTPException(422, detail={"error": {"code": "ACTION_UNKNOWN", "message": f"未知动作: {action}"}})

    session["final_action"] = action if action in ("approve", "reject") else session["final_action"]
    future.set_result(decision)
    return {"session_id": session_id, "status": "decision_accepted", "mapped": decision}


@router.post("/reviews/{session_id}/retro")
async def retro_chat(session_id: str, payload: dict):
    session = _get_session(session_id)
    if session["archive"] is None:
        raise HTTPException(409, detail={"error": {"code": "RETRO_NOT_READY", "message": "会议尚未归档，暂无复盘材料"}})
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(422, detail={"error": {"code": "RETRO_QUESTION_REQUIRED", "message": "question 必填"}})
    lock = await _session_lock(session_id)
    async with lock:
        digest = "\n".join(session["digest_parts"])
        answer = await asyncio.to_thread(retro_answer, digest, question)
        turn = {"question": question, "answer": answer, "timestamp": _now()}
        session["retro_logs"].append(turn)
        session["archive"]["retro_turns"] = session["archive"].get("retro_turns", 0) + 1
        # 复制需要持久化的数据，线程只写 store 不读 _SESSIONS
        snapshot = {
            "brief": copy.deepcopy(session["brief"]),
            "created_at": session["created_at"],
            "current_act": session["current_act"],
            "status": session["status"],
            "live_feed": copy.deepcopy(session["live_feed"]),
            "report": copy.deepcopy(session.get("report")),
            "archive": copy.deepcopy(session.get("archive")),
            "digest_parts": copy.deepcopy(session.get("digest_parts", [])),
            "final_action": session.get("final_action"),
            "error": session.get("error"),
        }
        await asyncio.to_thread(_persist_snapshot, session_id, snapshot, question, answer)
        return {"session_id": session_id, **turn}


@router.get("/weights/templates")
async def list_weight_templates():
    labels = {"default": "默认均衡", "volume": "走量款", "image": "形象款", "profit": "利润款"}
    return {"templates": [{"key": k, "label": labels[k], "weights": w.model_dump()} for k, w in WEIGHT_TEMPLATES.items()]}
