"""Stage 11B — Strict Real Mode 测试

覆盖：mock_allowed 默认值、resolve_provider 严格校验、Mock fallback 阻断、
企划默认模式强制 live、禁止 fixture 任务、demo 隐藏、健康检查。
"""
import pytest

from app.engine.strict_mode import (
    StrictModeError,
    allow_fixture_tasks,
    is_demo_hidden,
    mock_allowed,
    planning_default_mode,
    require_mock_allowed,
    resolve_provider,
    strict_real,
)


def _set(monkeypatch, **kw):
    for k, v in kw.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


# ── mock_allowed 默认值 ──────────────────────────
def test_mock_allowed_production_defaults_false(monkeypatch):
    _set(monkeypatch, APP_ENV="production")
    _set(monkeypatch, ALLOW_MOCK=None)
    assert mock_allowed() is False
    assert strict_real() is True


def test_mock_allowed_production_explicit_true(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="true")
    assert mock_allowed() is True
    assert strict_real() is False


def test_mock_allowed_nonproduction_defaults_true(monkeypatch):
    _set(monkeypatch, APP_ENV=None)
    _set(monkeypatch, ALLOW_MOCK=None)
    assert mock_allowed() is True


# ── resolve_provider 严格校验 ─────────────────────
def test_resolve_provider_blocks_mock_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false")
    with pytest.raises(StrictModeError):
        resolve_provider("趋势官", "TREND_AGENT_PROVIDER")


def test_resolve_provider_allows_real_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false", TREND_AGENT_PROVIDER="real")
    assert resolve_provider("趋势官", "TREND_AGENT_PROVIDER") == "real"


def test_resolve_provider_allows_deterministic_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false", GTM_AGENT_PROVIDER="deterministic")
    assert resolve_provider("GTM官", "GTM_AGENT_PROVIDER", ("real", "deterministic")) == "deterministic"


def test_resolve_provider_allows_mock_outside_strict(monkeypatch):
    _set(monkeypatch, APP_ENV=None)
    assert resolve_provider("趋势官", "TREND_AGENT_PROVIDER") == "mock"


# ── require_mock_allowed 阻断 ─────────────────────
def test_require_mock_allowed_raises_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false")
    with pytest.raises(StrictModeError):
        require_mock_allowed("测试回退")


def test_require_mock_allowed_pass_outside_strict(monkeypatch):
    _set(monkeypatch, APP_ENV=None)
    require_mock_allowed("测试回退")  # 不抛


# ── 企划默认模式 / fixture 禁止 / demo 隐藏 ───────
def test_planning_default_mode_forced_live_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false", PLANNING_DEFAULT_MODE="fixture")
    assert planning_default_mode() == "live"


def test_planning_default_mode_respects_env_outside_strict(monkeypatch):
    _set(monkeypatch, APP_ENV=None, PLANNING_DEFAULT_MODE="fixture")
    assert planning_default_mode() == "fixture"


def test_allow_fixture_and_demo_hidden_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false")
    assert allow_fixture_tasks() is False
    assert is_demo_hidden() is True


def test_allow_fixture_outside_strict(monkeypatch):
    _set(monkeypatch, APP_ENV=None)
    assert allow_fixture_tasks() is True
    assert is_demo_hidden() is False


# ── create_plan 严格行为（不落盘，避免污染状态文件）──
@pytest.mark.usefixtures("_no_state_save")
def test_create_plan_fixture_blocked_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false")
    from app.planning.repository import create_plan

    with pytest.raises(StrictModeError):
        create_plan({"theme": "t", "category": "小风扇", "mode": "fixture"})


@pytest.mark.usefixtures("_no_state_save")
def test_create_plan_live_allowed_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false")
    from app.planning.repository import create_plan

    p = create_plan({"theme": "t", "category": "小风扇", "mode": "live"})
    assert p["mode"] == "live"


@pytest.mark.usefixtures("_no_state_save")
def test_create_plan_default_live_in_strict(monkeypatch):
    _set(monkeypatch, APP_ENV="production", ALLOW_MOCK="false", PLANNING_DEFAULT_MODE="fixture")
    from app.planning.repository import create_plan

    p = create_plan({"theme": "t", "category": "小风扇"})
    assert p["mode"] == "live"


# ── fixture 防止污染状态文件 ─────────────────────
@pytest.fixture
def _no_state_save(monkeypatch):
    """禁止 _save_state 落盘，隔离测试对 plans_state.json 的影响"""
    import app.planning.repository as repo

    monkeypatch.setattr(repo, "_save_state", lambda: None)
