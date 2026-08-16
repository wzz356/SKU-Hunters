"""商品策略 · 成本校验规则（毛利率红线 + 定价解析）

校验规则写死，LLM 不得自由发挥；fixture 模式三方向均已离线校验通过，
live 模式校验不通过时由管线打回创意环节重出方案（最多 2 轮，仍不过则人工介入）。
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.planning import CostCheck

# 名创小家电品类毛利率红线
MIN_GROSS_MARGIN = 0.30


def _parse_price(price_str: str) -> float | None:
    """从「59 元」「49-99 元」等字符串里提取首个数字作为定价"""
    m = re.search(r"(\d+(?:\.\d+)?)", price_str)
    return float(m.group(1)) if m else None


def cost_check(plan_card: dict[str, Any], cost_limit: float) -> CostCheck:
    """商品策略校验回环：定价毛利率低于红线 → 打回创意设计调整

    fixture 模式下三个方向均已离线校验通过；live 模式校验不通过时
    由管线打回创意环节重出方案（最多 2 轮，仍不过则标记人工介入）。
    """
    price = _parse_price(plan_card.get("pricing", {}).get("price", ""))
    if price is None:
        return CostCheck(passed=False, reason="定价缺失，无法校验")
    margin = (price - cost_limit) / price
    return CostCheck(
        passed=margin >= MIN_GROSS_MARGIN,
        price=price,
        cost_limit=cost_limit,
        margin=round(margin, 3),
        reason=(
            f"毛利率 {margin:.0%} ≥ 红线 {MIN_GROSS_MARGIN:.0%}，校验通过"
            if margin >= MIN_GROSS_MARGIN
            else f"毛利率 {margin:.0%} 低于红线 {MIN_GROSS_MARGIN:.0%}，打回创意环节调整（降本或调价）"
        ),
    )
