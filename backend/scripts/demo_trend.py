"""端到端真实数据 Demo — 趋势官 Agent 跑通验证

用法:
    cd backend
    python -m scripts.demo_trend

输出: 真实 Google Trends 数据 → FeatureMatrix → JSON
"""

import asyncio
import json
import sys
from pathlib import Path

# 让脚本可直接从 backend/ 目录运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.trend_agent import TrendAgent


async def main():
    agent = TrendAgent()

    print("=" * 60)
    print("SKU Hunters — 趋势官 Agent 真实数据 Demo")
    print("场景: 东南亚市场 IP 潮玩趋势扫描")
    print("=" * 60)

    result = await agent.run({
        "keywords": ["Labubu", "Chiikawa", "Pop Mart", "blind box"],
        "category": "潮玩",
        "geo": "TH",  # 泰国市场
    })

    print(f"\n分析品类: {result['category']} | 区域: {result['region']} | 日期: {result['analysis_date']}")
    print(f"\n摘要:\n{result['summary']}\n")

    print("-" * 60)
    print(f"{'关键词':<15} {'热度指数':>8} {'生命周期':>10}")
    print("-" * 60)
    for t in result["trends"]:
        print(f"{t['keyword']:<15} {t['heat_index']:>8.1f} {t['lifecycle']:>10}")

    print("\n" + "-" * 60)
    print("证据链 (EvidenceRef):")
    print("-" * 60)
    for e in result["evidence_refs"]:
        print(f"  [{e['title']}]")
        print(f"    {e['snippet'][:120]}")
        print(f"    来源: {e['url']}")

    # 落盘
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "sample" / "trend_demo_output.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
