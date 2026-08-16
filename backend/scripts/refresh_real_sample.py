"""真实数据抽样刷新 — 为演示 fixtures 提供真实数据对照快照

用法（backend/ 目录）：
    ./venv/Scripts/python scripts/refresh_real_sample.py

拉取四类真实公开数据，按演示场景关键词过滤，写入
backend/data/real_sample_snapshot.json：

  ① 微博/百度热搜 × 演示关键词      （社媒趋势信号）
  ② 淘宝联想词 × 品类词             （真实消费需求信号）
  ③ B站搜索 × 品类词                （Z 世代 UGC 信号）

用途：答辩时 fixtures 的「生成演示数据」之外，附一份同日真实数据抽样，
证明管线接的是真连接器、冻数据口径可切换到真实口径。
每个源故障独立记录（failed_sources），不折叠为"零命中"。

注：Google Trends 走 trend_agent 的 live 路径（需代理），本脚本不含。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import hot_topics
from app.data.bilibili_hot import BilibiliConnector
from app.data.errors import ConnectorFetchError
from app.data.taobao_suggest import TaobaoSuggestConnector

OUT_FILE = Path(__file__).resolve().parents[1] / "data" / "real_sample_snapshot.json"

# 演示场景（2027夏季户外生活系列 × 小风扇）关键词
TREND_KEYWORDS = ["风扇", "露营", "户外", "桌面", "治愈", "库洛米", "三丽鸥", "香薰"]
TAOBAO_KEYWORDS = ["小风扇", "桌面风扇", "露营风扇", "库洛米"]
BILIBILI_KEYWORDS = ["小风扇", "工位改造", "露营装备"]


def _section_trends() -> dict:
    """① 热搜源 × 关键词"""
    payload = hot_topics.fetch_all()
    matched = hot_topics.match_keywords(payload, TREND_KEYWORDS)
    return {
        "total_items": len(payload["items"]),
        "scanned_sources": matched["scanned_sources"],
        "failed_sources": matched["failed_sources"],
        "hits": matched["hits"],
    }


def _section_taobao() -> dict:
    """② 淘宝联想词（故障隔离：单词失败记录后继续）"""
    conn = TaobaoSuggestConnector()
    results, failed = {}, []
    for kw in TAOBAO_KEYWORDS:
        try:
            suggestions = conn.get_suggestions(kw)
            results[kw] = suggestions[:10]
            if not suggestions:
                failed.append({"keyword": kw, "detail": "空返回（接口变更或被限流）"})
        except Exception as e:  # noqa: BLE001 — 该连接器约定返回空列表而非抛错
            failed.append({"keyword": kw, "detail": str(e)[:120]})
    return {"suggestions": results, "failed_keywords": failed}


def _section_bilibili() -> dict:
    """③ B站分区榜关键词曝光（该连接器逐分区容错，全失败才抛错）

    search_keyword 返回曝光统计 + top_videos；零命中是正常结果
    （附 scanned_partitions / failed_partitions 供对账）。
    """
    conn = BilibiliConnector()
    results, failed = {}, []
    for kw in BILIBILI_KEYWORDS:
        try:
            data = conn.search_keyword(kw)
            results[kw] = {
                "scanned_videos": data["scanned_videos"],
                "total_results": data["total_results"],
                "total_views": data["total_views"],
                "scanned_partitions": data["scanned_partitions"],
                "failed_partitions": data["failed_partitions"],
                "top_videos": [
                    {k: v[k] for k in ("title", "view", "tname", "bvid", "url")}
                    for v in data["top_videos"]
                ],
            }
        except ConnectorFetchError as e:
            failed.append({"keyword": kw, "detail": e.detail})
    return {"keywords": results, "failed_keywords": failed}


def main() -> int:
    print("真实数据抽样刷新中（每个源独立容错）…\n" + "─" * 40)
    snapshot = {"refreshed_at": datetime.now(timezone.utc).isoformat(), "sections": {}}

    for name, fn in [("hot_search", _section_trends),
                     ("taobao_suggest", _section_taobao),
                     ("bilibili", _section_bilibili)]:
        try:
            snapshot["sections"][name] = fn()
            ok = True
        except ConnectorFetchError as e:
            snapshot["sections"][name] = {"error": str(e)}
            ok = False
        except Exception as e:  # noqa: BLE001 — 抽样脚本：单节失败不拖垮整体
            snapshot["sections"][name] = {"error": f"{type(e).__name__}: {e}"[:200]}
            ok = False
        print(f"{'✅' if ok else '❌'} {name}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("─" * 40)
    print(f"快照已写入 {OUT_FILE}")

    # 控制台摘要（演示日可直接念）
    hot = snapshot["sections"].get("hot_search", {})
    if "hits" in hot:
        print(f"\n热搜命中 {len(hot['hits'])} 条（扫描 {len(hot.get('scanned_sources', []))} 源）：")
        for h in hot["hits"][:8]:
            print(f"  [{h['source']}] #{h.get('rank', '?')} {h['word']}（热度 {h.get('heat') or '—'}）")
    tb = snapshot["sections"].get("taobao_suggest", {})
    for kw, sugs in (tb.get("suggestions") or {}).items():
        if sugs:
            top = "、".join(s["query"] for s in sugs[:3] if isinstance(s, dict) and "query" in s)
            print(f"淘宝「{kw}」联想 TOP3：{top}")
    bili = snapshot["sections"].get("bilibili", {})
    for kw, r in (bili.get("keywords") or {}).items():
        print(f"B站「{kw}」：扫描 {r['scanned_videos']} 条热门 → 命中 {r['total_results']} 条"
              f"（分区 {'/'.join(r['scanned_partitions']) or '无'}）")
    for f in bili.get("failed_keywords") or []:
        print(f"B站「{f['keyword']}」采集失败：{f['detail'][:60]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
