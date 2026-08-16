"""真委员端到端冒烟 — AGENT_PROVIDER=real 下跑一轮完整评审

用法（从 backend/ 目录，env 必须在进程启动前设置）：
    set AGENT_PROVIDER=real && python scripts/smoke_real_agents.py      # cmd
    AGENT_PROVIDER=real python scripts/smoke_real_agents.py             # bash

验证点：
  - 六官是否真产出（confidence / evidence / caveats 来自真 Agent 特征）
  - 商业官总分 = 代码加权算术（可复算）
  - 任何一路故障自动回退 Mock（冒烟不炸即降级纪律生效）
输出全 ASCII（GBK 控制台安全）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.engine.graph import run_review

BRIEF = {
    "category": "小风扇",
    "market": "CN",
    "budget_range": "mid",
    "candidate_pool": ["库洛米", "玉桂狗", "线条小狗"],
}


async def _ask_human(gate: dict) -> dict:
    print(f">> gate [{gate['gate']}] auto-confirm")
    return {"action": "confirm"}


async def main() -> None:
    provider = os.getenv("AGENT_PROVIDER", "mock")
    print(f"== smoke: AGENT_PROVIDER={provider} category={BRIEF['category']} ==")
    async for event in run_review(BRIEF, ask_human=_ask_human):
        role = event["role"]
        head = event["content"].splitlines()[0] if event["content"] else ""
        print(f"[{role}] {head[:70]}")
        if event.get("score") is not None:
            print(f"  score={event['score']:.2f}")
        for ev in event.get("evidence", [])[:2]:
            print(f"  evidence: {str(ev)[:100]}")
    print("== smoke done ==")


if __name__ == "__main__":
    asyncio.run(main())
