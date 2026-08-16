"""趋势价值扫描 — 真实数据 → 四维打分 → 趋势卡（演示可现场跑）

用法（backend/ 目录）：
    ./venv/Scripts/python scripts/trend_scan.py
    ./venv/Scripts/python scripts/trend_scan.py 小风扇 库洛米 香薰   # 自定义候选

流程：一次拉取微博/百度热搜 + 逐词拉淘宝联想词 → trend_scorer 四维打分
（纯函数，确定性可复现）→ 按总分排序输出趋势卡 + 思考过程日志，
写入 data/trend_scan_snapshot.json。

答辩口径：这是"淘汰 N 个保留 M 个"的真算法背书——评委追问"凭什么说
这个趋势有价值"时，打开快照展示每个分数的依据链（挂了真实数据来源）。

注：growth_pct 为离线预采集增速（fixtures 口径），实时增速需要连续
多期快照对比（赛后 P2 方向）；本脚本不伪造实时增速。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import hot_topics, trend_scorer
from app.data.errors import ConnectorFetchError
from app.data.taobao_suggest import TaobaoSuggestConnector

OUT_FILE = Path(__file__).resolve().parents[1] / "data" / "trend_scan_snapshot.json"

# 默认候选池：演示场景（2027夏季户外生活系列）相关关键词
DEFAULT_CANDIDATES = ["小风扇", "桌面风扇", "露营风扇", "库洛米", "香薰", "工位改造"]

# 离线预采集增速信号（%），来自 fixtures 趋势雷达的口径；无则 None
GROWTH_MAP: dict[str, float] = {
    "小风扇": 45,
    "桌面风扇": 52,
    "露营风扇": 78,
    "库洛米": 65,
    "香薰": 35,
    "工位改造": 52,
}


def collect_candidate(
    keyword: str,
    hot_items: list[dict],
    taobao: TaobaoSuggestConnector,
) -> dict:
    """采集单个候选词的三路信号（单源失败降级为 None/空，不拖垮整体）"""
    hits = [item for item in hot_items if keyword in item["word"]]
    try:
        suggestions = taobao.get_suggestions(keyword)
    except Exception:  # noqa: BLE001 — 该连接器约定返回空列表，此处双保险
        suggestions = None
    return {
        "keyword": keyword,
        "hot_hits": hits,
        "suggestions": suggestions,
        "growth_pct": GROWTH_MAP.get(keyword),
    }


def main() -> int:
    keywords = sys.argv[1:] or DEFAULT_CANDIDATES
    print(f"趋势价值扫描：{len(keywords)} 个候选 × 四维打分\n" + "─" * 44)

    # ① 热搜（一次拉取，全候选共享）；故障降级为空集合并明示
    failed_sources: list[str] = []
    try:
        payload = hot_topics.fetch_all()
        hot_items = payload["items"]
        failed_sources = [f["source"] for f in payload["failed_sources"]]
        print(f"热搜拉取：{len(hot_items)} 条（源 {'/'.join(payload['scanned_sources'])}）")
    except ConnectorFetchError as e:
        hot_items = []
        print(f"⚠️ 热搜全部失败，动能维度降级为仅增速信号：{e.detail[:60]}")

    # ② 逐词采集 + 打分
    taobao = TaobaoSuggestConnector()
    candidates = [collect_candidate(kw, hot_items, taobao) for kw in keywords]
    cards = trend_scorer.score_trends(candidates)

    # ③ 落盘 + 控制台呈现
    snapshot = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "candidates": keywords,
        "failed_sources": failed_sources,
        "cards": cards,
        "process_log": trend_scorer.summarize(cards),
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n趋势卡（按总分排序）：")
    for c in cards:
        print(f"  [{c['grade']}] {c['keyword']} — {c['total']} 分")
        for dim, label in trend_scorer.DIM_LABELS.items():
            d = c["dimensions"][dim]
            print(f"      {label} {d['score']:.0f}：{d['evidence'][0]}")
    print("\n思考过程（processLog 同款）：")
    for line in snapshot["process_log"]:
        print(f"  · {line}")
    print(f"\n快照已写入 {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
