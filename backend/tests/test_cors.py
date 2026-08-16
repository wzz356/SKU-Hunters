"""CORS 配置测试 — 允许来源 / 非法来源 / 通配符拒绝"""

from __future__ import annotations

import pytest
from app.main import _load_cors_origins, app
from fastapi.testclient import TestClient


def test_cors_allows_localhost_5173():
    client = TestClient(app)
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_127_0_0_1_4173():
    client = TestClient(app)
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:4173"


def test_cors_rejects_unknown_origin():
    client = TestClient(app)
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


def test_cors_wildcard_rejected(monkeypatch):
    """显式传入 * 必须拒绝（与 allow_credentials=True 冲突）"""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        _load_cors_origins()


def test_cors_default_origins():
    """未配置时返回四个本地开发来源"""
    assert _load_cors_origins() == [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    ]
