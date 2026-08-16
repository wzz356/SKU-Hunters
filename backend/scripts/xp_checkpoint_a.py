"""跨进程 checkpoint 恢复 — 进程 A：启动评审，停在 act1_gate，落盘后退出。"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.graph import run_review

BRIEF = {"category": "蜘蛛侠", "market": "CN", "budget_range": "mid"}
SID = "xp_recovery_test"


async def ask(gate):
    # 进程 A 不做任何决策，直接等待首个 interrupt 后停止
    raise SystemExit("process A stops at first gate")


async def main():
    roles = []
    try:
        async for e in run_review(BRIEF, ask_human=ask, session_id=SID):
            roles.append(e["role"])
    except SystemExit:
        pass
    print("A_ROLES=" + ",".join(roles), flush=True)
    os._exit(0)


asyncio.run(main())
