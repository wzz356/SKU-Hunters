"""第三阶段飞书链路验收测试

- run_review 事件流被完整消费（FakeBot 收到各角色卡片）
- 角色顺序正确（含 challenge 在 creative 与 business 之间）
- challenge 事件正确展示
- session_id 透传：Gate 按钮 value 携带 session_id
- Gate 恢复同一 checkpoint：点击按钮 → 会议继续到终局
- 重复 event_id 只处理一次（webhook 幂等）
- 飞书发送失败时有明确错误状态（session.status = failed）
- 无硬编码占位结论（卡片内容来自事件，不含 handler 硬编码占位词）
"""

import asyncio
import time

import pytest
from feishu.cards import build_committee_card
from feishu.handler import MessageHandler
from feishu.webhook import is_event_processed


class FakeBot:
    """模拟飞书 bot：记录发送内容，不真正联网"""

    def __init__(self):
        self.messages: list[tuple[str, object]] = []
        self.fail = False

    def send_text(self, chat_id: str, text: str) -> dict:
        if self.fail:
            self.messages.append(("text_error", text))
            return {"code": 1, "msg": "send failed"}
        self.messages.append(("text", text))
        return {"code": 0}

    def send_card(self, chat_id: str, card: dict) -> dict:
        if self.fail:
            self.messages.append(("card_error", card))
            return {"code": 1, "msg": "send failed"}
        self.messages.append(("card", card))
        return {"code": 0}

    @staticmethod
    def build_report_card(role, content, evidence=None, score=None):
        return build_committee_card(
            role=role, content=content, evidence=evidence, score=score
        )

    def card_titles(self) -> list[str]:
        return [c["header"]["title"]["content"] for m, c in self.messages if m == "card"]

    def all_card_text(self) -> str:
        texts = []
        for m, c in self.messages:
            if m != "card":
                continue
            for el in c.get("elements", []):
                if el.get("tag") in ("div", "note"):
                    t = el.get("text", {})
                    texts.append(t.get("content", ""))
        return "\n".join(texts)


def _msg_event(text: str, chat_id: str = "oc_test") -> dict:
    import json

    return {
        "message": {
            "chat_id": chat_id,
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
    }


def _card_evt(sid: str, gate: str, action: str) -> dict:
    return {
        "action": {"value": {"session_id": sid, "gate": gate, "action": action}}
    }


async def _wait_for_gate(h, sid, gate, task, timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = h.get_session(sid)
        if (s.get("pending_gate") or {}).get("gate") == gate:
            return
        if task.done():
            raise AssertionError(f"task ended before reaching gate {gate}")
        await asyncio.sleep(0.05)
    raise AssertionError(f"timeout waiting for gate {gate}")


# ── 1. 事件流完整消费 + 角色顺序 + challenge 展示 + 无占位 ─────

@pytest.mark.asyncio
async def test_full_flow_consumes_all_roles_and_order():
    bot = FakeBot()
    h = MessageHandler(bot, gate_timeout=3)
    await h.handle_message(_msg_event("评审 解压玩具"))
    sid = h.list_sessions()[0]["session_id"]
    task = h.get_session(sid)["task"]

    # 用文本指令驱动所有门，快速走完，避免等超时
    await _wait_for_gate(h, sid, "act1_gate", task)
    await h.handle_message(_msg_event("通过"))  # act1 gate confirm
    await _wait_for_gate(h, sid, "human_gate", task)
    await h.handle_message(_msg_event("通过"))  # human gate confirm
    await _wait_for_gate(h, sid, "retro", task)
    await h.handle_message(_msg_event("结束"))  # retro done

    await asyncio.wait_for(task, timeout=15)
    assert h.get_session(sid)["status"] == "completed"

    titles = bot.card_titles()
    # 关键角色卡片均被消费
    for expected in ("🔍 趋势官", "👥 用户官", "🧸 IP官", "🎨 创意官",
                     "💰 商业官", "🌍 全球化官", "📈 学习官", "🎯 Decision Engine"):
        assert expected in titles, f"缺角色卡片 {expected}"
    # challenge 卡片（质询环节）被展示
    assert any("质询" in t for t in titles), "缺质询卡片"

    # 角色顺序：trend < creative < challenge < business < decision
    def _idx(role):
        return next(i for i, t in enumerate(titles) if role in t)
    assert _idx("创意官") < _idx("质询") < _idx("商业官")

    # 无 handler 硬编码占位结论
    text = bot.all_card_text()
    assert "开发中" not in text
    assert "此处为占位" not in text


# ── 2. challenge 事件正确展示（含来源角色与证据）─────────────

@pytest.mark.asyncio
async def test_challenge_event_displayed():
    bot = FakeBot()
    h = MessageHandler(bot, gate_timeout=3)
    await h.handle_message(_msg_event("评审 解压玩具"))
    sid = h.list_sessions()[0]["session_id"]
    task = h.get_session(sid)["task"]

    await _wait_for_gate(h, sid, "act1_gate", task)
    await h.handle_message(_msg_event("通过"))
    await _wait_for_gate(h, sid, "human_gate", task)
    await h.handle_message(_msg_event("通过"))
    await _wait_for_gate(h, sid, "retro", task)
    await h.handle_message(_msg_event("结束"))
    await asyncio.wait_for(task, timeout=15)

    challenge_text = bot.all_card_text()
    for label in ("趋势官 质询", "用户官 质询", "IP官 质询"):
        assert label in challenge_text, f"质询缺来源角色 {label}"


# ── 3. session_id 透传：Gate 按钮 value 携带 session_id ─────

@pytest.mark.asyncio
async def test_session_id_passed_to_gate_button():
    bot = FakeBot()
    h = MessageHandler(bot, gate_timeout=3)
    await h.handle_message(_msg_event("评审 解压玩具"))
    sid = h.list_sessions()[0]["session_id"]
    task = h.get_session(sid)["task"]

    await _wait_for_gate(h, sid, "act1_gate", task)
    # 找到 Gate 卡片，检查按钮 value 含 session_id
    gate_cards = [
        c for m, c in bot.messages
        if m == "card" and c["header"]["title"]["content"].startswith("🚪")
    ]
    assert gate_cards, "未发送 Gate 卡片"
    actions = [
        a["value"] for el in gate_cards[0].get("elements", [])
        if el.get("tag") == "action" for a in el["actions"]
    ]
    assert all(v["session_id"] == sid for v in actions)
    # 收尾
    await h.handle_message(_msg_event("通过"))
    await _wait_for_gate(h, sid, "human_gate", task)
    await h.handle_message(_msg_event("通过"))
    await _wait_for_gate(h, sid, "retro", task)
    await h.handle_message(_msg_event("结束"))
    await asyncio.wait_for(task, timeout=15)


# ── 4. Gate 恢复同一 checkpoint（点击按钮 → 会议继续到终局）───

@pytest.mark.asyncio
async def test_gate_button_restores_same_checkpoint():
    bot = FakeBot()
    h = MessageHandler(bot, gate_timeout=5)
    await h.handle_message(_msg_event("评审 解压玩具"))
    sid = h.list_sessions()[0]["session_id"]
    task = h.get_session(sid)["task"]

    # 三个门全部用按钮点击驱动
    await _wait_for_gate(h, sid, "act1_gate", task)
    await h.handle_card_action(_card_evt(sid, "act1_gate", "confirm"))

    await _wait_for_gate(h, sid, "human_gate", task)
    await h.handle_card_action(_card_evt(sid, "human_gate", "confirm"))

    await _wait_for_gate(h, sid, "retro", task)
    await h.handle_card_action(_card_evt(sid, "retro", "done"))

    await asyncio.wait_for(task, timeout=15)
    session = h.get_session(sid)
    assert session["status"] == "completed"
    # 同一 session 未重启：只发起了一次评审
    assert len(h.list_sessions()) == 1
    # 学习官归档事件出现
    titles = bot.card_titles()
    assert any("学习官" in t for t in titles)


# ── 5. 重复 event_id 只处理一次（webhook 幂等）──────────────

def test_event_id_idempotent():
    assert is_event_processed("evt_1") is False  # 首次登记
    assert is_event_processed("evt_1") is True   # 重复 → 已处理
    assert is_event_processed("evt_2") is False  # 不同 id 正常


# ── 6. 发送失败有明确错误状态 ─────────────────────────────

@pytest.mark.asyncio
async def test_send_failure_marks_failed():
    bot = FakeBot()
    bot.fail = True
    h = MessageHandler(bot, gate_timeout=1)
    await h.handle_message(_msg_event("评审 解压玩具"))
    sid = h.list_sessions()[0]["session_id"]
    task = h.get_session(sid)["task"]
    await asyncio.wait_for(task, timeout=15)
    s = h.get_session(sid)
    # 发送失败必须进入 failed 状态，不得显示 completed
    assert s["status"] == "failed"
    # 留痕：error、失败阶段、最后事件
    assert s.get("error"), "应保存失败原因"
    assert "failed_stage" in s, "应保存失败阶段"
    # 至少曾尝试发送（start 卡片或事件卡片）
    assert s.get("last_event") is not None or s["failed_stage"] == "start"
