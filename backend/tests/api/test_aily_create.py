"""Aily 发起企划端点测试 — 异步流程 + 通知 fail-soft（不碰真实飞书 API）"""

from __future__ import annotations

import pytest
from app.api.planning import router
from app.planning import pipeline
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(router)

BRIEF = {
    "theme": "2027夏季户外生活系列",
    "category": "小风扇",
    "price_range": [39, 99],
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_aily_create_returns_running_and_flow_completes(client, monkeypatch):
    """立即返回 running；后台任务跑完洞察+机会卡并触发通知（通知被 mock）"""
    pushed = []

    def _fake_notify(plan, opportunities):
        pushed.append((plan["plan_id"], len(opportunities)))
        return True

    monkeypatch.setattr("feishu.notify.notify_opportunities_ready", _fake_notify)

    r = client.post("/api/v1/plans/aily-create", json=BRIEF)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    plan_id = body["plan_id"]

    # TestClient 会在响应返回前执行 BackgroundTasks
    plan = pipeline.get_plan(plan_id)
    assert plan is not None
    assert plan["status"] == "opportunities_ready"
    assert pushed == [(plan_id, 3)]  # 3 张机会卡进入推送


def test_aily_create_notify_failure_keeps_task(client, monkeypatch):
    """推送抛异常不影响任务：后台流程 fail-soft，机会卡照常就绪"""

    def _boom(plan, opportunities):
        raise RuntimeError("飞书挂了")

    monkeypatch.setattr("feishu.notify.notify_opportunities_ready", _boom)

    r = client.post("/api/v1/plans/aily-create", json=BRIEF)
    assert r.status_code == 202, r.text
    plan = pipeline.get_plan(r.json()["plan_id"])
    assert plan["status"] == "opportunities_ready"


def test_aily_create_invalid_brief_422(client):
    """缺必填字段（theme/category）→ 422，不建档"""
    r = client.post("/api/v1/plans/aily-create", json={"market": "CN"})
    assert r.status_code == 422


def test_aily_create_compatible_wrapped_brief(client, monkeypatch):
    """兼容 {brief: {...}} 包装形式（与 POST /plans 行为一致）"""
    monkeypatch.setattr(
        "feishu.notify.notify_opportunities_ready", lambda p, o: True
    )
    r = client.post("/api/v1/plans/aily-create", json={"brief": BRIEF})
    assert r.status_code == 202, r.text
