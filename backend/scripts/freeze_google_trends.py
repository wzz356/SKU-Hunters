"""冻结 Google Trends 90 天曲线 — 手动导出的 CSV → JSON 快照

用法：
    1. 浏览器开代理访问 trends.google.com（三个词：小风扇/露营/库洛米，
       地区中国，过去 90 天），下载「随时间变化的趋势」CSV
    2. 保存为 backend/data/google_trends_raw.csv
    3. python scripts/freeze_google_trends.py

为什么手动：Google 对 pytrends 等脚本调用返回 429（机器人校验），
浏览器导出是最可靠的获取方式；本项目「冻数据」策略只需拉一次。

输出 backend/data/google_trends_snapshot.json：
    weeks: 日期列表（90 天为按天）
    series: [{name, data}] 三个词的热度曲线（0-100 相对值，同一次查询可比）
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_CSV = DATA_DIR / "google_trends_raw.csv"
OUT_JSON = DATA_DIR / "google_trends_snapshot.json"

KEYWORDS = ["风扇", "露营", "库洛米"]


def _parse_value(raw: str) -> float:
    """Google Trends CSV 低热度显示为 '<1'，归一为 0.5"""
    raw = raw.strip()
    if raw.startswith("<"):
        return 0.5
    return float(raw)


def main() -> None:
    if not RAW_CSV.is_file():
        raise SystemExit(f"找不到 {RAW_CSV}，请先从 trends.google.com 导出 CSV")

    # 导出 CSV 前两行是元信息（类别/地区），表头行以「天」或「周」开头
    with open(RAW_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header_idx = next(
        i for i, r in enumerate(rows) if r and r[0].strip() in ("日", "天", "周", "Day", "Week")
    )
    header = [h.strip() for h in rows[header_idx]]
    data_rows = [r for r in rows[header_idx + 1 :] if r and r[0].strip()]

    # 列名可能带「(中国)」后缀，做前缀匹配定位关键词列
    col_of = {}
    for kw in KEYWORDS:
        for i, h in enumerate(header):
            if h.startswith(kw):
                col_of[kw] = i
                break
        else:
            raise SystemExit(f"CSV 里没找到关键词列「{kw}」，实际表头：{header}")

    weeks = [r[0].strip() for r in data_rows]
    series = [
        {"name": kw, "data": [_parse_value(r[col_of[kw]]) for r in data_rows]}
        for kw in KEYWORDS
    ]

    snapshot = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "source": "trends.google.com 手动导出（pytrends 被 429 拦截，浏览器导出）",
        "geo": "CN",
        "timeframe": "today 3-m",
        "note": "热度为 0-100 相对值，三词同一次查询，可直接横向比较",
        "weeks": weeks,
        "series": series,
    }
    OUT_JSON.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ 冻结完成：{OUT_JSON}")
    print(f"   {len(weeks)} 个数据点（{weeks[0]} ~ {weeks[-1]}）")
    for s in series:
        peak = max(s["data"])
        print(f"   {s['name']}: 峰值 {peak:g}，均值 {sum(s['data'])/len(s['data']):.1f}")


if __name__ == "__main__":
    main()
