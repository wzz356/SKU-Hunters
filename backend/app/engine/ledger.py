"""学习官台账读取端 — 历史档案反哺新会议（飞轮闭环的另一半）

写入端早已存在：learning_node 每场会议建档进 committee.db（方案/预测分/
AI 建议/人决策/复盘轮数/通过与否）。本模块补上读取端：

  query_analogs(category) → 新会议启动时按品类取历史相似案例
    → 商业官：history_analog 维度从此有真实材料（不再"无支撑"）
    → 创意官：被否方案做负例，避免重复提案

纪律：
- 台账故障绝不阻塞会议：任何异常返回 []
- store 延迟 import（模块 import 不触库）
- select_analogs 是纯函数，可离线测试
"""

from __future__ import annotations

from typing import Any

# 档案里对下游有用的字段（compact，防 prompt 膨胀）
_ANALOG_KEYS = (
    "proposal", "predicted_score", "ai_decision", "human_action",
    "status", "retro_turns",
)


def select_analogs(
    rows: list[dict[str, Any]], category: str, limit: int = 5,
) -> list[dict[str, Any]]:
    """纯函数：从 store.list_all() 的行里挑历史相似案例。

    rows 须为时间倒序（store.list_all 保证）。规则：
    - 只要已建档（archive 非空）的场次
    - 同品类（精确或互为子串）排前，其余按原序补足
    - 每条只保留 _ANALOG_KEYS + category
    """
    archived = [
        {
            **{k: (r.get("archive") or {}).get(k) for k in _ANALOG_KEYS},
            "category": (r.get("brief") or {}).get("category", ""),
        }
        for r in rows
        if r.get("archive")
    ]

    def _is_match(a: dict[str, Any]) -> bool:
        cat = a["category"]
        return bool(category and cat) and (category in cat or cat in category)

    matches = [a for a in archived if _is_match(a)]
    others = [a for a in archived if not _is_match(a)]
    return (matches + others)[:limit]


def query_analogs(category: str, limit: int = 5) -> list[dict[str, Any]]:
    """读台账 + 挑选；任何故障返回 []（会议不阻塞）"""
    try:
        from app import store

        return select_analogs(store.list_all(), category, limit=limit)
    except Exception:  # noqa: BLE001 — 台账故障降级为"无历史"，不阻塞评审
        return []


def format_analogs(analogs: list[dict[str, Any]]) -> list[str]:
    """压成 prompt 材料行（每个案例一行，人决策是核心信号）"""
    lines = []
    for a in analogs:
        score = a.get("predicted_score")
        score_txt = f"{float(score):.1f} 分" if isinstance(score, (int, float)) else "无评分"
        lines.append(
            f"  · {a.get('proposal') or '（未命名方案）'}（品类 {a.get('category') or '?'}）："
            f"预测 {score_txt}，AI 建议 {a.get('ai_decision') or '?'} / "
            f"人决策 {a.get('human_action') or '?'}，状态 {a.get('status') or '?'}，"
            f"复盘 {a.get('retro_turns') or 0} 轮"
        )
    return lines
