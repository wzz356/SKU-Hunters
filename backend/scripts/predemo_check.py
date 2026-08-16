"""演示前一键自检 — 演示日防翻车

用法（backend/ 目录，后端服务已启动）：
    ./venv/Scripts/python scripts/predemo_check.py

检查项：后端存活 / 企划六步链路 / 飞书 webhook fail-closed / 即梦配置状态。
全绿输出 "演示可开始"；任何一项红 → 按提示修复后再演示。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.getenv("PREDEMO_BASE", "http://localhost:8000")
FAILURES: list[str] = []


def check(name: str, ok: bool, hint: str = "") -> None:
    print(f"{'✅' if ok else '❌'} {name}" + ("" if ok or not hint else f"  → {hint}"))
    if not ok:
        FAILURES.append(name)


def get(path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — 自检脚本：任何异常都视为该项失败
        return -1, {"_error": str(e)[:120]}


def post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")
    except Exception as e:  # noqa: BLE001
        return -1, {"_error": str(e)[:120]}


def main() -> int:
    print(f"演示前自检 · 目标 {BASE}\n" + "─" * 40)

    # 1. 后端存活
    code, _ = get("/api/v1/plans")
    check("后端在线（GET /api/v1/plans）", code == 200,
          "启动：cd backend && ./venv/Scripts/python -m uvicorn app.main:app --port 8000")
    if code != 200:
        print("\n后端不在线，后续检查跳过。")
        return 1

    # 2. demo 任务存在
    code, plan = get("/api/v1/plans/demo")
    check("演示任务 demo 存在", code == 200,
          "重置演示状态：删 backend/data/plans_state.json 后重启后端")
    if code == 200:
        check("demo 状态可演示（brief_locked / plan_card_ready / archived 均可）",
              plan.get("status") in {"brief_locked", "insights_ready", "opportunities_ready",
                                     "plan_card_ready", "archived"})

    # 3. 六步链路
    code, ins = get("/api/v1/plans/demo/insights")
    check("五看洞察返回五块数据", code == 200 and
          {"trendRadar", "consumerVoice", "competitiveMap", "insightBase", "trendGallery"} <= set(ins))
    code, opp = get("/api/v1/plans/demo/opportunities")
    check("机会生成 3 张方向卡 + 思考过程日志", code == 200 and
          len(opp.get("opportunities", [])) == 3 and len(opp.get("processLog", [])) > 0)

    # 4. 企划卡（新建一次性任务验证真管线，不动 demo 状态）
    code, created = post("/api/v1/plans", {"brief": {
        "theme": "自检任务", "category": "小风扇", "costLimit": 25, "priceRange": [39, 99]}})
    ok = code == 201
    check("创建企划任务（POST /plans）", ok)
    if ok:
        pid = created["plan_id"]
        code, card_resp = post(f"/api/v1/plans/{pid}/plan-card", {"opportunity_id": "ip-collect"})
        card = card_resp.get("plan_card", {})
        check("企划卡生成 + 成本校验实时计算", code == 200 and
              card.get("costCheck", {}).get("passed") is True and
              "成本校验" in (card.get("processLog") or [""])[-1])
        check("概念图路径已冻结", bool(card.get("conceptImage")),
              "检查 frontend/public/assets/ 三张概念图是否在")

    # 5. 飞书 webhook fail-closed
    code, _ = post("/api/v1/feishu/events", {"token": "wrong", "type": "event_callback"})
    check("飞书 webhook 验签 fail-closed（错误 token → 403）", code == 403,
          "检查 backend/.env 的 FEISHU_* 配置与 webhook 路由")

    # 6. 即梦配置状态（不阻断演示，缺 Key 自动降级冻结图）
    from dotenv import load_dotenv
    load_dotenv()
    has_volc = bool(os.getenv("VOLC_ACCESS_KEY_ID") and os.getenv("VOLC_SECRET_ACCESS_KEY"))
    print(f"{'✅' if has_volc else 'ℹ️ '} 即梦火山 AK/SK {'已配置（live 出图可用）' if has_volc else '未配置——演示走冻结概念图（可接受）'}")

    print("─" * 40)
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项未过：{'、'.join(FAILURES)}")
        return 1
    print("🎉 全部通过，演示可开始。前端：cd frontend && npm run dev → http://localhost:5173")
    return 0


if __name__ == "__main__":
    sys.exit(main())
