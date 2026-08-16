"""飞书端到端演示 — 用 FakeBot 完整消费 run_review 事件流并输出卡片映射日志

不真正连接飞书，用桩 bot 展示 LangGraph → 飞书卡片的完整映射，
便于本地验证与演示（避免依赖真实飞书凭据/外网）。

用法（从 backend/ 目录）：
    python scripts/feishu_e2e_demo.py 解压玩具 > feishu_e2e_log.txt
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from feishu.cards import build_committee_card
from feishu.handler import MessageHandler


class FakeBot:
    """桩 bot：打印每张卡片的标题与正文，模拟飞书发送"""

    def __init__(self):
        self.messages: list[tuple[str, object]] = []

    def send_text(self, chat_id: str, text: str) -> dict:
        self.messages.append(("text", text))
        print(f"  [TEXT] {text}")
        return {"code": 0}

    def send_card(self, chat_id: str, card: dict) -> dict:
        self.messages.append(("card", card))
        title = card["header"]["title"]["content"]
        print(f"  ┌─ [{title}]")
        for el in card.get("elements", []):
            if el.get("tag") == "div":
                t = el.get("text", {}).get("content", "")
                for line in t.splitlines():
                    print(f"  │  {line}")
            if el.get("tag") == "action":
                for a in el.get("actions", []):
                    print(f"  │  [按钮] {a['text']['content']} -> {a['value']}")
        print("  └─")
        return {"code": 0}

    @staticmethod
    def build_report_card(role, content, evidence=None, score=None):
        return build_committee_card(
            role=role, content=content, evidence=evidence, score=score
        )


def _msg(text: str) -> dict:
    return {
        "message": {
            "chat_id": "oc_demo",
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
    }


async def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "解压玩具"
    auto = "--auto" in sys.argv

    bot = FakeBot()
    handler = MessageHandler(bot, gate_timeout=30)
    print(f"=== SKU Hunters · 飞书圆桌会议（LangGraph 接入）主题：{topic} ===\n")

    await handler.handle_message(_msg(f"评审 {topic}"))
    sid = handler.list_sessions()[0]["session_id"]
    print(f"\n>>> 已发起评审，session_id = {sid}\n")
    task = handler.get_session(sid)["task"]

    async def drive_gate(gate: str, decision: str):
        # 等待到达门
        for _ in range(200):
            s = handler.get_session(sid)
            if (s.get("pending_gate") or {}).get("gate") == gate:
                break
            await asyncio.sleep(0.05)
        print(f"\n>>> [GATE {gate}] 收到人工决策点，用户输入：{decision}\n")
        await handler.handle_message(_msg(decision))

    auto_task = None
    if not auto:
        # 交互模式：用按钮/文本驱动三道门（验证 session_id 透传恢复 checkpoint）
        await drive_gate("act1_gate", "通过")
        await drive_gate("human_gate", "通过")
        await drive_gate("retro", "结束")
    else:
        # 自动模式：监听 pending_gate，到达门即自动注入 confirm/done，
        # 而不是等 gate_timeout 兜底（避免累计超时）。
        async def auto_drive():
            while True:
                s = handler.get_session(sid)
                if s is None:
                    return
                gate = (s.get("pending_gate") or {}).get("gate")
                if gate:
                    decision = "结束" if gate == "retro" else "通过"
                    print(f"\n>>> [AUTO] 检测到门 {gate}，自动注入：{decision}\n")
                    await handler.handle_message(_msg(decision))
                await asyncio.sleep(0.1)

        auto_task = asyncio.create_task(auto_drive())

    await asyncio.wait_for(task, timeout=120)
    if auto_task is not None:
        auto_task.cancel()
    s = handler.get_session(sid)
    print(f"\n=== 会议结束：status = {s['status']} ===")
    roles = [e["role"] for e in s["live_feed"]]
    print(f"事件流角色序列：{roles}")


if __name__ == "__main__":
    asyncio.run(main())
