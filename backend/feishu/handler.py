"""
消息处理器 - 接收飞书消息，接入 LangGraph run_review 事件流

架构（第三阶段）：
- 飞书收到「评审 <主题>」→ 生成稳定 session_id → 后台任务调用
  app.engine.graph.run_review(brief, ask_human=callback, session_id=session_id)
- session_id 即 LangGraph checkpoint thread_id；人工 Gate 按钮 value 携带
  session_id，点击后通过 gate_future 恢复同一 checkpoint（不重启流程）。
- 事件流（role/content/evidence/score 四键契约）映射为委员发言卡片；
  卡片内容一律来自 LangGraph 事件 / Artifact，禁止硬编码角色结论与评分。
- 门事件（act1_gate / human_gate / retro）经 ask_human 回调发带按钮的
  Gate 卡片，超时（默认 10s）自动 confirm / done 兜底。
- 所有 HTTP 发送经 asyncio.to_thread 包裹，避免阻塞事件循环，
  保证 webhook 异步快速返回。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from .bot import FeishuBot
from .cards import build_gate_card, build_start_card

# 决策回显标记（run_review 中 _describe 返回，用于区分门事件提问与回显）
_GATE_ECHO_MARKERS = ("✅", "✏️", "❌", "❓", "💬", "📝")
# 复盘/问答作答的固定前缀（无 LLM 时 retro_answer 的产物索引降级）
_ANSWER_PREFIX = "关于「"
_GATE_LABEL = {"act1_gate": "洞察确认门", "human_gate": "立项拍板门", "retro": "复盘"}

_EMPTY = object()


class BotSendError(Exception):
    """飞书消息发送失败（Bot 返回非零 code）"""


def _check_send(resp):
    """校验 Bot 发送返回值：非零 code 或非 dict 一律视为失败，抛出明确异常。

    Feishu API 返回体含 code 字段，0 表示成功，非 0 表示失败。
    发送失败必须显式抛异常，由 _run_review 将会话置为 failed，
    避免会议在发送失败后仍显示 completed。
    """
    if not isinstance(resp, dict) or resp.get("code", 0) != 0:
        raise BotSendError(f"飞书发送失败，返回：{resp}")


class MessageHandler:
    """飞书消息处理器（LangGraph 接入版）"""

    def __init__(self, bot: FeishuBot, gate_timeout: float = 10.0):
        self.bot = bot
        self.gate_timeout = gate_timeout
        # session_id -> 会话状态（含 gate_future，供按钮恢复 checkpoint）
        self._sessions: dict[str, dict[str, Any]] = {}

    # ── 消息入口 ─────────────────────────────────

    async def handle_message(self, event: dict[str, Any]) -> dict[str, Any]:
        msg = event.get("message", {})
        chat_id = msg.get("chat_id", "")
        msg_type = msg.get("message_type", "")
        content = msg.get("content", "{}")

        if msg_type != "text":
            return {"code": 0, "msg": "ignored"}

        import json

        try:
            content_data = json.loads(content)
            text = content_data.get("text", "")
        except (ValueError, AttributeError):
            text = content

        text = re.sub(r"@_user_1\s*", "", text).strip()
        if not text:
            return {"code": 0, "msg": "ignored"}

        # 1) 启动新一轮评审
        if text.startswith(("评审", "分析")):
            topic = re.sub(r"^(评审|分析)(一下|下)?", "", text).strip()
            if not topic:
                topic = "解压玩具"
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            self._sessions[session_id] = {
                "chat_id": chat_id,
                "topic": topic,
                "brief": {"category": topic, "market": "CN", "budget_range": "mid"},
                "status": "running",
                "pending_gate": None,
                "gate_future": None,
                "live_feed": [],
            }
            task = asyncio.create_task(self._run_review(session_id))
            self._sessions[session_id]["task"] = task
            return {"code": 0, "msg": "ok", "session_id": session_id}

        # 2) 会议进行中的人工 Gate 文本指令（修改/追问/通过/否决/复盘）
        if self._try_text_decision(chat_id, text):
            return {"code": 0, "msg": "ok"}

        # 3) 帮助
        if text in ("帮助", "help"):
            await self._send_text(
                chat_id,
                "SKU Hunters · AI Product Committee\n\n"
                "使用方式：\n"
                "• @我 说「评审 XXX」- 启动一轮商品评审\n"
                "• 门决策时：`通过` / `否决 <理由>` / `修改 <意见>` / `追问 <问题>`\n"
                "• 复盘窗：直接发送问题即可继续提问，`结束` 结束复盘\n"
                "• @我 说「帮助」- 查看帮助",
            )
            return {"code": 0, "msg": "ok"}

        return {"code": 0, "msg": "ignored"}

    # ── 人工 Gate 文本指令 ───────────────────────

    def _try_text_decision(self, chat_id: str, text: str) -> bool:
        """把群聊文本映射为当前 pending gate 的决策，恢复同一 checkpoint"""
        for s in self._sessions.values():
            if s["chat_id"] != chat_id:
                continue
            future = s.get("gate_future")
            gate = s.get("pending_gate")
            if not gate or future is None or future.done():
                continue

            gname = gate["gate"]
            if gname == "retro":
                if text in ("结束", "总结", "done"):
                    decision: dict[str, Any] = {"action": "done"}
                elif text:
                    decision = {"action": "chat", "content": text}
                else:
                    continue
            elif text.startswith("通过") or text in ("确定", "确认", "是"):
                decision = {"action": "confirm"}
            elif text.startswith("否决"):
                reason = text[2:].strip() or "商品经理否决"
                decision = {"action": "reject", "reason": reason}
            elif text.startswith("修改"):
                suggestion = text[2:].strip() or "请调整方案"
                decision = {"action": "modify", "suggestion": suggestion}
                if gname == "human_gate":
                    decision["scope"] = "business"
            elif text.startswith("追问"):
                q = text[2:].strip()
                decision = {"action": "question", "question": q}
            else:
                continue

            future.set_result(decision)
            return True
        return False

    # ── 后台评审任务（消费 run_review 事件流）───────

    async def _run_review(self, session_id: str) -> None:
        from app.engine.graph import run_review

        s = self._sessions[session_id]
        chat_id = s["chat_id"]

        stage = "start"
        last_event = None
        try:
            await self._send_card(chat_id, build_start_card(s["topic"]))
            async for event in run_review(
                s["brief"],
                ask_human=self._make_ask_human(session_id),
                session_id=session_id,
            ):
                last_event = event
                s["last_event"] = event
                stage = f"event:{event.get('role', '?')}"
                s["live_feed"].append(event)
                await self._dispatch(chat_id, event, session_id)
            s["status"] = "completed"
        except Exception as e:  # noqa: BLE001 — 会议失败要可见，不静默
            # 失败留痕：状态置 failed，保存错误、失败阶段与最后事件，
            # 不得继续显示为 completed。
            s["status"] = "failed"
            s["error"] = str(e)[:500]
            s["failed_stage"] = stage
            s["last_event"] = last_event
            try:
                await self._send_text(
                    chat_id, f"⚠️ 会议执行失败（{stage}）：{str(e)[:200]}"
                )
            except Exception:  # noqa: BLE001,S110 — 失败通知失败也不掩盖原始失败
                pass

    async def _dispatch(self, chat_id: str, event: dict, session_id: str) -> None:
        """把 LangGraph 事件映射为飞书消息"""
        role = event["role"]

        # 委员发言（含质询、决策、学习、问答、复盘作答）
        if role in (
            "trend", "user", "ip", "creative", "challenge",
            "business", "global", "learning",
        ):
            await self._send_committee(chat_id, role, event)
            return

        if role == "decision":
            await self._send_committee(chat_id, "decision", event)
            return

        # 复盘/问答作答（retro_qa_node / qa 节点）
        if role in ("retro", "qa") and event["content"].startswith(_ANSWER_PREFIX):
            await self._send_committee(chat_id, role, event)
            return

        # 门事件：提问由 ask_human 发按钮卡（此处不重复发）；回显发一条文本
        if role in ("act1_gate", "human_gate", "retro"):
            content = event["content"]
            if content.startswith(_GATE_ECHO_MARKERS):
                label = _GATE_LABEL.get(role, role)
                await self._send_text(chat_id, f"🚪 {label}：{content}")
            # 其余为门提问，由 _make_ask_human 的按钮卡处理
            return

    def _make_ask_human(self, session_id: str):
        """构造 run_review 的 ask_human 回调：发按钮卡并等待人工决策（带超时）"""

        async def ask_human(gate_info: dict[str, Any]) -> dict[str, Any]:
            s = self._sessions[session_id]
            chat_id = s["chat_id"]

            await self._send_gate_card(chat_id, gate_info, session_id)

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            s["gate_future"] = future
            s["pending_gate"] = gate_info
            try:
                decision = await asyncio.wait_for(
                    asyncio.shield(future), timeout=self.gate_timeout
                )
            except asyncio.TimeoutError:
                decision = (
                    {"action": "done"}
                    if gate_info["gate"] == "retro"
                    else {"action": "confirm"}
                )
            finally:
                s["pending_gate"] = None
                s["gate_future"] = None
            return decision

        return ask_human

    # ── 卡片按钮事件（恢复 checkpoint）─────────────

    async def handle_card_action(self, event: dict[str, Any]) -> dict[str, Any]:
        action = event.get("action", {})
        value = action.get("value", {})
        sid = value.get("session_id")
        act = value.get("action")

        s = self._sessions.get(sid)
        if not s or not s.get("gate_future") or s.get("gate_future").done():
            return {"code": 0, "msg": "no pending gate"}

        if act == "confirm":
            decision: dict[str, Any] = {"action": "confirm"}
        elif act == "reject":
            decision = {"action": "reject", "reason": value.get("reason", "商品经理否决")}
        elif act == "question":
            decision = {"action": "question", "question": value.get("question", "请说明疑问")}
        elif act == "chat":
            decision = {"action": "chat", "content": value.get("content", "")}
        elif act == "done":
            decision = {"action": "done"}
        else:
            return {"code": 0, "msg": "unknown action"}

        s["gate_future"].set_result(decision)
        return {"code": 0, "msg": "ok"}

    # ── 发送辅助（to_thread 异步化，避免阻塞事件循环）──

    async def _send_text(self, chat_id: str, text: str) -> None:
        resp = await asyncio.to_thread(self.bot.send_text, chat_id, text)
        _check_send(resp)

    async def _send_card(self, chat_id: str, card: dict) -> None:
        resp = await asyncio.to_thread(self.bot.send_card, chat_id, card)
        _check_send(resp)

    async def _send_committee(
        self, chat_id: str, role: str, event: dict
    ) -> None:
        card = self.bot.build_report_card(
            role=role,
            content=event["content"],
            evidence=event.get("evidence"),
            score=event.get("score"),
        )
        await self._send_card(chat_id, card)

    async def _send_gate_card(
        self, chat_id: str, gate_info: dict, session_id: str
    ) -> None:
        gate = gate_info.get("gate", "human_gate")
        card = build_gate_card(
            gate=gate,
            prompt=gate_info.get("prompt", ""),
            session_id=session_id,
            gate_label=_GATE_LABEL.get(gate, "人工决策"),
        )
        await self._send_card(chat_id, card)

    # ── 状态访问（测试用）────────────────────────

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {"session_id": sid, "status": s["status"], "topic": s["topic"]}
            for sid, s in self._sessions.items()
        ]
