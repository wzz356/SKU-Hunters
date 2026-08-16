"""基于 Feishu Base 明细生成不带猜测的实时洞察结构。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any

from app.data.base_adapter import (
    BaseDataAdapter,
    BaseProviderError,
    BaseUnavailable,
    category_matches,
    normalize_category,
)
from app.schemas.base_data import BaseRecord


def _matches_category(record: BaseRecord, category: str) -> bool:
    target = (category or "").strip().lower()
    if not target:
        return True
    # 父品类：明细 category 按子串规则匹配（如「风扇」匹配所有含「扇」子品类）
    if category_matches(record.category, category):
        return True
    values = (record.keyword,)
    return any(target in (value or "").lower() or (value or "").lower() in target for value in values)

def _records_for_category(adapter: BaseDataAdapter, category: str) -> list[BaseRecord]:
    exact = adapter.search_all("", category=category)
    if exact:
        return exact
    return [record for record in adapter.search_all("") if _matches_category(record, category)]

def _normalize_pain_points(raw: Any) -> list[dict[str, Any]]:
    """汇总表 pain_points → 前端契约 [{"text": str, "count": number}]

    再次过滤非法条目：仅接受 list；每项须 dict；text 非空字符串；count 可转非负数。
    保证前端永远拿到 list[dict]，不伪造、不抛异常。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        text = raw_text.strip()
        if not text:
            continue
        count = item.get("count")
        if count is None:
            continue
        try:
            count_f = float(count)
        except (ValueError, TypeError):
            continue
        if count_f < 0:
            continue
        out.append({"text": text, "count": count_f})
    return out


def _normalize_scenes(raw: Any) -> list[dict[str, Any]]:
    """汇总表 scenes → 前端契约 [{"name": str, "value": number}]

    再次过滤非法条目：仅接受 list；每项须 dict；name 非空字符串；value 可转非负数。
    保证前端永远拿到 list[dict]，不伪造、不抛异常。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        name = raw_name.strip()
        if not name:
            continue
        value = item.get("value")
        if value is None:
            continue
        try:
            value_f = float(value)
        except (ValueError, TypeError):
            continue
        if value_f < 0:
            continue
        out.append({"name": name, "value": value_f})
    return out


def _price(value: str | None) -> float:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(match.group()) if match else 0.0

def _price_bands(records: list[BaseRecord]) -> list[dict[str, Any]]:
    labels = ("0-50元", "50-100元", "100-150元", "150元以上")
    counts = Counter()
    for record in records:
        price = _price(record.price_range)
        if price <= 0:
            continue
        counts["0-50元" if price < 50 else "50-100元" if price < 100 else "100-150元" if price < 150 else "150元以上"] += 1
    total = sum(counts.values())
    if not total:
        return []
    return [{"band": label, "pct": round(counts[label] / total * 100, 1)} for label in labels]

def build_live_insight_bundle(
    category: str,
    brief: dict[str, Any] | None = None,
    adapter: BaseDataAdapter | None = None,
) -> dict[str, Any]:
    """从 Feishu Base 生成五看洞察；未接入的字段保持空值。"""
    source = adapter or BaseDataAdapter()
    # 企划层品类归一化：旧任务「小风扇」等含「扇」子品类统一为父品类「风扇」
    category = normalize_category(category) or ""
    records = _records_for_category(source, category)
    if not records:
        raise ValueError(f"Feishu Base 没有匹配品类：{category}")

    # 快照统一：明细与汇总读取同一快照，避免混用；有多个快照时取最新并只保留该快照记录
    snapshot_ids = sorted({record.snapshot_id for record in records if record.snapshot_id})
    selected_snapshot = snapshot_ids[-1] if snapshot_ids else None
    if selected_snapshot is not None:
        records = [record for record in records if record.snapshot_id == selected_snapshot]

    # 汇总表读取（与明细同一快照；失败不阻断，保持空值并记录原因，不调用 LLM/不估算）
    summary: dict[str, Any] | None = None
    summary_error: str | None = None
    try:
        summary = source.get_summary(category=category, snapshot_id=selected_snapshot)
    except (BaseUnavailable, BaseProviderError, ValueError) as exc:
        summary = None
        summary_error = str(exc)

    pain_points = _normalize_pain_points((summary or {}).get("pain_points"))
    scenes = _normalize_scenes((summary or {}).get("scenes"))
    evidence = source.build_evidence_refs(records)
    dates = sorted(record.record_date for record in records)
    weeks: dict[str, list[float]] = defaultdict(list)
    platform_heats: dict[str, list[float]] = defaultdict(list)
    keyword_counts: Counter[str] = Counter()
    for record in records:
        current = date.fromisoformat(record.record_date)
        iso = current.isocalendar()
        weeks[f"{iso.year}-W{iso.week:02d}"].append(record.heat_index or 0)
        platform_heats[record.platform.value].append(record.heat_index or 0)
        keyword_counts[record.keyword] += 1

    week_labels = sorted(weeks)
    trend_signals = []
    for platform, heats in sorted(platform_heats.items(), key=lambda item: sum(item[1]), reverse=True):
        label = {"xiaohongshu": "小红书", "tiktok": "TikTok", "bilibili": "B站", "taobao": "淘宝"}.get(platform, platform)
        trend_signals.append({
            "name": f"{label}采集热度",
            "metric": f"{len(heats)} 条记录，平均归一化热度 {sum(heats) / len(heats):.1f}",
            "period": f"{dates[0]} 至 {dates[-1]}",
            "domains": [category],
            "opportunity": "基于真实采集记录，待人工结合内容摘要判断机会",
        })

    top_records = sorted(records, key=lambda record: record.heat_index or 0, reverse=True)
    quotes = [
        {"text": record.summary, "source": record.source_url}
        for record in top_records
        if record.summary and record.source_url
    ][:5]
    products = [
        {
            "name": record.keyword,
            "price": _price(record.price_range),
            "imageUrl": "",
            "sellingPoint": record.summary[:80] if record.summary else "",
            "design": 0,
        }
        for record in top_records[:8]
    ]
    hit_products = [
        {
            "name": record.keyword,
            "index": round(record.heat_index or 0, 2),
            "factors": [record.platform.value],
            "note": record.source_url or "飞书 Base 记录（无来源链接）",
        }
        for record in top_records[:4]
    ]
    ip_records = sorted(
        [record for record in source.search_all("") if record.category == "IP"],
        key=lambda record: record.heat_index or 0,
        reverse=True,
    )[:5]

    generated_at = datetime.now(timezone.utc).isoformat()

    return {
        "trendRadar": {
            "processLog": [
                "数据源：飞书 Base 实时明细",
                f"读取 {len(records)} 条匹配「{category}」的采集记录",
                "热度由 BaseRecord.heat_index 聚合，未接入字段不做推断",
            ],
            "signals": trend_signals[:5],
            "heatCurve": {
                "weeks": week_labels,
                "series": [{"name": category, "data": [round(sum(weeks[week]) / len(weeks[week]), 2) for week in week_labels]}],
            },
            "hotWords": [word for word, _ in keyword_counts.most_common(10)],
        },
        "consumerVoice": {
            "processLog": _consumer_process_log(pain_points, scenes, summary_error),
            "painPoints": pain_points,
            "scenes": scenes,
            "quotes": quotes,
            "summary": _consumer_summary(pain_points, scenes, summary_error),
        },
        "competitiveMap": {
            "processLog": [
                "数据源：飞书 Base 实时明细",
                "价格带按真实 price_range 统计；设计评分字段尚未接入，统一保持 0",
            ],
            "products": products,
            "gapZone": None,
            "priceBands": _price_bands(records),
            "sellingPoints": [],
        },
        "insightBase": {
            "hitProducts": hit_products,
            "ipPool": [
                {"name": record.brand or record.keyword, "status": "待核验", "heat": str(round(record.heat_index or 0, 2)), "fit": []}
                for record in ip_records
            ],
            "designLanguage": [],
        },
        "trendGallery": {
            "colors": [],
            "patterns": [],
            "shapes": [],
            "expressions": [],
        },
        "dataSource": "feishu",
        "sourceLabel": "飞书 Base · SKU-Hunters 采集数据",
        "evidenceCount": len(evidence),
        "recordCount": len(records),
        "generatedAt": generated_at,
        "dataContext": {
            "data_source": "feishu",
            "snapshot_id": selected_snapshot or "",
            "ingestion_run_id": selected_snapshot or "",
            "record_count": len(records),
            "evidence_count": len(evidence),
            "generated_at": generated_at,
        },
    }


def _consumer_process_log(
    pain_points: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    summary_error: str | None,
) -> list[str]:
    """按真实情况写 consumerVoice 过程日志：不把数据源故障写成暂无数据。"""
    if pain_points or scenes:
        return [
            "数据源：飞书 Base 实时明细",
            f"汇总表快照提供痛点 {len(pain_points)} 条、场景 {len(scenes)} 条",
        ]
    if summary_error is not None:
        return [
            "数据源：飞书 Base 实时明细",
            "汇总表读取失败，painPoints 与 scenes 保持空值",
        ]
    return [
        "数据源：飞书 Base 实时明细",
        "汇总表未提供结构化痛点/场景字段，painPoints 与 scenes 保持空值",
    ]


def _consumer_summary(
    pain_points: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    summary_error: str | None,
) -> str:
    if pain_points or scenes:
        return "已接入真实汇总痛点与场景；其余仅展示真实摘要。"
    if summary_error is not None:
        return "汇总表读取失败；情感、痛点和场景字段暂为空。"
    return "当前仅展示真实摘要；情感、痛点和场景字段尚未接入。"
