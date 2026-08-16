"""从 Feishu Base 记录构建实时看板数据。

本模块只做确定性聚合，不把互动量伪装成销量，也不在数据不足时回退到 fixture。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any

from app.data.base_adapter import BaseDataAdapter
from app.schemas.base_data import BaseRecord

_PRICE_RE = re.compile(r"\d+(?:\.\d+)?")
_PLATFORM_LABELS = {
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "tiktok": "TikTok",
    "bilibili": "B站",
    "taobao": "淘宝",
}


def _numbers(value: str | None) -> list[float]:
    return [float(item) for item in _PRICE_RE.findall(value or "")]


def _price(value: str | None) -> float | None:
    values = _numbers(value)
    return values[0] if values else None


def _price_band(value: str | None) -> str:
    price = _price(value)
    if price is None:
        return "未标注"
    if price < 50:
        return "0-50元"
    if price < 100:
        return "50-100元"
    if price < 150:
        return "100-150元"
    return "150元以上"


def _week(value: str) -> str:
    current = date.fromisoformat(value)
    iso = current.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _category_rows(records: list[BaseRecord]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for record in records:
        if not record.category:
            continue
        counts[record.category] += 1
        if record.heat_index is not None:
            buckets[record.category].append(record.heat_index)
    rows = []
    for category, count in counts.items():
        heats = buckets[category]
        rows.append({
            "name": category,
            "heat": round(sum(heats) / len(heats), 2) if heats else 0,
            "recordCount": count,
        })
    return sorted(rows, key=lambda row: (row["heat"], row["recordCount"]), reverse=True)[:12]


def _hot_rows(records: list[BaseRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str | None, str | None], list[BaseRecord]] = defaultdict(list)
    for record in records:
        if record.heat_index is not None:
            groups[(record.keyword, record.brand, record.price_range)].append(record)
    ranked = []
    for items in groups.values():
        best = max(items, key=lambda item: item.heat_index or 0)
        ranked.append({
            "name": best.keyword,
            "brand": best.brand or "未标注",
            "price": _price(best.price_range),
            "point": (best.summary or "暂无摘要")[:80],
            "heat": round(best.heat_index or 0, 2),  # 热度指标，非销量
            "recordCount": len(items),
        })
    ranked.sort(key=lambda row: row["heat"], reverse=True)
    for index, row in enumerate(ranked[:10], start=1):
        row["rank"] = index
    return ranked[:10]


def _voice_trend(records: list[BaseRecord]) -> dict[str, list[Any]]:
    weekly: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        if record.platform.value not in {"xiaohongshu", "douyin", "tiktok"}:
            continue
        weekly[_week(record.record_date)][record.platform.value] += 1
    weeks = sorted(weekly)[-12:]
    return {
        "weeks": weeks,
        "xhs": [weekly[week].get("xiaohongshu", 0) for week in weeks],
        "douyin": [
            weekly[week].get("douyin", 0) + weekly[week].get("tiktok", 0)
            for week in weeks
        ],
        "platformLabels": {"xhs": "小红书记录数", "douyin": "抖音/TikTok记录数"},
    }


def _price_bands(records: list[BaseRecord]) -> list[dict[str, Any]]:
    labels = ["0-50元", "50-100元", "100-150元", "150元以上"]
    counts = Counter(_price_band(record.price_range) for record in records)
    total = sum(counts[label] for label in labels)
    if not total:
        return []
    return [
        {"band": label, "pct": round(counts[label] / total * 100, 1), "recordCount": counts[label]}
        for label in labels
    ]


def build_live_data_board(adapter: BaseDataAdapter | None = None) -> dict[str, Any]:
    """读取 Feishu Base 全量明细并构建看板。

    ``BaseDataAdapter`` 自带分页、缓存和字段归一化；这里不直接访问 provider。
    """
    source = adapter or BaseDataAdapter()
    records = source.search_all("")
    if not records:
        raise ValueError("Feishu Base 明细表没有可用于看板的数据")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "categoryRank": _category_rows(records),
        "hotProducts": _hot_rows(records),
        "voiceTrend": _voice_trend(records),
        "priceBands": _price_bands(records),
        "dataSource": "feishu",
        "sourceLabel": "飞书 Base · SKU-Hunters 采集数据",
        "recordCount": len(records),
        "generatedAt": now,
        "platformLabels": _PLATFORM_LABELS,
    }
