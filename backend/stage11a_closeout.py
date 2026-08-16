"""Stage 11A 收口补丁 2/2：
1. 补齐 4b82/4d4d（live）的 data_context（同一构建路径，不改动 insights/status）
2. 清理 6 个 fixture 任务的旧 crawled 洞察 → 显式演示数据（dataSource=fixture）+ data_context
逐任务原子（失败恢复原状），执行前备份。
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))

from dotenv import load_dotenv

load_dotenv(_BASE / ".env")
import os

os.environ.setdefault("BASE_PROVIDER_MODE", "feishu")

import app.planning.service as _service  # noqa: F401  触发 seed_demo 加载
from app.planning.insight_resolver import _resolve_insight_bundle
from app.planning.repository import _PLANS, _save_state, _snake_keys
from app.planning.service import _build_plan_data_context
from app.schemas.planning import InsightBundle

LIVE_BACKFILL = ["plan_20260815_4b82", "plan_20260815_4d4d"]
FIXTURE_CLEAN = [p for p, v in _PLANS.items() if v.get("mode") == "fixture"]


def _backup() -> Path:
    import shutil
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = _BASE / "data" / "state" / f"plans_state.pre-closeout-{ts}.json"
    shutil.copy2(_BASE / "data" / "state" / "plans_state.json", dst)
    return dst


def main() -> None:
    print("备份:", _backup())
    results = []

    # 1) live 补齐 data_context（不改动 insights/status）
    for pid in LIVE_BACKFILL:
        plan = _PLANS[pid]
        original = copy.deepcopy(plan)
        try:
            assert plan["mode"] == "live" and plan["brief"]["mode"] == "live"
            bundle = _resolve_insight_bundle(plan["brief"]["category"], plan["brief"])
            InsightBundle.model_validate(_snake_keys(bundle))
            ctx = _build_plan_data_context(plan, bundle)
            assert ctx["data_source"] == "feishu" and ctx["evidence_count"] > 0, ctx
            results.append((pid, "live-backfill", ctx["data_source"], ctx["evidence_count"], "OK"))
        except Exception as exc:  # noqa: BLE001
            _PLANS[pid] = original
            results.append((pid, "live-backfill", None, None, f"FAIL: {exc}"))

    # 2) fixture 清理旧 crawled 洞察 → 演示数据（保留 mode/status/opportunities）
    for pid in FIXTURE_CLEAN:
        plan = _PLANS[pid]
        original = copy.deepcopy(plan)
        try:
            old_ds = (plan.get("insights") or {}).get("dataSource")
            bundle = _resolve_insight_bundle(plan["brief"]["category"], plan["brief"])
            assert bundle.get("dataSource") == "fixture", bundle.get("dataSource")
            InsightBundle.model_validate(_snake_keys(bundle))
            plan["insights"] = bundle
            ctx = _build_plan_data_context(plan, bundle)
            assert ctx["data_source"] == "fixture"
            results.append((pid, f"fixture-clean({old_ds}->fixture)", ctx["data_source"], ctx["evidence_count"], "OK"))
        except Exception as exc:  # noqa: BLE001
            _PLANS[pid] = original
            results.append((pid, "fixture-clean", None, None, f"FAIL: {exc}"))

    _save_state()
    for r in results:
        print(r)
    print("已落盘")


if __name__ == "__main__":
    main()
