"""命令行演示：跑一轮完整的 AI 委员会评审（mock Agent 版）

用法（从 backend/ 目录）：
    python scripts/demo_review.py 解压玩具
    python scripts/demo_review.py 解压玩具 --auto   # 门全部自动确定

门节点交互：输入回车=确定；m 空格 意见=修改；q 空格 问题=疑问
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Windows 控制台默认 GBK，打不了 emoji——强制 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.engine.graph import run_review

_ROLE_LABEL = {
    "trend": "🔍 趋势官", "user": "👥 用户官", "ip": "🧸 IP官",
    "creative": "🎨 创意官", "challenge": "⚔️ 质询", "business": "💰 商业官", "global": "🌍 全球化官",
    "decision": "🎯 Decision Engine", "learning": "📈 学习官",
    "act1_gate": "🚪 洞察确认门", "human_gate": "🚪 立项拍板门", "qa": "💬 问答",
}


def _make_ask_human(auto: bool):
    async def ask(gate: dict) -> dict:
        if auto:
            print("   （自动模式：直接确定）")
            return {"action": "confirm"}
        raw = input("   你的决定 [回车=确定 / m 意见=修改 / q 问题=疑问]: ").strip()
        if raw.startswith("m "):
            d: dict = {"action": "modify", "suggestion": raw[2:]}
            if gate["gate"] == "human_gate":
                scope = input("   回退范围 [b=商业官重算(默认) / c=回退创意官]: ").strip()
                d["scope"] = "creative" if scope == "c" else "business"
            return d
        if raw.startswith("q "):
            return {"action": "question", "question": raw[2:]}
        return {"action": "confirm"}

    return ask


async def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "解压玩具"
    auto = "--auto" in sys.argv
    brief = {"category": topic, "market": "CN", "budget_range": "mid"}

    print(f"\n{'=' * 56}\n  SKU Hunters · AI 委员会评审（mock 版）  主题：{topic}\n{'=' * 56}\n")

    async for event in run_review(brief, ask_human=_make_ask_human(auto)):
        label = _ROLE_LABEL.get(event["role"], event["role"])
        print(f"┌─ {label} {'─' * max(2, 48 - len(label) * 2)}")
        for line in event["content"].splitlines():
            print(f"│  {line}")
        if event.get("score") is not None:
            print(f"│  ⭐ 机会值：{event['score']:.1f} / 100")
        for ev in event.get("evidence", []):
            print(f"│  📎 {ev}")
        print(f"└{'─' * 56}\n")

    print("会议结束。立项台账已建档（学习官）。")


if __name__ == "__main__":
    asyncio.run(main())
