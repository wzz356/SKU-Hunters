"""端到端验证：归档 → 飞书多维表格自动新增一行

用法：python backend/scripts/e2e_bitable_archive.py
流程：创建企划(fixture) → 生成企划卡 → 归档 → 触发同步钩子 → 读回表格验证

注意：会向 FEISHU_BITABLE_APP_TOKEN 指向的多维表格真实写入一行。
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

from app.planning import pipeline
from feishu.bitable_sync import _get_syncer, sync_plan_to_bitable


def main() -> None:
    # ① 创建企划（fixture 冻数据，不调真实 LLM）
    plan = pipeline.create_plan({
        "theme": "2027夏季户外生活系列",
        "category": "小风扇",
        "price_range": [39, 99],
        "ip_strategy": ["三丽鸥"],
        "launch_window": "2027.04",
    })
    print(f"① 企划已创建: {plan['plan_id']}")

    # ② 选定第一张机会卡，生成企划卡
    opp_id = pipeline.get_opportunities(plan)[0]["id"]
    card = pipeline.generate_plan_card(plan, opp_id)
    assert card, "企划卡生成失败"
    print(f"② 企划卡已生成: {card['name']}")

    # ③ 归档 + 手动触发同步钩子（正式链路里钩子由 API 层 BackgroundTasks 执行）
    pipeline.archive_plan(plan)
    print(f"③ 已归档: status={plan['status']}, archived_at={plan['archived_at']}")
    assert sync_plan_to_bitable(plan), "多维表格同步失败（检查 .env 配置与网络）"

    # ④ 读回多维表格，验证新行存在
    syncer = _get_syncer()
    assert syncer, "多维表格未配置（检查 .env 的 FEISHU_BITABLE_*）"
    import requests
    resp = requests.get(f"{syncer.base}/records", headers=syncer._headers())
    data = resp.json()
    assert data.get("code") == 0, f"读取记录失败: {data}"
    rows = data["data"].get("items") or []
    hit = [r for r in rows if r["fields"].get("plan_id") == plan["plan_id"]]
    assert hit, f"表格里没找到 plan_id={plan['plan_id']} 的记录（现有 {len(rows)} 行）"
    print(f"④ 验证通过：多维表格已出现新行 record_id={hit[0]['record_id']}")
    print(f"   字段预览: theme={hit[0]['fields'].get('theme')}, "
          f"concept={hit[0]['fields'].get('concept')}")


if __name__ == "__main__":
    main()
