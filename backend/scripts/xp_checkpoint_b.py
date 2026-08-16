"""跨进程 checkpoint 恢复 — 进程 B：恢复进程 A 停在 act1_gate 的会话，走完流程。"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.graph import run_review

BRIEF = {"category": "蜘蛛侠", "market": "CN", "budget_range": "mid"}
SID = "xp_recovery_test"


async def ask(gate):
    return {"action": "confirm"} if gate["gate"] != "retro" else {"action": "done"}


async def main():
    roles = []
    async for e in run_review(BRIEF, ask_human=ask, session_id=SID):
        roles.append(e["role"])
    print("B_ROLES=" + ",".join(roles), flush=True)
    os._exit(0)


asyncio.run(main())
