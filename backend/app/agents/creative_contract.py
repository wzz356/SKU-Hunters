"""创意官输出契约校验 — 四项确定性硬校验

对应剧本 2.2 硬校验规则（不通过则打回重生成）：
1. source_map 覆盖三方 Artifact 各至少一条，来源真实（空 Artifact / 缺失 / 引用不存在 → 失败）
2. 方案间「形态 / 场景 / 价位」至少两维不同（微调变体不算独立方案）
3. price_band 不得超出 Brief 预算区间（解析失败明确失败，不用模糊字符串比较）
4. product_form 必须来自用户官形态信号（不得仅凭 LLM 自由生成就放行）

均为纯函数，确定性、可测试；校验发生在创意官输出边界，先于 ProposalSet.model_validate。
"""

from __future__ import annotations

import re
from typing import Any


class ContractError(Exception):
    """创意官输出契约失败"""

# 预算带 → 建议价格带（名创优品实际价位段；复用现有映射，抽成纯数值区间）
_BUDGET_BAND: dict[str, tuple[float, float]] = {
    "low": (9.9, 29),
    "mid": (29, 69),
    "high": (69, 149),
}

_ARTIFACT_NAMES = ("FeatureMatrix", "UserSentiment", "IPAssessment")

def parse_price_band(price_band: str) -> tuple[float, float] | None:
    """解析价格带字符串，如 '¥39-59' → (39.0, 59.0)；解析失败返回 None"""
    nums = re.findall(r"\d+(?:\.\d+)?", price_band or "")
    if len(nums) < 2:
        return None
    lo, hi = float(nums[0]), float(nums[1])
    return (min(lo, hi), max(lo, hi))

def _user_signal_text(user_sentiment: dict[str, Any] | None) -> str:
    """从用户官 Artifact 提取形态信号文本（summary + 痛点 + 动机标签）"""
    if not user_sentiment or not isinstance(user_sentiment, dict):
        return ""
    parts = [str(user_sentiment.get("summary", ""))]
    for pp in user_sentiment.get("pain_points", []) or []:
        if isinstance(pp, dict):
            parts.append(str(pp.get("description", "")))
    for tag in user_sentiment.get("motivation_tags", []) or []:
        parts.append(str(tag))
    return " ".join(p for p in parts if p)

def _has_signal_basis(form: str, signal: str) -> bool:
    """product_form 是否在信号文本中有依据（精确子串匹配，不用模糊退化）"""
    return form in signal

def validate_source_map_coverage(
    proposals: list[dict[str, Any]],
    feature_matrix: dict[str, Any] | None,
    user_sentiment: dict[str, Any] | None,
    ip_assessment: dict[str, Any] | None,
) -> None:
    """校验 source_map 覆盖三官 Artifact，且来源真实（非空 Artifact）"""
    artifacts = {
        "FeatureMatrix": feature_matrix,
        "UserSentiment": user_sentiment,
        "IPAssessment": ip_assessment,
    }
    for name, art in artifacts.items():
        if not art or not isinstance(art, dict):
            raise ContractError(f"创意官输出缺少 {name} 来源 Artifact（空 Artifact 不得生成方案）")
    for p in proposals:
        name = p.get("name", "?")
        refs = [r for r in p.get("source_map", []) if isinstance(r, dict)]
        covered = {r.get("artifact") for r in refs}
        missing = set(_ARTIFACT_NAMES) - covered
        if missing:
            raise ContractError(f"方案 {name} source_map 未覆盖 {sorted(missing)}")
        for r in refs:
            a = r.get("artifact")
            if a not in _ARTIFACT_NAMES:
                raise ContractError(f"方案 {name} source_map 引用不存在的 artifact: {a!r}")

def validate_proposal_distinctness(proposals: list[dict[str, Any]]) -> None:
    """校验方案间至少两维差异（形态 product_form / 场景 target_segment / 价位 price_band）"""
    for i in range(len(proposals)):
        for j in range(i + 1, len(proposals)):
            a, b = proposals[i], proposals[j]
            diffs = sum([
                a.get("product_form") != b.get("product_form"),
                a.get("target_segment") != b.get("target_segment"),
                a.get("price_band") != b.get("price_band"),
            ])
            if diffs < 2:
                raise ContractError(
                    f"方案 {a.get('name')} 与 {b.get('name')} 不足两维差异（仅 {diffs} 维）"
                )

def validate_price_bands(proposals: list[dict[str, Any]], budget_range: str) -> None:
    """校验每个方案价格带落在预算区间内；解析失败明确失败"""
    lo, hi = _BUDGET_BAND.get(budget_range, _BUDGET_BAND["mid"])
    for p in proposals:
        name = p.get("name", "?")
        band = parse_price_band(p.get("price_band", ""))
        if band is None:
            raise ContractError(f"方案 {name} 价格带解析失败: {p.get('price_band')!r}")
        if band[0] < lo or band[1] > hi:
            raise ContractError(
                f"方案 {name} 价格带 {p.get('price_band')} 超出预算区间 [{lo}, {hi}]"
            )

def validate_product_form_basis(
    proposals: list[dict[str, Any]], user_sentiment: dict[str, Any] | None
) -> None:
    """校验 product_form 有用户官形态信号依据（不得仅凭 LLM 自由生成）"""
    signal = _user_signal_text(user_sentiment)
    if not signal:
        raise ContractError("用户官 Artifact 无形态信号，无法校验 product_form 依据")
    for p in proposals:
        name = p.get("name", "?")
        form = (p.get("product_form") or "").strip()
        if not form:
            raise ContractError(f"方案 {name} product_form 为空")
        if not _has_signal_basis(form, signal):
            raise ContractError(f"方案 {name} product_form {form!r} 无用户官形态信号依据")

def validate_proposals(
    proposals: list[dict[str, Any]],
    brief: dict[str, Any],
    feature_matrix: dict[str, Any] | None,
    user_sentiment: dict[str, Any] | None,
    ip_assessment: dict[str, Any] | None,
) -> None:
    """创意官输出四项契约校验（总入口）"""
    validate_source_map_coverage(proposals, feature_matrix, user_sentiment, ip_assessment)
    validate_proposal_distinctness(proposals)
    validate_price_bands(proposals, brief.get("budget_range", "mid"))
    validate_product_form_basis(proposals, user_sentiment)
