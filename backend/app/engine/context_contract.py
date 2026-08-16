"""Context 契约校验 — business/gtm Agent 的必需 Artifact 强制校验

原则（铁律的代码化）：
- 三官 Artifact 必须来自 state 中已过 schema 校验的产物，不能 LLM 重生成、不能读 Base 原始数据。
- 缺失 / None / 错误类型 → ContextContractError（fail-fast，阻断 Agent 调用）。
- 不允许用 mock fallback、空 dict、空 list 或 LLM 补全来掩盖缺失。
- risk_warnings=[] 是 OpportunityScore 内部合法值，不在本契约校验范围内。
- Pydantic 模型统一 model_dump(mode="json")；context 必须 JSON-safe。
- 不修改原始 state 对象或原始 Artifact。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ContextContractError(Exception):
    """Agent context 契约失败：缺少必需 Artifact 或类型错误"""

def _dump_if_model(value: Any) -> Any:
    """Pydantic 模型 → model_dump(mode="json")；其余原样返回"""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value

def _require_dict(context: dict[str, Any], key: str, who: str) -> dict[str, Any]:
    """校验必需 Artifact 是「非空 dict」，否则抛 ContextContractError"""
    value = context.get(key)
    if value is None:
        raise ContextContractError(f"{who} Context 缺少必需 Artifact：{key}")
    value = _dump_if_model(value)
    if not isinstance(value, dict):
        raise ContextContractError(
            f"{who} Context 的 {key} 类型错误：期望 dict，实际 {type(value).__name__}"
        )
    if not value:
        raise ContextContractError(f"{who} Context 的 {key} 为空 dict（不允许用空值掩盖缺失）")
    return value

def _require_list(context: dict[str, Any], key: str, who: str) -> list[Any]:
    """校验必需 Artifact 是「非空 list」，否则抛 ContextContractError"""
    value = context.get(key)
    if value is None:
        raise ContextContractError(f"{who} Context 缺少必需 Artifact：{key}")
    if not isinstance(value, list):
        raise ContextContractError(
            f"{who} Context 的 {key} 类型错误：期望 list，实际 {type(value).__name__}"
        )
    if not value:
        raise ContextContractError(f"{who} Context 的 {key} 为空 list（不允许用空值掩盖缺失）")
    return value

_BUSINESS_REQUIRED = ("feature_matrix", "user_sentiment", "ip_assessment")

def validate_business_context(context: dict[str, Any]) -> None:
    """business context 必须含三官 Artifact（feature_matrix / user_sentiment / ip_assessment）"""
    for key in _BUSINESS_REQUIRED:
        _require_dict(context, key, "business")

def validate_gtm_context(context: dict[str, Any]) -> None:
    """gtm context 必须含 opportunity_scores（list）与 ip_assessment（dict）"""
    _require_list(context, "opportunity_scores", "gtm")
    _require_dict(context, "ip_assessment", "gtm")
