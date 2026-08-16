"""webhook 集成测试 — 身份校验、event_id 幂等、依赖注入

通过 TestClient 驱动 create_feishu_router（注入 FakeBot，不真正联网），
验证：
- challenge 校验：URL 验证请求原样返回
- 身份校验 fail-closed：token 不匹配 → 403
- event_id 幂等：同一 event_id 重复投递只处理一次
- 消息事件触发评审（FakeBot 记录发送）
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from feishu.config import FeishuConfig
from feishu.webhook import create_feishu_router


class FakeBot:
    """最小飞书 bot 桩：记录发送，不联网"""

    def __init__(self):
        self.messages = []

    def send_text(self, chat_id, text):
        self.messages.append(("text", text))
        return {"code": 0}

    def send_card(self, chat_id, card):
        self.messages.append(("card", card))
        return {"code": 0}

    @staticmethod
    def build_report_card(role, content, evidence=None, score=None):
        from feishu.cards import build_committee_card

        return build_committee_card(
            role=role, content=content, evidence=evidence, score=score
        )

    def card_titles(self):
        return [c["header"]["title"]["content"] for m, c in self.messages if m == "card"]


def _msg_event(text: str, chat_id: str = "oc_test") -> dict:
    return {
        "message": {
            "chat_id": chat_id,
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
    }


@pytest.fixture
def client():
    bot = FakeBot()
    config = FeishuConfig(
        app_id="cli_x", app_secret="sec_x", verification_token="tok_x"
    )
    app = FastAPI()
    app.include_router(create_feishu_router(config, bot=bot), prefix="/feishu")
    with TestClient(app) as c:
        c.bot = bot  # type: ignore[attr-defined]
        yield c


def _body(event_type: str, event: dict, event_id: str = "evt_x") -> dict:
    return {
        "header": {"event_type": event_type, "event_id": event_id},
        "event": event,
        "token": "tok_x",
    }


def test_url_verification_challenge(client):
    # URL 验证请求必须携带正确 token 才能返回 challenge
    r = client.post(
        "/feishu/events",
        json={"type": "url_verification", "token": "tok_x", "challenge": "abc123"},
    )
    assert r.status_code == 200
    assert r.json() == {"challenge": "abc123"}


def test_challenge_invalid_token_rejected(client):
    # challenge + 错误 token 必须先过鉴权，403 而非返回 challenge
    r = client.post(
        "/feishu/events",
        json={"type": "url_verification", "token": "wrong", "challenge": "abc123"},
    )
    assert r.status_code == 403
    assert "challenge" not in r.json()


def test_challenge_missing_token_rejected(client):
    # challenge + 缺失 token -> 403
    r = client.post("/feishu/events", json={"type": "url_verification", "challenge": "abc123"})
    assert r.status_code == 403


def test_invalid_token_rejected(client):
    body = _body("im.message.receive_v1", _msg_event("评审 解压玩具"))
    body["token"] = "wrong_token"
    r = client.post("/feishu/events", json=body)
    assert r.status_code == 403


def test_missing_token_rejected(client):
    body = _body("im.message.receive_v1", _msg_event("评审 解压玩具"))
    body.pop("token", None)
    r = client.post("/feishu/events", json=body)
    assert r.status_code == 403


def test_config_missing_token_fail_closed():
    # 配置缺失 verification_token -> 全部请求 403，不 fail-open
    bot = FakeBot()
    config = FeishuConfig(app_id="cli_x", app_secret="sec_x", verification_token="")
    app = FastAPI()
    app.include_router(create_feishu_router(config, bot=bot), prefix="/feishu")
    with TestClient(app) as c:
        r = c.post(
            "/feishu/events",
            json={"type": "url_verification", "token": "tok_x", "challenge": "abc"},
        )
        assert r.status_code == 403
        r2 = c.post(
            "/feishu/events",
            json=_body("im.message.receive_v1", _msg_event("评审 解压玩具"), event_id="evt_cfg"),
        )
        assert r2.status_code == 403


def test_event_id_idempotent(client):
    body = _body("im.message.receive_v1", _msg_event("评审 解压玩具"), event_id="evt_dup")
    r1 = client.post("/feishu/events", json=body)
    assert r1.status_code == 200
    # 同一 event_id 重复投递 → 幂等忽略，不重复启动
    r2 = client.post("/feishu/events", json=body)
    assert r2.status_code == 200
    assert r2.json()["msg"] == "duplicate, ignored"


def test_message_triggers_review(client):
    body = _body("im.message.receive_v1", _msg_event("评审 解压玩具", "oc_abc"), event_id="evt_msg")
    r = client.post("/feishu/events", json=body)
    assert r.status_code == 200
    # 后台任务在 TestClient portal 异步推进，轮询等待评审开始卡片
    import time
    deadline = time.time() + 5
    titles = client.bot.card_titles()  # type: ignore[attr-defined]
    while time.time() < deadline and not any("评审开始" in t for t in titles):
        time.sleep(0.1)
        titles = client.bot.card_titles()  # type: ignore[attr-defined]
    assert any("评审开始" in t for t in titles)
