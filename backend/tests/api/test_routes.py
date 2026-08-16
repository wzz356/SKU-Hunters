"""API 集成测试 — 冻结契约动作映射 + 门桥 + 建议书端点

走真图（mock 委员）：POST /reviews 后台驱动，轮询到门，提交决策，拿建议书。
"""

import time

import pytest
from app.api.routes import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(router)

BRIEF = {"brief": {"category": "解压玩具", "market": "CN", "budget_range": "mid"}}


@pytest.fixture
def client():
    # 必须用 with：portal 持续运转，后台会议任务才会推进
    with TestClient(app) as c:
        yield c


def _create(client) -> str:
    r = client.post("/api/v1/reviews", json=BRIEF)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _poll(client, session_id: str, pred, timeout: float = 20.0):
    """轮询会议状态直到 pred 命中，返回状态 dict"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/v1/reviews/{session_id}").json()
        assert state["status"] != "failed", state.get("error")
        if pred(state):
            return state
        time.sleep(0.1)
    raise TimeoutError(f"轮询超时: {session_id}")


def _at_gate(gate: str):
    return lambda s: (s["pending_gate"] or {}).get("gate") == gate


def _drain_to_end(client, session_id: str, timeout: float = 20.0):
    """通用收尾：不管当前在哪个门，批准/结束直到会议终局（无挂起的门）"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/api/v1/reviews/{session_id}").json()
        assert s["status"] != "failed", s.get("error")
        if s["status"] in ("approved", "rejected", "completed") \
                and s["pending_gate"] is None:
            return s
        gate = (s["pending_gate"] or {}).get("gate")
        if gate in ("act1_gate", "human_gate"):
            client.post(f"/api/v1/reviews/{session_id}/decision",
                        json={"action": "approve", "reason": "ok"})
        elif gate == "retro":
            client.post(f"/api/v1/reviews/{session_id}/decision",
                        json={"action": "done"})
        time.sleep(0.1)
    raise TimeoutError(f"收尾超时: {session_id}")


def test_full_flow_approve_to_report(client):
    """全链路：发起 → Gate1 批准 → Gate2 批准 → done → 建议书可取"""
    sid = _create(client)

    # 门桥挂起：act1_gate
    _poll(client, sid, _at_gate("act1_gate"))
    # approve 无理由 → 422（契约：理由必填，学习官负样本来源）
    r = client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "approve"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "DECISION_REASON_REQUIRED"
    # 带理由批准
    r = client.post(f"/api/v1/reviews/{sid}/decision",
                    json={"action": "approve", "reason": "方向认可"})
    assert r.status_code == 200
    assert r.json()["mapped"]["action"] == "confirm"

    # Gate2 批准
    _poll(client, sid, _at_gate("human_gate"))
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "同意立项"})
    # 复盘窗：直接结束
    _poll(client, sid, _at_gate("retro"))
    client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "done"})

    final = _poll(client, sid, lambda s: s["status"] == "approved"
                  and s["pending_gate"] is None)
    roles = [e["role"] for e in final["live_feed"]]
    assert {"trend", "user", "ip", "creative", "business", "decision",
            "learning"} <= set(roles)

    # 归档快照：Gate 2 结论即建档（归档先于复盘）
    assert final["archive"]["status"] == "archived"
    assert final["archive"]["human_action"] == "confirm"

    # 建议书
    report = client.get(f"/api/v1/reviews/{sid}/report").json()
    assert report["decision"] in ("approve", "hold", "reject")
    assert report["proposal"]["name"]


def test_reject_flow_marks_rejected(client):
    """reject → 状态 rejected，建议书仍可查（bad case 留档）"""
    sid = _create(client)
    _poll(client, sid, _at_gate("act1_gate"))
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _poll(client, sid, _at_gate("human_gate"))
    r = client.post(f"/api/v1/reviews/{sid}/decision",
                    json={"action": "reject", "reason": "窗口期赶不上"})
    assert r.json()["mapped"]["action"] == "reject"
    _poll(client, sid, _at_gate("retro"))
    client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "done"})
    final = _poll(client, sid, lambda s: s["status"] == "rejected")
    assert final["status"] == "rejected"
    assert client.get(f"/api/v1/reviews/{sid}/report").status_code == 200


def test_reweight_requires_valid_weights(client):
    """reweight：缺/错权重 → WEIGHT_SUM_INVALID；合法权重 → 商业官重算"""
    sid = _create(client)
    _poll(client, sid, _at_gate("act1_gate"))
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _poll(client, sid, _at_gate("human_gate"))

    # 缺 custom_weights
    r = client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "reweight"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "WEIGHT_SUM_INVALID"
    # 权重和不为 1
    r = client.post(f"/api/v1/reviews/{sid}/decision",
                    json={"action": "reweight",
                          "custom_weights": {"trend_heat": 0.5, "user_demand": 0.4,
                                             "ip_fit": 0.4, "competition": 0.1,
                                             "history_analog": 0.1}})
    assert r.status_code == 422
    # 合法 reweight
    r = client.post(f"/api/v1/reviews/{sid}/decision",
                    json={"action": "reweight",
                          "custom_weights": {"trend_heat": 1.0, "user_demand": 0.0,
                                             "ip_fit": 0.0, "competition": 0.0,
                                             "history_analog": 0.0}})
    assert r.status_code == 200

    # 重算后回到 Gate2 → 批准 → done
    _poll(client, sid, _at_gate("human_gate"))
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _poll(client, sid, _at_gate("retro"))
    client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "done"})
    final = _poll(client, sid, lambda s: s["status"] == "approved")
    business = [e for e in final["live_feed"] if e["role"] == "business"]
    assert len(business) == 2                      # 商业官重算了一次
    assert business[-1]["score"] == 92.0           # 全押趋势热度 → 92×1.0


def test_decision_rejected_when_not_at_gate(client):
    """不在决策点提交决策 → 409 SESSION_NOT_AT_GATE"""
    sid = _create(client)
    state = client.get(f"/api/v1/reviews/{sid}").json()
    if state["pending_gate"] is None:
        r = client.post(f"/api/v1/reviews/{sid}/decision",
                        json={"action": "approve", "reason": "ok"})
        assert r.status_code in (409, 200)  # 极快机器上提交瞬间可能刚到门
        if r.status_code == 409:
            assert r.json()["detail"]["error"]["code"] == "SESSION_NOT_AT_GATE"
    # 收尾：无论竞态走到哪，按当前门通用驱动到终局，避免后台任务悬挂
    _drain_to_end(client, sid)


def test_session_not_found(client):
    assert client.get("/api/v1/reviews/sess_none").status_code == 404
    assert client.get("/api/v1/reviews/sess_none/report").status_code == 404
    r = client.post("/api/v1/reviews/sess_none/decision",
                    json={"action": "approve", "reason": "x"})
    assert r.status_code == 404


def test_question_action_roundtrip(client):
    """D4 question：门前提问 → qa 作答 → 回到同一门，不重跑委员"""
    sid = _create(client)
    _poll(client, sid, _at_gate("act1_gate"))

    r = client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "question"})
    assert r.status_code == 422  # 空问题必填
    r = client.post(f"/api/v1/reviews/{sid}/decision",
                    json={"action": "question", "question": "趋势数据源是什么？"})
    assert r.status_code == 200
    assert r.json()["mapped"]["action"] == "question"

    _poll(client, sid, _at_gate("act1_gate"))  # 答完回到同一门
    state = client.get(f"/api/v1/reviews/{sid}").json()
    roles = [e["role"] for e in state["live_feed"]]
    assert "qa" in roles
    assert roles.count("trend") == 1  # 未重跑
    _drain_to_end(client, sid)


def test_list_reviews(client):
    """D4 会议列表：任务中心/知识库数据源，含归档摘要与复盘轮数"""
    sid = _create(client)
    _drain_to_end(client, sid)

    r = client.get("/api/v1/reviews")
    assert r.status_code == 200
    items = {i["session_id"]: i for i in r.json()["reviews"]}
    assert sid in items
    item = items[sid]
    assert item["category"] == "解压玩具"
    assert item["status"] == "approved"
    assert item["created_at"]
    assert item["archive"]["status"] == "archived"
    assert item["retro_turns"] == 0


def test_report_not_ready_before_decision(client):
    """会议早期查建议书 → 404 REPORT_NOT_READY"""
    sid = _create(client)
    _poll(client, sid, _at_gate("act1_gate"))  # 保证还在 Gate1，决策未出
    r = client.get(f"/api/v1/reviews/{sid}/report")
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "REPORT_NOT_READY"
    # 收尾
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _poll(client, sid, _at_gate("human_gate"))
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _poll(client, sid, _at_gate("retro"))
    client.post(f"/api/v1/reviews/{sid}/decision", json={"action": "done"})
    _poll(client, sid, lambda s: s["status"] == "approved")


def test_historical_retro_chat_after_archive(client):
    """D3 历史复盘入口：归档后随时追问，问答追加 retro_logs 并累加轮数"""
    sid = _create(client)

    # 归档前追问 → 409 RETRO_NOT_READY
    _poll(client, sid, _at_gate("act1_gate"))
    r = client.post(f"/api/v1/reviews/{sid}/retro",
                    json={"question": "为什么是 Top1？"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"]["code"] == "RETRO_NOT_READY"

    # 驱动到终局（archive 在 Gate2 结论时即建档）
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _poll(client, sid, _at_gate("human_gate"))
    client.post(f"/api/v1/reviews/{sid}/decision",
                json={"action": "approve", "reason": "ok"})
    _drain_to_end(client, sid)

    # 归档后随时复盘：两轮追问都落 retro_logs，轮数累加
    for q in ("为什么第二名落选？", "下次类似品类该提高哪个权重？"):
        r = client.post(f"/api/v1/reviews/{sid}/retro", json={"question": q})
        assert r.status_code == 200
        assert r.json()["answer"]
    state = client.get(f"/api/v1/reviews/{sid}").json()
    assert len(state["retro_logs"]) == 2
    assert state["archive"]["retro_turns"] == 2

    # 空问题 → 422
    r = client.post(f"/api/v1/reviews/{sid}/retro", json={"question": "  "})
    assert r.status_code == 422
