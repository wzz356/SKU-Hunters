"""异步边界并发回归测试 — 阻塞 LLM 调用不阻塞事件循环，两个请求同时推进"""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
from app.main import app
from app.planning import repository

BRIEF = {
    "theme": "异步边界测试",
    "category": "小风扇",
    "priceRange": [39, 99],
    "costLimit": 25,
}


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    snapshot = dict(repository._PLANS)
    repository._PLANS.clear()
    monkeypatch.setattr(repository, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(repository, "_STATE_FILE", tmp_path / "plans_state.json")
    monkeypatch.setattr(repository, "_LEGACY_STATE_FILE", tmp_path / "legacy.json")
    yield
    repository._PLANS.clear()
    repository._PLANS.update(snapshot)


@pytest.mark.asyncio
async def test_concurrent_review_requests_progress(monkeypatch):
    """两个 review 请求并发推进：阻塞 LLM 调用放线程池，不串行阻塞事件循环"""
    plan = repository.create_plan(BRIEF)
    plan_id = plan["plan_id"]

    call_times: list[float] = []
    lock = threading.Lock()

    def slow_complete(*args, **kwargs):
        with lock:
            call_times.append(time.time())
        time.sleep(0.4)  # 模拟阻塞 LLM 调用
        return "测试回答"

    monkeypatch.setattr("app.engine.llm.complete", slow_complete)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.time()
        resp1, resp2 = await asyncio.gather(
            client.post(f"/api/v1/plans/{plan_id}/review", json={"question": "q1"}),
            client.post(f"/api/v1/plans/{plan_id}/review", json={"question": "q2"}),
        )
        elapsed = time.time() - start

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(call_times) == 2

    # 两次阻塞调用时间重叠（并发，而非串行），证明 to_thread 生效
    overlap = abs(call_times[1] - call_times[0])
    assert overlap < 0.3, f"两次 LLM 调用未并发（间隔 {overlap:.3f}s）"

    # 总耗时约一次阻塞调用时长，而非两次串行
    assert elapsed < 0.7, f"总耗时 {elapsed:.3f}s，疑似串行阻塞"
