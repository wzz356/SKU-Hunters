"""Strict Real Mode —— 生产环境严格真实模式

设计纪律（对应 Stage 11B）：
- 生产（APP_ENV=production）默认禁止 Mock / fixture / 演示数据，仅显式
  ALLOW_MOCK=true 才放行；非生产（test/dev）默认允许 Mock（自动化测试用）。
- 严格模式下：
  * LLM / 数据源失败 → 阻断（抛错），不回退 MockAgent
  * 真实数据不足 → unavailable（合法契约态），不用演示内容填满页面
  * 字段缺失 → unknown
  * 禁止运行 fixture / demo 任务
- 使用真实飞书数据的 deterministic（确定性聚合）Agent 不属于 Mock，可保留。

本模块为单一事实源，不依赖 FastAPI；供 Agent 注册表、真实 Agent 内部
fallback、企划服务（PLANNING_DEFAULT_MODE / fixture 禁止）、健康检查共用。
"""

from __future__ import annotations

import os


class StrictModeError(RuntimeError):
    """严格真实模式下禁止回退 Mock/演示数据，或使用未授权 provider / 创建 fixture 任务"""


def app_env() -> str:
    return os.getenv("APP_ENV", "").strip().lower()


def mock_allowed() -> bool:
    """生产默认禁止 Mock（仅显式 ALLOW_MOCK=true 放行）；非生产默认允许 Mock。"""
    if app_env() == "production":
        return os.getenv("ALLOW_MOCK", "false").strip().lower() == "true"
    return os.getenv("ALLOW_MOCK", "true").strip().lower() == "true"


def strict_real() -> bool:
    """是否处于严格真实模式（生产 + 未显式允许 Mock）。"""
    return not mock_allowed()


def require_mock_allowed(where: str) -> None:
    """在 Mock/演示数据回退点调用：严格模式抛错阻断，否则放行。"""
    if strict_real():
        raise StrictModeError(
            f"严格真实模式已启用（APP_ENV=production 且 ALLOW_MOCK=false），"
            f"禁止回退 Mock/演示数据：{where}"
        )


def resolve_provider(role: str, env_key: str, allowed: tuple[str, ...] = ("real",)) -> str:
    """解析某角色 provider；严格模式下校验必须为 allowed 内真实实现，否则抛错阻断。

    allowed 约定：仅 LLM 官 → ("real",)；含确定性官 → ("real", "deterministic")。
    """
    val = (os.getenv(env_key) or os.getenv("AGENT_PROVIDER", "mock")).strip().lower()
    if strict_real() and val not in allowed:
        raise StrictModeError(
            f"严格真实模式要求「{role}」使用真实实现"
            f"（{env_key}={'/'.join(allowed)} 或 AGENT_PROVIDER=real），"
            f"当前 provider={val or '未设置'}"
        )
    return val


def planning_default_mode() -> str:
    """企划默认任务模式：严格模式强制 live；否则取 PLANNING_DEFAULT_MODE（默认 crawled）。

    crawled = 真实采集 + LLM 分析（Stage 1-4 主链路）；fixture = 冻结演示样例；live = 飞书实时。
    """
    if strict_real():
        return "live"
    return os.getenv("PLANNING_DEFAULT_MODE", "crawled").strip().lower()


def allow_fixture_tasks() -> bool:
    """严格模式禁止创建/打开 fixture 任务；非严格允许（测试/演示）。"""
    return not strict_real()


def is_demo_hidden() -> bool:
    """严格模式隐藏 demo 演示任务（列表与详情均不可见）。"""
    return strict_real()
