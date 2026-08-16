"""真实数据端到端 Demo — 淘宝需求信号 + B站 UGC 趋势

用法:
    cd backend
    python scripts/demo_real_data.py

场景: 验证 Labubu / Chiikawa / 线条小狗 三个 IP 的
      真实消费需求信号（淘宝）+ 内容热度信号（B站）
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.bilibili_hot import BilibiliConnector
from app.data.taobao_suggest import TaobaoSuggestConnector

IP_CANDIDATES = ["labubu", "chiikawa", "线条小狗"]


def main():
    tb = TaobaoSuggestConnector()
    bili = BilibiliConnector()

    report = {}

    print("=" * 66)
    print("SKU Hunters — 真实数据管道验证")
    print("数据源: 淘宝搜索联想（消费需求）+ B站分区排行（UGC热度）")
    print("=" * 66)

    for kw in IP_CANDIDATES:
        print(f"\n{'─' * 66}")
        print(f"▶ 分析关键词: {kw}")
        print(f"{'─' * 66}")

        # ── 淘宝：真实消费需求信号 ──
        demand = tb.analyze_demand(kw)
        print(f"\n[淘宝·消费需求] 关联需求 {demand['demand_breadth']} 个，"
              f"平均热度 {demand['avg_heat']}")
        if demand["top_demands"]:
            print("  Top 需求词:")
            for d in demand["top_demands"]:
                print(f"    - {d['query']}（热度 {d['heat']}）")
        if demand["product_signals"]:
            print(f"  商品形态信号: {'、'.join(demand['product_signals'])}")

        # ── B站：真实 UGC 热度信号 ──
        ugc = bili.search_keyword(kw)
        print(f"\n[B站·UGC热度] 扫描5大分区榜共 {ugc['scanned_videos']} 个视频，"
              f"命中 {ugc['total_results']} 个，总播放 {ugc['total_views']:,}")
        if ugc["top_videos"]:
            v = ugc["top_videos"][0]
            print(f"  最热视频: {v['title'][:40]}（播放 {v['play']:,}）")
            print(f"  链接: {v['url']}")

        report[kw] = {"taobao_demand": demand, "bilibili_ugc": ugc}

    # ── 综合对比 ──
    print(f"\n{'=' * 66}")
    print("综合信号对比（多源交叉验证）")
    print(f"{'=' * 66}")
    print(f"{'IP':<14} {'淘宝需求广度':>10} {'B站视频数':>10} {'B站总播放':>14}")
    print(f"{'-' * 66}")
    for kw in IP_CANDIDATES:
        r = report[kw]
        print(f"{kw:<14} {r['taobao_demand']['demand_breadth']:>10} "
              f"{r['bilibili_ugc']['total_results']:>10} "
              f"{r['bilibili_ugc']['total_views']:>14,}")

    out = Path(__file__).resolve().parent.parent.parent / "data" / "sample" / "real_data_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整报告已保存: {out}")


if __name__ == "__main__":
    main()
