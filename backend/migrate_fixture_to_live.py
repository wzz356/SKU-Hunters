"""fixture → live 任务迁移脚本（受控、逐任务原子、可审计）

用途：将旧 fixture/mock 任务重新基于 Feishu Base 真实数据生成 insights，
清除旧的 mock 派生产物，并切换 mode/brief.mode 为 live。

用法：
  python migrate_fixture_to_live.py             # dry-run：只预览，不改数据
  python migrate_fixture_to_live.py --apply     # 创建备份并逐任务原子迁移

纪律：
- 只用真实 Feishu 数据（BASE_PROVIDER_MODE=feishu），不回退 fixture/mock/LLM 兜底；
- 匹配不到 Feishu 数据 → 保持原状态并报告 BLOCKED；
- 逐任务原子：单个失败恢复该任务原状态，不产生半迁移；
- 保留任务 ID、人工 brief 约束；仅清除旧 mock 派生产物（insights/opportunities/plan_card/revise_logs）；
- 不打印任何密钥/Token。
"""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BASE = Path(__file__).resolve().parent  # backend/
sys.path.insert(0, str(_BASE))

from dotenv import load_dotenv

load_dotenv(_BASE / ".env")
# 迁移必须用真实 Feishu（setdefault：不覆盖 .env 已配置值）
os.environ.setdefault("BASE_PROVIDER_MODE", "feishu")
os.environ.setdefault("AGENT_PROVIDER", "real")
os.environ.setdefault("LEARNING_AGENT_PROVIDER", "real")
os.environ.setdefault("PLANNING_DEFAULT_MODE", "live")

# 触发 seed_demo 从 plans_state.json 加载全部任务到 _PLANS
import app.planning.service as _service  # noqa: F401
from app.planning.insight_resolver import _resolve_insight_bundle
from app.planning.repository import _PLANS, _save_state, _snake_keys
from app.planning.service import _build_plan_data_context
from app.schemas.planning import InsightBundle

# 本次迁移目标（其余 fixture 任务不在指定范围；92be/2efc 为 live 不可动）
TARGETS = ["plan_20260815_1002", "demo"]

_STATE_FILE = _BASE / "data" / "state" / "plans_state.json"


def _build_insights(plan: dict[str, Any]) -> dict[str, Any]:
    """重新生成真实 insights（只读，不修改 plan）"""
    brief = dict(plan["brief"])
    brief["mode"] = "live"
    bundle = _resolve_insight_bundle(brief.get("category", ""), brief)
    InsightBundle.model_validate(_snake_keys(bundle))  # schema 校验，失败即抛
    return bundle


def _preview(plan_id: str) -> dict[str, Any]:
    plan = _PLANS.get(plan_id)
    if plan is None:
        return {"plan_id": plan_id, "exists": False, "ok": False}
    try:
        bundle = _build_insights(plan)
        return {
            "plan_id": plan_id,
            "exists": True,
            "old_status": plan.get("status"),
            "new_status": "insights_ready",
            "match_records": bundle.get("recordCount", 0),
            "dataSource": bundle.get("dataSource"),
            "evidenceCount": bundle.get("evidenceCount", 0),
            "ok": bundle.get("evidenceCount", 0) > 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"plan_id": plan_id, "exists": True, "old_status": plan.get("status"), "error": str(exc), "ok": False}


def _backup() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = _BASE / "data" / "state" / f"plans_state.pre-live-migration-{ts}.json"
    shutil.copy2(_STATE_FILE, dst)
    return dst


def _migrate(plan_id: str, apply: bool = False) -> dict[str, Any]:
    plan = _PLANS.get(plan_id)
    if plan is None:
        return {"plan_id": plan_id, "ok": False, "error": "任务不存在"}
    if plan.get("mode") == "live" and plan.get("brief", {}).get("mode") == "live":
        return {"plan_id": plan_id, "ok": False, "skipped": True, "error": "已是 live"}
    original = copy.deepcopy(plan)
    try:
        bundle = _build_insights(plan)
        if not bundle.get("evidenceCount", 0):
            _PLANS[plan_id] = original  # 无真实证据 → BLOCKED，保持原状态
            return {"plan_id": plan_id, "ok": False, "blocked": True, "error": "无真实 Feishu 证据，保持原状态"}
        plan["insights"] = bundle
        # 先切 mode=live，再构造 data_context（契约按 brief.mode 分支，顺序颠倒会误写 fixture）
        plan["mode"] = "live"
        plan["brief"]["mode"] = "live"
        plan["status"] = "insights_ready"
        _build_plan_data_context(plan, bundle)
        # 清除旧 mock 派生产物
        plan["opportunities"] = []
        plan["selected_opportunity"] = None
        plan["plan_card"] = None
        plan["revise_logs"] = []
        if apply:
            _save_state()
        return {
            "plan_id": plan_id, "ok": True,
            "match_records": bundle.get("recordCount", 0),
            "evidenceCount": bundle.get("evidenceCount", 0),
            "dataSource": bundle.get("dataSource"),
            "new_status": "insights_ready",
        }
    except Exception as exc:  # noqa: BLE001
        _PLANS[plan_id] = original  # 回滚该任务原状态
        return {"plan_id": plan_id, "ok": False, "error": str(exc)}


def _fixture_targets() -> list[str]:
    return [pid for pid, p in _PLANS.items() if p.get("mode") == "fixture"]


def main() -> None:
    parser = argparse.ArgumentParser(description="fixture → live 迁移")
    parser.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    parser.add_argument("--plan", action="append", help="指定要迁移的任务（可多次）")
    args = parser.parse_args()

    targets = args.plan or TARGETS
    if not args.apply:
        print("=== DRY-RUN（不修改数据）===")
        print("fixture 任务:", _fixture_targets())
        for pid in targets:
            print(_preview(pid))
        return

    print("=== APPLY ===")
    backup = _backup()
    print(f"备份文件: {backup}")
    for pid in targets:
        print(_migrate(pid, apply=True))


if __name__ == "__main__":
    main()
