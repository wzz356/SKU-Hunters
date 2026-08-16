"""趋势历史回溯 — UApiPro 关键词历史检索 → 逐日命中序列 → 实测环比增速（演示可现场跑）

用法（backend/ 目录）：
    ./venv/Scripts/python scripts/trend_backfill.py
    ./venv/Scripts/python scripts/trend_backfill.py 风扇 香薰   # 自定义候选

回答的问题：「从今天开始攒数据曲线来不及」→ 不用攒。
UApiPro 历史检索模式（keyword + time_start/time_end）可以一次性搜出
关键词在过去 N 天所有热榜快照中的命中记录，按日分桶即得时间序列；
再对前 3 天 / 后 3 天求均值算环比增速——于是 trend_scan.py 里
GROWTH_MAP 的冻结数字（fixtures 口径）有了实测对照。

默认平台组合（2026-08 实测定型）：
  - smzdm（什么值得买）：消费品类榜，风扇/香薰等品类词命中率高 —— 主力
  - douyin / xiaohongshu / weibo：全民热榜，以娱乐新闻为主，
    细分品类词诚实零命中（这本身是答辩可用的真实结论：
    全民榜承载不了消费意图，所以打分器要接淘宝联想词补转化信号）

落盘 data/trend_history.json：
  - per keyword × platform 的逐日序列（date / hits / best_rank）
  - measured_growth_pct：后3天均命中 vs 前3天均命中的环比（%）
  - 与 GROWTH_MAP 冻结值的对照差

失败语义（与连接器层一致）：
  - 单平台失败 → 该平台记 error 并计入 failed_platforms，不拖垮整行
  - 检索零命中 → 逐日全 0，是正常结果不是故障

注：每个关键词×平台 = 1 次请求；默认 4 词 × 4 平台 = 16 次，
脚本内置请求间隔，避免触发免费层限流。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.errors import ConnectorFetchError
from app.data.uapi_hot import UapiHotConnector
from scripts.trend_scan import GROWTH_MAP

OUT_FILE = Path(__file__).resolve().parents[1] / "data" / "trend_history.json"

# 默认回溯平台：什么值得买（消费品类主力）+ 三大全民热榜（公域声量）
DEFAULT_PLATFORMS = ["smzdm", "douyin", "xiaohongshu", "weibo"]

DEFAULT_DAYS = 7
HALF = 3  # 环比窗口：前3天 vs 后3天
REQUEST_INTERVAL = 0.6  # 秒，免费层友好

_CST = timezone(timedelta(hours=8))

# 全民榜上消费词命中低，smzdm 用更宽的品类词效果更好；
# 候选词原样传给所有平台，由数据自己说话
BACKFILL_CANDIDATES = ["风扇", "库洛米", "香薰", "露营"]


def _date_range(days: int) -> list[str]:
    """过去 N 天（不含今天）的日期列表，升序"""
    today = datetime.now(_CST).date()
    return [(today - timedelta(days=o)).isoformat() for o in range(days, 0, -1)]


def _growth_pct(series: list[dict]) -> float | None:
    """后3天日均命中 vs 前3天日均命中的环比（%）；数据不足返回 None"""
    valid = [s["hits"] for s in series if s["hits"] is not None]
    if len(valid) < HALF * 2:
        return None
    prev, recent = valid[:HALF], valid[-HALF:]
    base = sum(prev) / HALF
    now = sum(recent) / HALF
    if base == 0:
        return None if now == 0 else 999.0  # 从 0 起量：无意义百分比，封顶标记
    return round((now - base) / base * 100, 1)


def backfill_keyword(keyword: str, platforms: list[str], days: int) -> dict:
    """单个关键词 × 多平台的历史检索 + 逐日分桶 + 实测增速汇总"""
    dates = _date_range(days)
    now_ms = int(datetime.now(_CST).timestamp() * 1000)
    start_ms = now_ms - days * 86400_000

    per_platform = {}
    growth_samples = []
    failed_platforms = []

    for platform in platforms:
        connector = UapiHotConnector(platform=platform)
        try:
            result = connector.search_history(keyword, start_ms, now_ms)
        except ConnectorFetchError as e:
            failed_platforms.append(platform)
            per_platform[platform] = {
                "series": [
                    {"date": d, "hits": None, "best_rank": None,
                     "error": e.detail[:60]} for d in dates
                ],
                "growth_pct": None,
            }
            time.sleep(REQUEST_INTERVAL)
            continue

        # 按日分桶：同一天多个快照重复命中只记一次（取最优排名）
        bucket: dict[str, list[int]] = {d: [] for d in dates}
        for item in result["items"]:
            day = datetime.fromtimestamp(
                item["snapshot_ts"] / 1000, _CST
            ).date().isoformat()
            if day in bucket:
                bucket[day].append(item["rank"])

        series = [
            {
                "date": d,
                "hits": 1 if bucket[d] else 0,  # 当日上过榜=1，用于环比
                "best_rank": min(bucket[d]) if bucket[d] else None,
            }
            for d in dates
        ]
        growth = _growth_pct(series)
        per_platform[platform] = {
            "series": series,
            "growth_pct": growth,
            "raw_hits": result["count"],  # 原始命中条目数（含重复快照）
        }
        if growth is not None:
            growth_samples.append(growth)
        time.sleep(REQUEST_INTERVAL)

    measured = (
        round(sum(growth_samples) / len(growth_samples), 1)
        if growth_samples else None
    )
    frozen = GROWTH_MAP.get(keyword)
    return {
        "keyword": keyword,
        "platforms": per_platform,
        "measured_growth_pct": measured,
        "frozen_growth_pct": frozen,
        "delta": (
            round(measured - frozen, 1)
            if measured is not None and frozen is not None else None
        ),
        "failed_platforms": failed_platforms,
    }


def main() -> int:
    keywords = sys.argv[1:] or BACKFILL_CANDIDATES
    print(f"趋势历史回溯：{len(keywords)} 词 × {len(DEFAULT_PLATFORMS)} 平台"
          f" × {DEFAULT_DAYS} 天\n" + "-" * 44)

    results = []
    for kw in keywords:
        print(f">> {kw}")
        row = backfill_keyword(kw, DEFAULT_PLATFORMS, DEFAULT_DAYS)
        results.append(row)
        for platform, data in row["platforms"].items():
            marks = " ".join(
                "-" if s["hits"] is None else ("x" if s["hits"] == 0 else "o")
                for s in data["series"]
            )
            growth = data["growth_pct"]
            growth_s = f"{growth:+.1f}%" if growth is not None else "数据不足"
            raw = f"（原始命中 {data['raw_hits']} 条）" if "raw_hits" in data else ""
            print(f"    {platform:<12} [{marks}]  环比 {growth_s} {raw}")
        measured, frozen = row["measured_growth_pct"], row["frozen_growth_pct"]
        compare = ""
        if measured is not None and frozen is not None:
            compare = f"（冻结值 {frozen}%，差 {row['delta']:+.1f}）"
        measured_s = f"{measured:+.1f}%" if measured is not None else "数据不足"
        print(f"    -> 实测环比 {measured_s} {compare}")
        if row["failed_platforms"]:
            print(f"    !! {','.join(row['failed_platforms'])} 检索失败（已降级）")

    snapshot = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "method": "UApiPro 关键词历史检索（过去 N 天全部快照）按日分桶；当日上榜记 1",
        "days": DEFAULT_DAYS,
        "platforms": DEFAULT_PLATFORMS,
        "keywords": results,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n已写入 {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
