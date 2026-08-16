"""企划工作室 API — AI 新品企划工作室的六步链路端点

    POST /api/v1/plans                      ① 创建企划任务（约束输入）
    GET  /api/v1/plans                      任务列表
    GET  /api/v1/plans/{id}                 任务详情（约束 + 状态）
    GET  /api/v1/plans/{id}/insights        ② 五看洞察（三Agent + 两块策展数据）
    GET  /api/v1/plans/{id}/opportunities   ③ 机会生成（3 张方向卡）
    POST /api/v1/plans/{id}/plan-card       ④⑤⑥ 选定方向 → 生成企划卡
    POST /api/v1/plans/{id}/revise          改稿沟通

    GET  /api/v1/insight-base               名创内部（策展数据独立页）
    GET  /api/v1/trend-gallery              流行元素板（策展数据独立页）
    GET  /api/v1/data-board                 数据看板（大盘）

数据策略「真管线、冻数据」：默认 fixture 模式返回冻结分析结果；
brief 传 mode="live" 走真实 LLM + 即梦出图（失败自动降级）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import ValidationError

from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.engine.strict_mode import StrictModeError
from app.planning import fixtures, ip_resource, pipeline
from app.planning.insight_resolver import LLMGenerationError
from app.planning.live_data import build_live_data_board
from app.planning.repository import plan_write_lock
from app.planning.service import StateTransitionError
from app.schemas.planning import PlanBrief
from app.schemas.planning_api_v2 import PlanListResponseV2

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["planning"])
from app.engine.strict_mode import is_demo_hidden


def _get_plan_or_404(plan_id: str) -> dict[str, Any]:
    if plan_id == "demo" and is_demo_hidden():
        raise HTTPException(404, detail={"error": {"code": "PLAN_NOT_FOUND", "message": plan_id}})
    plan = pipeline.get_plan(plan_id)
    if plan is None:
        raise HTTPException(404, detail={"error": {"code": "PLAN_NOT_FOUND", "message": plan_id}})
    return plan


def _state_transition_error(e: StateTransitionError) -> HTTPException:
    """状态机非法转移 → 409（原子动作前置状态校验失败）"""
    return HTTPException(409, detail={"error": {"code": "INVALID_TRANSITION", "message": str(e)}})


def _llm_generation_error(e: LLMGenerationError) -> HTTPException:
    """LLM 生成失败 → 503（无采集数据且 LLM 不可用/输出不合契约；不产假数据，诚实报错）"""
    return HTTPException(503, detail={"error": {"code": "LLM_UNAVAILABLE", "message": str(e)}})


@router.post("/plans", status_code=201)
async def create_plan(payload: dict):
    brief = payload.get("brief") or payload  # 兼容直接传 brief
    # PlanBrief schema 校验（pydantic 保证必填字段 + 类型检查）
    try:
        PlanBrief.model_validate(brief)
    except ValidationError as e:
        raise HTTPException(422, detail={"error": {"code": "BRIEF_INVALID", "message": str(e)}}) from e
    try:
        plan = pipeline.create_plan(brief)
    except StrictModeError as e:
        # 严格模式禁止 fixture/演示任务 → 409 业务冲突
        raise HTTPException(409, detail={"error": {"code": "STRICT_REAL_MODE", "message": str(e)}}) from e
    return {"plan_id": plan["plan_id"], "status": plan["status"]}


def _run_aily_flow(plan: dict[str, Any]) -> None:
    """Aily 发起后的后台流程：五看洞察 → 机会卡 → 推飞书卡片

    Aily 插件调用有超时限制（10-30s），不能同步等 pipeline，
    跑完由后端主动推消息（fail-soft，推送失败不影响任务状态）。
    """
    try:
        pipeline.generate_insights(plan)
        opportunities = pipeline.generate_opportunities(plan)
        from feishu.notify import notify_opportunities_ready
        notify_opportunities_ready(plan, opportunities)
    except Exception:
        logger.exception("Aily 后台流程异常，plan_id=%s", plan.get("plan_id"))


@router.post("/plans/aily-create", status_code=202)
async def aily_create_plan(payload: dict, background_tasks: BackgroundTasks):
    """Aily 轻入口：对话收集 PlanBrief → 立即返回，后台跑 pipeline

    入参与 POST /plans 一致（PlanBrief 字段），出参立即返回 plan_id；
    机会卡生成后推送飞书消息卡片（摘要 + 跳转前端选定方向）。
    """
    brief = payload.get("brief") or payload  # 兼容直接传 brief
    try:
        PlanBrief.model_validate(brief)
    except ValidationError as e:
        raise HTTPException(422, detail={"error": {"code": "BRIEF_INVALID", "message": str(e)}}) from e
    plan = pipeline.create_plan(brief)
    background_tasks.add_task(_run_aily_flow, plan)
    return {"plan_id": plan["plan_id"], "status": "running"}

@router.get("/plans", response_model=PlanListResponseV2)
async def list_plans():
    return {"plans": pipeline.list_plans()}


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    plan = _get_plan_or_404(plan_id)
    return {
        "plan_id": plan["plan_id"],
        "brief": plan["brief"],
        "mode": plan["mode"],
        "status": plan["status"],
        "selected_opportunity": plan["selected_opportunity"],
        "plan_card": plan.get("plan_card"),  # 已有企划卡（归档后回看用）
        "product_proposal": plan.get("product_proposal"),  # 新品企划案（六模块）
        "created_at": plan["created_at"],
    }


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: str):
    """删除任务：套 plan 写锁与在途生成串行化；不存在 → 404"""
    _get_plan_or_404(plan_id)
    with plan_write_lock(plan_id):
        pipeline.delete_plan(plan_id)


@router.get("/plans/{plan_id}/insights")
async def get_insights(plan_id: str):
    plan = _get_plan_or_404(plan_id)
    try:
        return {"plan_id": plan_id, **pipeline.get_insights(plan)}
    except LLMGenerationError as e:
        raise _llm_generation_error(e) from e


@router.get("/plans/{plan_id}/opportunities")
async def get_opportunities(plan_id: str):
    plan = _get_plan_or_404(plan_id)
    try:
        opportunities = pipeline.get_opportunities(plan)
    except LLMGenerationError as e:
        raise _llm_generation_error(e) from e
    return {
        "plan_id": plan_id,
        "opportunities": opportunities,
        # 机会生成思考过程：按真实链路生成（只描述系统真实发生的动作）
        "processLog": pipeline._opportunities_process_log(
            plan["brief"].get("category", ""), plan.get("insights"), opportunities
        ),
    }


# 流程推进的状态机（GET 只读不改业务状态；推进由本 POST 显式触发）
_STATUS_ORDER = ["brief_locked", "insights_ready", "opportunities_ready", "plan_card_ready"]

@router.post("/plans/{plan_id}/advance")
async def advance_plan(plan_id: str, payload: dict):
    """显式推进流程状态（brief_locked → insights_ready → opportunities_ready → plan_card_ready）

    取代旧实现里 GET /insights、/opportunities 顺带推进状态的反模式：
    GET 只读、可重试、幂等，不再产生状态副作用。
    """
    plan = _get_plan_or_404(plan_id)
    target = (payload.get("to") or payload.get("status") or "").strip()
    if target not in _STATUS_ORDER:
        raise HTTPException(422, detail={"error": {"code": "INVALID_STATUS", "message": target or "(空)"}})
    current = plan.get("status", "brief_locked")
    if current == "archived":
        raise HTTPException(409, detail={"error": {"code": "PLAN_ARCHIVED", "message": "已归档，不可推进"}})
    if _STATUS_ORDER.index(target) <= _STATUS_ORDER.index(current):
        raise HTTPException(409, detail={"error": {"code": "INVALID_TRANSITION", "message": f"{current} -> {target}"}})
    plan["status"] = target
    return {"plan_id": plan_id, "status": target}

# ── 原子业务动作（Stage 5）：生成 + 落盘 + 推进状态一次完成 ────────
# 取代「advance + GET」两请求组合，消除「状态已推进但产物未生成」半完成态。
# 旧 advance / plan-card / archive 端点保留为兼容入口（见下方旧端点）。

@router.post("/plans/{plan_id}/actions/generate-insights")
async def action_generate_insights(plan_id: str):
    plan = _get_plan_or_404(plan_id)
    try:
        insights = pipeline.generate_insights(plan)
    except StateTransitionError as e:
        raise _state_transition_error(e) from e
    except LLMGenerationError as e:
        raise _llm_generation_error(e) from e
    return {"plan_id": plan_id, "status": plan["status"], "insights": insights}


@router.post("/plans/{plan_id}/actions/generate-opportunities")
async def action_generate_opportunities(plan_id: str):
    plan = _get_plan_or_404(plan_id)
    try:
        opportunities = pipeline.generate_opportunities(plan)
    except StateTransitionError as e:
        raise _state_transition_error(e) from e
    except LLMGenerationError as e:
        raise _llm_generation_error(e) from e
    return {
        "plan_id": plan_id,
        "status": plan["status"],
        "opportunities": opportunities,
        "processLog": pipeline._opportunities_process_log(
            plan["brief"].get("category", ""), plan.get("insights"), opportunities
        ),
    }


@router.post("/plans/{plan_id}/actions/generate-plan-card")
async def action_generate_plan_card(plan_id: str, payload: dict):
    plan = _get_plan_or_404(plan_id)
    opportunity_id = payload.get("opportunity_id")
    if not opportunity_id:
        raise HTTPException(422, detail={"error": {"code": "OPPORTUNITY_REQUIRED", "message": "opportunity_id 必填"}})
    try:
        card = await asyncio.to_thread(pipeline.generate_plan_card, plan, opportunity_id)
    except StateTransitionError as e:
        raise _state_transition_error(e) from e
    except LLMGenerationError as e:
        raise _llm_generation_error(e) from e
    if card is None:
        raise HTTPException(404, detail={"error": {"code": "OPPORTUNITY_NOT_FOUND", "message": opportunity_id}})
    return {"plan_id": plan_id, "status": plan["status"], "plan_card": card,
            "product_proposal": plan.get("product_proposal")}


@router.post("/plans/{plan_id}/actions/archive")
async def action_archive(plan_id: str, background_tasks: BackgroundTasks):
    plan = _get_plan_or_404(plan_id)
    try:
        await asyncio.to_thread(pipeline.archive_plan, plan)
    except StateTransitionError as e:
        raise _state_transition_error(e)
    except ValueError as e:
        raise HTTPException(409, detail={"error": {"code": "PLAN_CARD_NOT_READY", "message": str(e)}})
    background_tasks.add_task(_run_archive_hooks, plan)
    return {"plan_id": plan_id, "status": plan["status"], "archived_at": plan["archived_at"]}


@router.post("/plans/{plan_id}/plan-card")
async def generate_plan_card(plan_id: str, payload: dict):
    plan = _get_plan_or_404(plan_id)
    opportunity_id = payload.get("opportunity_id")
    if not opportunity_id:
        raise HTTPException(422, detail={"error": {"code": "OPPORTUNITY_REQUIRED", "message": "opportunity_id 必填"}})
    try:
        card = await asyncio.to_thread(pipeline.generate_plan_card, plan, opportunity_id)
    except StateTransitionError as e:
        raise _state_transition_error(e) from e
    except LLMGenerationError as e:
        raise _llm_generation_error(e) from e
    if card is None:
        raise HTTPException(404, detail={"error": {"code": "OPPORTUNITY_NOT_FOUND", "message": opportunity_id}})
    return {"plan_id": plan_id, "plan_card": card,
            "product_proposal": plan.get("product_proposal")}


@router.post("/plans/{plan_id}/revise")
async def revise_plan(plan_id: str, payload: dict):
    plan = _get_plan_or_404(plan_id)
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(422, detail={"error": {"code": "MESSAGE_REQUIRED", "message": "message 必填"}})
    if plan.get("plan_card") is None:
        raise HTTPException(409, detail={"error": {"code": "PLAN_CARD_NOT_READY", "message": "请先生成企划卡"}})
    try:
        result = await asyncio.to_thread(pipeline.revise_plan, plan, message)
        return {"plan_id": plan_id, **result}
    except StateTransitionError as e:
        raise _state_transition_error(e)


def _run_archive_hooks(plan: dict[str, Any]) -> None:
    """归档后的飞书同步：①写入多维表格（企划资产库）②推归档卡片到通知群

    挂后台执行，归档响应不等飞书（演示现场不转圈）；
    fail-soft：任一失败只记日志，归档本身已落盘。
    """
    try:
        from feishu.bitable_sync import sync_plan_to_bitable
        from feishu.notify import notify_plan_archived
        sync_plan_to_bitable(plan)
        notify_plan_archived(plan)
    except Exception:
        logger.exception("归档后飞书同步异常（归档本身不受影响），plan_id=%s",
                         plan.get("plan_id"))


@router.post("/plans/{plan_id}/archive")
async def archive_plan(plan_id: str, background_tasks: BackgroundTasks):
    plan = _get_plan_or_404(plan_id)
    try:
        await asyncio.to_thread(pipeline.archive_plan, plan)
    except StateTransitionError as e:
        raise _state_transition_error(e)
    except ValueError as e:
        raise HTTPException(409, detail={"error": {"code": "PLAN_CARD_NOT_READY", "message": str(e)}})
    # 事件驱动同步挪后台：归档立即返回，多维表格写入 + 卡片推送随后执行
    background_tasks.add_task(_run_archive_hooks, plan)
    return {"plan_id": plan_id, "status": plan["status"], "archived_at": plan["archived_at"]}


@router.post("/plans/{plan_id}/review")
async def review_plan(plan_id: str, payload: dict):
    """复盘追问（只读）：归档后基于企划卡回答追问，不修改 plan"""
    plan = _get_plan_or_404(plan_id)
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(422, detail={"error": {"code": "QUESTION_REQUIRED", "message": "question 必填"}})
    result = await asyncio.to_thread(pipeline.review_plan, plan, question)
    return {"plan_id": plan_id, **result}


# ── 策展数据独立页（非 Agent 现搜，提前策展）────────────────────

@router.get("/ip-resource")
async def get_ip_resource():
    """名创内部 IP 资源库（策展数据：12 个代表性 IP + 官方披露数据带 + 筛选维度）"""
    return {
        "stats": ip_resource.IP_STATS,
        "ips": ip_resource.IP_RESOURCE,
        "audienceFilters": ip_resource.AUDIENCE_FILTERS,
        "styleFilters": ip_resource.STYLE_FILTERS,
    }


def _load_curated_module(topic: str, key: str, fallback: dict):
    if os.getenv("BASE_PROVIDER_MODE", "disabled").strip().lower() == "feishu":
        try:
            from app.planning.live_insights import build_live_insight_bundle

            return build_live_insight_bundle(topic)[key]
        except (BaseUnavailable, BaseProviderError, ValueError) as exc:
            raise HTTPException(
                503,
                detail={
                    "error": {
                        "code": "BASE_UNAVAILABLE",
                        "message": "飞书实时洞察暂不可用，请检查 Base 配置或品类数据",
                    }
                },
            ) from exc
    """策展数据：有社媒证据取真实数据，否则回退 fixtures"""
    try:
        from app.insights.loaders.social_evidence import SocialEvidenceLoader
        return SocialEvidenceLoader().get_insight_bundle(topic)[key]
    except FileNotFoundError:
        return fallback


@router.get("/insight-base")
async def insight_base(topic: str = "小风扇"):
    return _load_curated_module(topic, "insightBase", fixtures.INSIGHT_BASE)


@router.get("/trend-gallery")
async def trend_gallery(topic: str = "小风扇"):
    return _load_curated_module(topic, "trendGallery", fixtures.TREND_GALLERY)


@router.get("/data-board")
async def data_board():
    """数据看板：Feishu 模式读取实时明细，其他模式才展示 fixture。"""
    mode = os.getenv("BASE_PROVIDER_MODE", "disabled").strip().lower()
    if mode == "feishu":
        try:
            return await asyncio.to_thread(build_live_data_board)
        except (BaseUnavailable, BaseProviderError, ValueError) as exc:
            logger.exception("Feishu 实时看板读取失败")
            raise HTTPException(
                503,
                detail={
                    "error": {
                        "code": "BASE_UNAVAILABLE",
                        "message": "飞书实时数据暂不可用，请检查 Base 配置、权限或数据表内容",
                    }
                },
            ) from exc
    return {
        **fixtures.DATA_BOARD,
        "priceBands": fixtures.COMPETITIVE_MAP["priceBands"],
        "dataSource": "fixture",
        "sourceLabel": "本地演示数据（仅 BASE_PROVIDER_MODE 非 feishu 时）",
    }


_TREND_SCAN_FILE = Path(__file__).resolve().parents[2] / "data" / "trend_scan_snapshot.json"


@router.get("/trend-scan")
async def trend_scan():
    """趋势价值打分快照（scripts/trend_scan.py 生成）

    非破坏式集成：主链路不依赖本端点；快照存在则返回趋势卡 +
    思考过程日志，供前端/答辩展示"四维打分是真算法"。
    """
    if not _TREND_SCAN_FILE.exists():
        return {"available": False, "message": "尚未生成，运行 scripts/trend_scan.py"}
    return {"available": True, **json.loads(_TREND_SCAN_FILE.read_text(encoding="utf-8"))}
