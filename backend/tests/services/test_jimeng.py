"""即梦文生图客户端测试 — 签名结构 + 降级纪律（不触网）

降级纪律与 LLM 客户端一致：未配置 Key 或任何调用失败 → 返回 fallback，
不阻塞企划卡生成。火山 AK/SK 到位前的保护网。
"""

import json

import pytest
from app.services import jimeng


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """确保测试绝不读真实 .env 里的 AK/SK"""
    monkeypatch.delenv("VOLC_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("VOLC_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("JIMENG_REQ_KEY", raising=False)
    monkeypatch.delenv("JIMENG_TIMEOUT", raising=False)


# ── 配置与降级 ───────────────────────────────────────────


def test_config_none_without_keys():
    assert jimeng._get_config() is None


def test_config_reads_keys_and_defaults(monkeypatch):
    monkeypatch.setenv("VOLC_ACCESS_KEY_ID", "AK_TEST")
    monkeypatch.setenv("VOLC_SECRET_ACCESS_KEY", "SK_TEST")
    cfg = jimeng._get_config()
    assert cfg["ak"] == "AK_TEST"
    assert cfg["req_key"] == "jimeng_t2i_v40"  # 默认即梦 4.0
    assert cfg["timeout"] == 60.0


def test_generate_returns_fallback_without_keys():
    assert jimeng.generate_concept_image("一只库洛米风扇", fallback="/assets/frozen.png") == "/assets/frozen.png"
    assert jimeng.generate_concept_image("一只库洛米风扇") is None


# ── V4 签名结构 ──────────────────────────────────────────


def test_signed_request_structure():
    req = jimeng._signed_request("AK_TEST", "SK_TEST", "CVSync2AsyncSubmitTask", {"prompt": "测试"})
    assert req.method == "POST"
    assert "Action=CVSync2AsyncSubmitTask" in str(req.url)
    assert f"Version={jimeng._VERSION}" in str(req.url)

    auth = req.headers["Authorization"]
    assert auth.startswith("HMAC-SHA256 Credential=AK_TEST/")
    assert f"/{jimeng._REGION}/{jimeng._SERVICE}/request" in auth
    assert "SignedHeaders=content-type;host;x-content-sha256;x-date" in auth
    assert "Signature=" in auth

    assert req.headers["X-Content-Sha256"]  # payload hash 存在
    assert json.loads(req.content.decode("utf-8")) == {"prompt": "测试"}


def test_signature_changes_with_body():
    r1 = jimeng._signed_request("AK", "SK", "Act", {"prompt": "A"})
    r2 = jimeng._signed_request("AK", "SK", "Act", {"prompt": "B"})
    assert r1.headers["X-Content-Sha256"] != r2.headers["X-Content-Sha256"]


# ── _post 错误处理 ───────────────────────────────────────


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send(self, req):
        return _FakeResp(self._payload)


def test_post_raises_on_business_error_code(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "Client", lambda timeout: _FakeClient({"code": 50400, "message": "参数错误"}))
    with pytest.raises(RuntimeError, match="50400"):
        jimeng._post("AK", "SK", "Act", {})


def test_post_accepts_success_code_10000(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "Client", lambda timeout: _FakeClient({"code": 10000, "data": {"ok": 1}}))
    assert jimeng._post("AK", "SK", "Act", {})["data"] == {"ok": 1}


# ── 完整流程（mock _post，不触网）─────────────────────────


def _with_keys(monkeypatch, timeout="5"):
    monkeypatch.setenv("VOLC_ACCESS_KEY_ID", "AK_TEST")
    monkeypatch.setenv("VOLC_SECRET_ACCESS_KEY", "SK_TEST")
    monkeypatch.setenv("JIMENG_TIMEOUT", timeout)
    monkeypatch.setattr(jimeng.time, "sleep", lambda s: None)


def test_full_flow_submit_then_done(monkeypatch):
    _with_keys(monkeypatch)
    calls = []

    def fake_post(ak, sk, action, body):
        calls.append((action, body))
        if action == jimeng._ACTION_SUBMIT:
            return {"data": {"task_id": "task-123"}}
        return {"data": {"status": "done", "image_urls": ["https://img.example/fan.png"]}}

    monkeypatch.setattr(jimeng, "_post", fake_post)
    url = jimeng.generate_concept_image("产品概念渲染图，库洛米风扇", fallback="fb")
    assert url == "https://img.example/fan.png"

    submit_body = calls[0][1]
    assert submit_body["req_key"] == "jimeng_t2i_v40"
    assert submit_body["width"] == 1024 and submit_body["height"] == 1024
    assert submit_body["prompt"] == "产品概念渲染图，库洛米风扇"
    # 查询轮询带上了同一个 task_id
    assert calls[1][1]["task_id"] == "task-123"


def test_done_without_urls_returns_fallback(monkeypatch):
    _with_keys(monkeypatch)
    monkeypatch.setattr(jimeng, "_post", lambda *a: (
        {"data": {"task_id": "t"}} if a[2] == jimeng._ACTION_SUBMIT
        else {"data": {"status": "done", "image_urls": []}}
    ))
    assert jimeng.generate_concept_image("p", fallback="fb") == "fb"


def test_not_found_returns_fallback(monkeypatch):
    _with_keys(monkeypatch)
    monkeypatch.setattr(jimeng, "_post", lambda *a: (
        {"data": {"task_id": "t"}} if a[2] == jimeng._ACTION_SUBMIT
        else {"data": {"status": "not_found"}}
    ))
    assert jimeng.generate_concept_image("p", fallback="fb") == "fb"


def test_timeout_returns_fallback(monkeypatch):
    _with_keys(monkeypatch, timeout="0")  #  deadline 立即到期
    monkeypatch.setattr(jimeng, "_post", lambda *a: (
        {"data": {"task_id": "t"}} if a[2] == jimeng._ACTION_SUBMIT
        else {"data": {"status": "in_queue"}}
    ))
    assert jimeng.generate_concept_image("p", fallback="fb") == "fb"


def test_any_exception_returns_fallback(monkeypatch):
    _with_keys(monkeypatch)

    def boom(*args):
        raise ConnectionError("网络不可达")

    monkeypatch.setattr(jimeng, "_post", boom)
    assert jimeng.generate_concept_image("p", fallback="fb") == "fb"
