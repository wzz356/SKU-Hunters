"""LangGraph 编排 — 五幕圆桌会议图 + 双门人在回路

拓扑（与全景设计文档 4.2/5.5 一致）：

    START → brief_node ─┬─→ trend_agent ─┐
                        ├─→ user_agent  ─┼─→ 🚪act1_gate ─→ creative_agent ─→ 三质询(fan-in) ─→ business_agent ─→ gtm_agent ─→ decision_engine
                        └─→ ip_agent    ─┘        ↕ qa
                                                                                                        │
                              ┌─ retro_qa ←→ 🚪retro_gate ←─ learning_node ←─ 🚪human_gate ←──────────┘
                              ↓            （首次复盘入口：    ↕ qa        （Gate 2 结论即归档：
                              └──────────→ learning_node       chat/done，   bad case 同等入档）
                                            （幂等：复盘轮数     不打回重做）
                                             追加入档）→ END

归档不是封存：learning_node 首过建档，复盘窗结束后二过把 retro_turns 追加入档；
归档后仍可通过 API 历史复盘入口随时追问（见 routes.py POST /reviews/{id}/retro）。

关键设计：
- 真/假 Agent 零成本替换：节点是薄包装层，只认 AGENT_REGISTRY 注册表
- 双门 interrupt：超时逻辑不在图里，由 run_review 的 ask_human 回调实现
- run_review(brief) → async iterator，事件格式 {"role","content","evidence","score"}
"""

from __future__ import annotations

import atexit
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.business_agent import get_business_agent_class
from app.agents.challenge_agents import CHALLENGE_REGISTRY
from app.agents.creative_agent import get_creative_agent_class
from app.agents.creative_contract import validate_proposals
from app.agents.gtm_agent import get_gtm_agent_class
from app.agents.ip_agent import get_ip_agent_class
from app.agents.learning_agent import get_learning_agent_class
from app.agents.trend_agent import get_trend_agent_class
from app.agents.user_agent import get_user_agent_class
from app.engine import llm
from app.engine.connector_gateway import (
    resolve_connectors,
    resolve_views,
    resolve_write_port,
)
from app.engine.context_contract import (
    validate_business_context,
    validate_gtm_context,
)
from app.engine.decision_engine import DecisionEngine
from app.engine.ledger import query_analogs
from app.engine.state import CommitteeState
from app.schemas import (
    Brief,
    ChallengeRecord,
    Confidence,
    ConflictRecord,
    ConflictType,
    FeatureMatrix,
    GTMPlan,
    IPAssessment,
    OpportunityScore,
    ProposalSet,
    RetroReport,
    UserSentiment,
    Weights,
    WeightTemplate,
)

# D5：SQLite checkpoint——归档后随时复盘跨重启成立。
# 设置 CHIN_CHIN=sqlite → 写 data/checkpoints.db；否则退回 MemorySaver
#
# 序列化安全：把 app.schemas 中会进入 state dict 的枚举类型显式注册到
# allowed_msgpack_modules，消除 "Deserializing unregistered type" 警告，
# 并保证 LANGGRAPH_STRICT_MSGPACK=true 严格模式下也能正常反序列化。
_CHECKPOINT_DB = Path(__file__).resolve().parents[3] / "data" / "checkpoints.db"
_CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)

_ALLOWED_MSGPACK_TYPES: set[tuple[str, str]] = {
    ("app.schemas.brief", "WeightTemplate"),
    ("app.schemas.brief", "BudgetRange"),
    ("app.schemas.challenge", "ChallengeStance"),
    ("app.schemas.evidence", "Confidence"),
    ("app.schemas.recommendation", "Decision"),
    ("app.schemas.review", "ConflictType"),
    ("app.schemas.testcase", "Outcome"),
}
try:
    _serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_TYPES)
except TypeError:
    _serde = JsonPlusSerializer()

# 懒加载单例：图全走 async 路径，checkpointer 首次使用时异步初始化。
# SQLite 用 AsyncSqliteSaver（同步 SqliteSaver 不支持 astream）；
# 连接常驻，保证跨进程/跨重启恢复成立。
_checkpointer: Any = None


async def _get_checkpointer():
    """返回 checkpointer 单例（首次调用时初始化）。

    - CHIN_CHIN=sqlite → AsyncSqliteSaver 写 data/checkpoints.db
    - 否则 → MemorySaver
    """
    global _checkpointer
    if _checkpointer is None:
        if os.environ.get("CHIN_CHIN") == "sqlite":
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            # aiosqlite 的工作线程默认非 daemon，会在进程退出时被
            # threading._shutdown 阻塞 join，导致 CLI 无法退出。
            # connect() 返回懒连接（线程未启动），先设 daemon 再 await。
            # 连接引用存模块级，防 GC 关闭。
            global _SQLITE_CONN
            _conn = aiosqlite.connect(str(_CHECKPOINT_DB))
            _conn._thread.daemon = True
            _SQLITE_CONN = await _conn
            _checkpointer = AsyncSqliteSaver(_SQLITE_CONN, serde=_serde)
        else:
            _checkpointer = MemorySaver(serde=_serde)
    return _checkpointer


def _close_sqlite():
    """解释器退出时关闭 aiosqlite 连接，终结其非 daemon 工作线程。

    该线程默认非 daemon，threading._shutdown 会 join 它导致 CLI 在流程
    结束后挂起。conn.close() 会把 close_and_stop 压入内部队列，工作线程
    处理后退出。用独立事件循环执行（原循环此时通常已关闭）。
    """
    conn = globals().get("_SQLITE_CONN")
    if conn is None:
        return
    try:
        import asyncio

        asyncio.run(conn.close())
    except Exception:  # noqa: BLE001,S110 — 退出清理失败不影响主流程
        pass


atexit.register(_close_sqlite)

# ── Agent 注册表：真 Agent 出炉后只改这里 ──────────────────────
# 六官均支持环境变量切换：默认 Mock（离线/确定/快），
# 设 <ROLE>_AGENT_PROVIDER=real 或总开关 AGENT_PROVIDER=real 启用真 LLM Agent
# （数据/LLM 故障时真 Agent 内部自动回退 Mock，会议不阻塞）；
# user/ip/business 另支持 <ROLE>_AGENT_PROVIDER=deterministic 启用
# 确定性真实实现（不烧 LLM，分数全部来自 Scoped View 聚合）。
# 注意：注册表在 import 时求值，env 必须在进程启动前设置。
AGENT_REGISTRY: dict[str, type] = {
    "trend": get_trend_agent_class(),
    "user": get_user_agent_class(),
    "ip": get_ip_agent_class(),
    "creative": get_creative_agent_class(),
    "business": get_business_agent_class(),
    "gtm": get_gtm_agent_class(),
    "learning": get_learning_agent_class(),
}

# ── Agent 短键 → AGENT_DATA_ACCESS 白名单键映射 ────────────────
_AGENT_ACCESS_KEY = {
    "trend": "trend_agent",
    "user": "consumer_insight_agent",
    "ip": "ip_strategy_agent",
    "creative": "product_ideation_agent",
    "business": "business_evaluation_agent",
    "gtm": "go_to_market_agent",
    "learning": "learning_agent",
}


def _instantiate_agent(agent_key: str):
    """经数据网关实例化 agent：只注入白名单内的 connector 与 Scoped View（信息隔离）

    只有真实 TrendAgent 访问原始数据源（google_trends / bilibili_ranking），
    经 resolve_connectors 按白名单注入；其余 mock agent 不访问 connector。
    product_ideation_agent 的白名单不含原始数据源，创意官物理上拿不到它们。
    Scoped View 经 resolve_views 注入（创意官 views 为空 → 不见数据）；
    复盘写入端口经 resolve_write_port 注入（仅 learning_agent 有）。
    Agent 拿到的永远是能力对象（View / 写入端口），不持有原始 BaseDataAdapter。
    """
    agent_cls = AGENT_REGISTRY[agent_key]
    access_key = _AGENT_ACCESS_KEY.get(agent_key)
    if access_key is None:
        return agent_cls()
    connectors = resolve_connectors(access_key)
    views = resolve_views(access_key)            # Scoped View（创意官为空 dict）
    write_port = resolve_write_port(access_key)  # 复盘写入端口（当前仅 learning 有）
    if agent_key == "trend":
        from app.agents.trend_agent import TrendAgent
        if issubclass(agent_cls, TrendAgent):
            agent = agent_cls(
                google_connector=connectors.get("google_trends"),
                bilibili_connector=connectors.get("bilibili_ranking"),
            )
        else:
            agent = agent_cls()
    else:
        agent = agent_cls()
    # 能力对象注入：Agent 经网关拿 View/写入端口，而非 raw adapter
    agent.views = views
    agent.write_port = write_port
    return agent

# ── 权重模板：把参数问题翻译成业务语言（剧本 5.4）──────────────
_TEMPLATE_WEIGHTS = {
    WeightTemplate.DEFAULT: Weights(),
    WeightTemplate.VOLUME: Weights(
        trend_heat=0.25, user_demand=0.40, ip_fit=0.15,
        competition=0.10, history_analog=0.10,
    ),
    WeightTemplate.IMAGE: Weights(
        trend_heat=0.45, user_demand=0.20, ip_fit=0.20,
        competition=0.05, history_analog=0.10,
    ),
    WeightTemplate.PROFIT: Weights(
        trend_heat=0.30, user_demand=0.20, ip_fit=0.20,
        competition=0.15, history_analog=0.15,
    ),
}


# ══════════════════ 节点 ══════════════════

async def brief_node(state: CommitteeState) -> dict[str, Any]:
    """BRIEF_LOCKED：冻结输入，解析权重"""
    brief = Brief.model_validate(state["brief"])
    weights = brief.custom_weights or _TEMPLATE_WEIGHTS[brief.weight_template]
    return {
        "weights": weights.model_dump(),
        "current_act": "brief",
        "review_logs": [{"node": "brief_node", "act": "brief", "status": "locked"}],
    }


def _feedback(state: CommitteeState) -> str:
    """提取最近一次人工修改意见（供重跑的 Agent 参考）"""
    decision = state.get("human_decision") or {}
    if decision.get("action") == "modify":
        return decision.get("suggestion", "")
    return ""


def _check_evidence(dump: dict[str, Any], agent_key: str, act: str) -> list[dict]:
    """铁律之二：无证据不得发言。

    证据非空 → 放行；证据为空但声明 UNKNOWN → 合法，记 C5 冲突；
    证据为空且自称有把握 → 拒绝（数据不足却硬编结论）。
    """
    if dump.get("evidence_refs"):
        return []
    if dump.get("confidence") == Confidence.UNKNOWN.value:
        return [
            ConflictRecord(
                conflict_type=ConflictType.C5_INSUFFICIENT,
                parties=[agent_key],
                description="证据不足，该委员声明无法判断",
                resolution="open",
                act=act,
            ).model_dump()
        ]
    raise ValueError(f"{agent_key} 输出缺少证据引用（无证据不得发言）")


def _make_insight_node(agent_key: str, artifact_key: str, schema: type):
    """ACT1 洞察官节点工厂：三官并行，各自写自己的 artifact 键"""

    async def node(state: CommitteeState) -> dict[str, Any]:
        agent = _instantiate_agent(agent_key)
        raw = await agent.run({
            "brief": state["brief"],
            "feedback": _feedback(state),
        })
        artifact = schema.model_validate(raw).model_dump(mode="json")
        return {
            artifact_key: artifact,
            # 注意：并行节点不写 current_act 等共享标量键，
            # 否则 LastValue channel 报并发写冲突；幕标记由下游门节点写
            "conflicts": _check_evidence(artifact, agent_key, "act1"),
            "review_logs": [{"node": agent_key, "act": "act1", "status": "ok"}],
        }

    return node


def _make_challenge_node(agent_key: str):
    """ACT2 质询节点工厂：创意官产出后，各洞察官对方案发起结构化质询"""
    async def node(state: CommitteeState) -> dict[str, Any]:
        agent = CHALLENGE_REGISTRY[agent_key]()
        raw = await agent.run({
            "brief": state["brief"],
            "proposal_set": state["proposal_set"],
        "challenges": state.get("challenges", []),
            "feature_matrix": state.get("feature_matrix"),
            "user_sentiment": state.get("user_sentiment"),
            "ip_assessment": state.get("ip_assessment"),
        })
        challenges = [
            ChallengeRecord.model_validate(c).model_dump(mode="json")
            for c in raw["challenges"]
        ]
        return {
            "challenges": challenges,
            "review_logs": [{"node": f"{agent_key}_challenge", "act": "act2", "status": "ok"}],
        }
    return node


async def creative_node(state: CommitteeState) -> dict[str, Any]:
    """ACT2 创意官：汇聚三方情报（fan-in）"""
    agent = _instantiate_agent("creative")
    raw = await agent.run({
        "brief": state["brief"],
        "feature_matrix": state.get("feature_matrix"),
        "user_sentiment": state.get("user_sentiment"),
        "ip_assessment": state.get("ip_assessment"),
        "feedback": _feedback(state),
        # 学习官台账：历史被否方案做负例（Mock 忽略多余键，透明）
        "history_analogs": query_analogs(state["brief"].get("category", "")),
    })
    # 四项契约校验（graph 边界强制：Mock 与真实输出都经过，非法输出不能进入 business）
    validate_proposals(
        raw.get("proposals", []),
        state["brief"],
        state.get("feature_matrix"),
        state.get("user_sentiment"),
        state.get("ip_assessment"),
    )
    return {
        "proposal_set": ProposalSet.model_validate(raw).model_dump(mode="json"),
        "current_act": "act2",
        "review_logs": [{"node": "creative", "act": "act2", "status": "ok"}],
    }


async def business_node(state: CommitteeState) -> dict[str, Any]:
    """ACT3 商业官：对每个提案出五维评分（算术由 schema 强制校验）"""
    upstream = [
        state.get("feature_matrix", {}).get("confidence", "unknown"),
        state.get("user_sentiment", {}).get("confidence", "unknown"),
        state.get("ip_assessment", {}).get("confidence", "unknown"),
    ]
    context = {
        "brief": state["brief"],
        "weights": state["weights"],
        "proposal_set": state["proposal_set"],
        "challenges": state.get("challenges", []),
        "upstream_confidences": upstream,
        # 真商业官的评审材料（Mock 忽略多余键，透明）
        "feature_matrix": state.get("feature_matrix"),
        "user_sentiment": state.get("user_sentiment"),
        "ip_assessment": state.get("ip_assessment"),
        "feedback": _feedback(state),
        # 学习官台账：history_analog 维度的真实材料（飞轮闭环）
        "history_analogs": query_analogs(state["brief"].get("category", "")),
    }
    validate_business_context(context)  # 三官 Artifact 缺失 → ContextContractError，阻断 Agent 调用
    agent = _instantiate_agent("business")
    raw = await agent.run(context)
    scores = [
        OpportunityScore.model_validate(s).model_dump(mode="json")
        for s in raw["opportunity_scores"]
    ]
    return {
        "opportunity_scores": scores,
        "current_act": "act3",
        "review_logs": [{"node": "business", "act": "act3", "status": "ok"}],
    }


async def gtm_node(state: CommitteeState) -> dict[str, Any]:
    """ACT3 全球化官（商业官之后串行：需 opportunity_scores 上游结果）"""
    context = {
        "brief": state["brief"],
        "proposal_set": state["proposal_set"],
        "challenges": state.get("challenges", []),
        "opportunity_scores": state["opportunity_scores"],
        "ip_assessment": state["ip_assessment"],
        "feedback": _feedback(state),
    }
    validate_gtm_context(context)  # 上游结果缺失 → ContextContractError，阻断 Agent 调用
    agent = _instantiate_agent("gtm")
    raw = await agent.run(context)
    plans = [
        GTMPlan.model_validate(p).model_dump(mode="json") for p in raw["gtm_plans"]
    ]
    return {
        "gtm_plans": plans,
        "review_logs": [{"node": "gtm", "act": "act3", "status": "ok"}],
    }


async def decision_node(state: CommitteeState) -> dict[str, Any]:
    """ACT4 Decision Engine：合成立项建议书"""
    conflicts = list(state.get("conflicts", []))
    for c in state.get("challenges", []):
        conflicts.append(ConflictRecord(
            conflict_type=ConflictType.C2_QUOTE_DEVIATION,
            parties=[c.get("source_role", "committee")],
            description=(
                f"[质询·{c.get('stance', '')}] "
                f"{c.get('proposal_name', '')}：{c.get('content', '')}"
            ),
            resolution="open",
            act="act2",
        ).model_dump())
    rec = DecisionEngine().synthesize(
        proposal_set=state["proposal_set"],
        opportunity_scores=state["opportunity_scores"],
        conflicts=conflicts,
    )
    return {
        "recommendation": rec.model_dump(mode="json"),
        "current_act": "act4",
        "review_logs": [{"node": "decision_engine", "act": "act4", "status": "ok"}],
    }


# ── 双门 ────────────────────────────────────

def _gate(decision: dict[str, Any], act: str) -> dict[str, Any]:
    """门节点公共返回：记录人工决定；修改/否决记 C4 人机冲突（人赢，留理由）

    reweight（modify + custom_weights）时把新权重写进 state，商业官重算即生效。
    """
    action = decision.get("action", "confirm")
    update: dict[str, Any] = {
        "human_decision": decision,
        "current_act": act,
        "review_logs": [{"node": act, "decision": action,
                         "detail": decision.get("suggestion")
                         or decision.get("reason")
                         or decision.get("question", "")}],
    }
    if action in ("modify", "reject"):
        reason = decision.get("suggestion") or decision.get("reason", "")
        prefix = "人否决立项" if action == "reject" else "人工要求修改"
        update["conflicts"] = [
            ConflictRecord(
                conflict_type=ConflictType.C4_HUMAN_AI,
                parties=["human", "committee"],
                description=f"{prefix}：{reason}",
                resolution="resolved",
                act=act,
            ).model_dump()
        ]
    if decision.get("custom_weights"):
        update["weights"] = Weights.model_validate(
            decision["custom_weights"]
        ).model_dump()
    return update


async def act1_gate(state: CommitteeState) -> dict[str, Any]:
    """🚪 Gate 1：洞察确认门——方向不对趁早打回，省掉后面 2/3 计算"""
    decision = interrupt({
        "gate": "act1_gate",
        "prompt": "三位洞察官已完成陈述，请确认方向（确定/修改/疑问）",
        "options": ["confirm", "modify", "question"],
    })
    return _gate(decision, "act1_gate")


async def human_gate(state: CommitteeState) -> dict[str, Any]:
    """🚪 Gate 2：立项拍板门——AI 建议在此刻变成人的决策，留痕"""
    decision = interrupt({
        "gate": "human_gate",
        "prompt": "立项建议书已生成，请拍板（确定/修改/疑问）",
        "options": ["confirm", "modify", "question"],
    })
    return _gate(decision, "human_gate")


def _make_qa_node(gate: str):
    """疑问节点：只读 state 作答，不污染任何 artifact，答完回到同一个门"""

    def node(state: CommitteeState) -> dict[str, Any]:
        question = (state.get("human_decision") or {}).get("question", "")
        artifacts = [
            k for k in ("feature_matrix", "user_sentiment", "ip_assessment",
                        "proposal_set", "opportunity_scores", "recommendation")
            if state.get(k)
        ]
        answer = (
            f"关于「{question}」：当前会议已产出 {len(artifacts)} 份产物"
            f"（{', '.join(artifacts)}），每条结论的证据见对应委员卡片的"
            f"证据来源栏。（QA 节点占位，接入 LLM 后基于证据链作答）"
        )
        return {
            "current_act": f"qa@{gate}",
            "review_logs": [{"node": f"qa@{gate}", "act": gate, "answer": answer}],
        }

    return node


# ── 会后复盘（归档前置：归档不是封存，是任务进入历史库）─────────────

async def retro_gate(state: CommitteeState) -> dict[str, Any]:
    """🚪 首次复盘入口：归档已完成，不打回重做；人可对话、总结教训

    chat/question → retro_qa 作答后回到本窗；done → 学习官把复盘轮数追加入档。
    归档后随时可再复盘（API 历史入口），本窗只是"任务结束时的第一次"。
    """
    decision = interrupt({
        "gate": "retro",
        "prompt": "已归档。可趁热复盘：提问、讨论、总结教训（chat），或稍后再聊（done）",
        "options": ["chat", "done"],
    })
    decision = decision or {"action": "done"}
    return {
        "human_decision": decision,
        "current_act": "retro",
        "review_logs": [{"node": "retro_gate", "decision": decision.get("action", "done"),
                         "detail": decision.get("question")
                         or decision.get("content", "")}],
    }


_DIM_LABEL = {
    "trend_heat": "趋势热度", "user_demand": "用户需求", "ip_fit": "IP契合",
    "competition": "竞争格局", "history_analog": "历史类比",
}


def _state_digest(state: CommitteeState) -> str:
    """把本场会议产物压成纯文本摘要，供 LLM 复盘作答

    必须包含：权重、每个方案的五维分项、质询立场、落选方案、分歧——
    否则"为什么落选/权重影响"类问题在材料里无据可查，助手只能说不知道。
    """
    parts = []
    if fm := state.get("feature_matrix"):
        parts.append(f"趋势官：{fm.get('summary', '')}")
    if us := state.get("user_sentiment"):
        parts.append(f"用户官：{us.get('summary', '')}")
    if ip := state.get("ip_assessment"):
        parts.append(f"IP官：{ip.get('strategy_note', '')}")
    if w := state.get("weights"):
        parts.append(
            "五维权重（本案实际使用）："
            + "，".join(f"{_DIM_LABEL.get(k, k)} {float(w.get(k, 0)):.0%}" for k in _DIM_LABEL)
        )
    for s in state.get("opportunity_scores", []):
        dims = "，".join(
            f"{_DIM_LABEL.get(d.get('dimension'), d.get('dimension'))} {d.get('score', 0):.0f}"
            for d in s.get("dimension_scores", [])
        )
        parts.append(
            f"商业官评分：{s.get('proposal_name', '')} 总分 {s.get('total_score', 0):.1f}"
            f"（{dims}）"
        )
        for r in s.get("risk_warnings", []):
            parts.append(
                f"  风险提示[{s.get('proposal_name', '')}]：{r.get('risk', '')}"
                f"（来源维度：{_DIM_LABEL.get(r.get('source_dimension'), r.get('source_dimension', ''))}）"
            )
    for c in state.get("challenges", []):
        stance = {"endorse": "背书", "revise": "修正", "oppose": "反对"}.get(
            c.get("stance"), c.get("stance", "")
        )
        parts.append(
            f"质询[{c.get('source_role', '')}] {stance}「{c.get('proposal_name', '')}」："
            f"{c.get('content', '')[:60]}"
        )
    if rec := state.get("recommendation"):
        parts.append(
            f"立项建议：{rec.get('decision', '')}，"
            f"Top1「{rec.get('proposal', {}).get('name', '')}」，"
            f"{rec.get('summary', '')}"
        )
        for r in rec.get("runner_ups", []):
            parts.append(f"落选方案：{r}")
        for cond in rec.get("conditions", []):
            parts.append(f"前置条件：{cond}")
    for c in state.get("conflicts", []):
        parts.append(f"分歧记录：{c.get('description', '')[:80]}")
    return "\n".join(parts)


def retro_answer(digest: str, question: str) -> str:
    """复盘作答（图内 retro_qa 与 API 历史复盘入口共用）：
    LLM 基于本场证据链回答；无 Key/故障时降级为产物索引"""
    answer = llm.complete(
        system_prompt=(
            "你是 SKU Hunters 商品评审会的复盘助手。基于给定的本场会议产物，"
            "回答商品经理的问题、帮助总结教训。只依据给定材料作答，禁止编造"
            "材料中不存在的数字；材料里没有的信息直接说明。150 字以内。"
        ),
        user_prompt=f"【本场会议产物】\n{digest}\n\n【商品经理的问题】\n{question}",
        max_tokens=400,
    )
    if answer is None:
        answer = (
            f"关于「{question}」：本场会议产物摘要如下——\n{digest}\n"
            f"（LLM 未配置或暂不可用，以上为原始产物索引）"
        )
    return answer


def retro_qa_node(state: CommitteeState) -> dict[str, Any]:
    """复盘作答：只读 state，不污染任何 artifact"""
    decision = state.get("human_decision") or {}
    question = decision.get("question") or decision.get("content", "")
    answer = retro_answer(_state_digest(state), question)
    return {
        "current_act": "retro",
        "review_logs": [{"node": "retro", "act": "retro",
                         "question": question, "answer": answer}],
    }


async def learning_node(state: CommitteeState) -> dict[str, Any]:
    """ACT5 学习官：建档（首过）/ 复盘轮数追加入档（二过）——幂等

    bad case（人否决）与通过案同等归档：人决策 + 复盘对话是最宝贵的训练信号。
    归档不是封存：snapshot 先进历史库，复盘对话作为 retro_logs 后续追加。
    """
    rec = state.get("recommendation", {})
    logs = state.get("review_logs", [])
    retro_turns = sum(1 for log in logs if log.get("node") == "retro")
    existing = next(
        (log.get("snapshot") for log in reversed(logs)
         if log.get("node") == "learning" and log.get("snapshot")),
        None,
    )
    if existing is not None:
        # 二过：复盘窗结束，把对话轮数追加进档案（归档 ≠ 封存）
        snapshot = {**existing, "retro_turns": retro_turns}
        return {
            "current_act": "act5",
            "review_logs": [{"node": "learning", "act": "act5",
                             "appended": True, "snapshot": snapshot}],
        }
    gate2 = next(
        (log for log in reversed(logs) if log.get("node") == "human_gate"), {}
    )
    snapshot = {
        "session_id": state.get("session_id", ""),
        "proposal": rec.get("proposal", {}).get("name", ""),
        "predicted_score": rec.get("opportunity_score", {}).get("total_score"),
        "ai_decision": rec.get("decision", ""),
        "human_action": gate2.get("decision", ""),
        "retro_turns": retro_turns,
        "status": "rejected" if gate2.get("decision") == "reject" else "archived",
    }
    # 首过：经学习官生成归一化实际信号 + 复盘报告（不伪造销量/上市结果）
    agent = _instantiate_agent("learning")
    learning_ctx = {
        "brief": state["brief"],
        "category": state["brief"].get("category", ""),
        "market": state["brief"].get("market", ""),
        "proposal": rec.get("proposal", {}),
        "opportunity_score": rec.get("opportunity_score", {}),
        "decision": rec.get("decision", ""),
        "human_action": snapshot["human_action"],
        "session_id": state.get("session_id", ""),
        "snapshot_id": state.get("session_id", ""),
    }
    learning_out = await agent.run(learning_ctx)
    retro_report = learning_out["retro_report"]
    RetroReport.model_validate(retro_report)  # 复盘契约校验：失败即阻断
    normalized = learning_out["normalized_actual_signal"]
    snapshot = {
        **snapshot,
        "normalized_actual_signal": normalized,
        "retro_report": retro_report,
    }
    return {
        "current_act": "act5",
        "retro_reports": [retro_report],
        "review_logs": [{
            "node": "learning", "act": "act5",
            "snapshot": snapshot,
            "normalized_actual_signal": normalized,
        }],
    }


# ── 门路由 ───────────────────────────────────

def _route_act1_gate(state: CommitteeState) -> Any:
    action = (state.get("human_decision") or {}).get("action", "confirm")
    if action == "modify":
        # 创意官尚未跑，全场最便宜的回退点：三洞察官重跑
        return ["trend_agent", "user_agent", "ip_agent"]
    if action == "question":
        return "qa_act1_node"
    return "creative_agent"


def _route_human_gate(state: CommitteeState) -> str:
    decision = state.get("human_decision") or {}
    action = decision.get("action", "confirm")
    if action == "modify":
        # 最小失效：参数微调只回退商业官重算，方案大改才回退创意官
        if decision.get("scope") == "creative":
            return "creative_agent"
        return "business_agent"
    if action == "question":
        return "qa_act4_node"
    # confirm / reject 都先归档（bad case 同等入档），再开首次复盘入口
    return "learning_node"


def _route_retro_gate(state: CommitteeState) -> str:
    action = (state.get("human_decision") or {}).get("action", "done")
    if action in ("chat", "question"):
        return "retro_qa_node"
    return "learning_node"


def _route_learning(state: CommitteeState) -> str:
    """learning_node 幂等路由：首过（刚建档）→ 首次复盘入口；二过（追加完成）→ END"""
    learnings = sum(
        1 for log in state.get("review_logs", []) if log.get("node") == "learning"
    )
    return END if learnings >= 2 else "retro_gate"


# ══════════════════ 建图 ══════════════════

def build_graph(checkpointer: Any = None) -> Any:
    g = StateGraph(CommitteeState)

    g.add_node("brief_node", brief_node)
    g.add_node("trend_agent", _make_insight_node("trend", "feature_matrix", FeatureMatrix))
    g.add_node("user_agent", _make_insight_node("user", "user_sentiment", UserSentiment))
    g.add_node("ip_agent", _make_insight_node("ip", "ip_assessment", IPAssessment))
    g.add_node("act1_gate", act1_gate)
    g.add_node("qa_act1_node", _make_qa_node("act1_gate"))
    g.add_node("creative_agent", creative_node)
    g.add_node("trend_challenge", _make_challenge_node("trend"))
    g.add_node("user_challenge", _make_challenge_node("user"))
    g.add_node("ip_challenge", _make_challenge_node("ip"))
    g.add_node("business_agent", business_node)
    g.add_node("gtm_agent", gtm_node)
    g.add_node("decision_engine", decision_node)
    g.add_node("human_gate", human_gate)
    g.add_node("qa_act4_node", _make_qa_node("human_gate"))
    g.add_node("retro_gate", retro_gate)
    g.add_node("retro_qa_node", retro_qa_node)
    g.add_node("learning_node", learning_node)

    g.add_edge(START, "brief_node")
    g.add_edge("brief_node", "trend_agent")
    g.add_edge("brief_node", "user_agent")
    g.add_edge("brief_node", "ip_agent")

    # ACT1 fan-in → Gate 1
    g.add_edge("trend_agent", "act1_gate")
    g.add_edge("user_agent", "act1_gate")
    g.add_edge("ip_agent", "act1_gate")
    g.add_conditional_edges("act1_gate", _route_act1_gate)
    g.add_edge("qa_act1_node", "act1_gate")

    # ACT2 → ACT2_CHALLENGE（三洞察官质询）→ ACT3 串行（business → gtm）
    g.add_edge("creative_agent", "trend_challenge")
    g.add_edge("creative_agent", "user_challenge")
    g.add_edge("creative_agent", "ip_challenge")
    g.add_edge("trend_challenge", "business_agent")
    g.add_edge("user_challenge", "business_agent")
    g.add_edge("ip_challenge", "business_agent")
    g.add_edge("business_agent", "gtm_agent")  # business → gtm 串行（gtm 需 opportunity_scores）

    # ACT3 → ACT4
    g.add_edge("gtm_agent", "decision_engine")
    g.add_edge("decision_engine", "human_gate")

    # Gate 2 → 归档 → 首次复盘入口 → 追加入档
    g.add_conditional_edges("human_gate", _route_human_gate)
    g.add_edge("qa_act4_node", "human_gate")
    g.add_conditional_edges("retro_gate", _route_retro_gate)
    g.add_edge("retro_qa_node", "retro_gate")
    g.add_conditional_edges("learning_node", _route_learning)

    return g.compile(checkpointer=checkpointer or _checkpointer)


# ══════════════════ 事件翻译 ══════════════════

def _evidence_of(artifact: dict[str, Any]) -> list[str]:
    """事件 evidence 只从产物 evidence_refs 提取，不允许自由发挥"""
    return [
        f"{ref['title']}：{ref['snippet']}"
        for ref in artifact.get("evidence_refs", [])
    ]


def _translate(node_name: str, update: dict[str, Any]) -> dict[str, Any] | None:
    """节点 state 更新 → 飞书卡片事件 {"role","content","evidence","score"}"""
    if node_name in ("trend_challenge", "user_challenge", "ip_challenge"):
        src = {"trend_challenge": "趋势官", "user_challenge": "用户官",
               "ip_challenge": "IP官"}[node_name]
        lines = []
        evidence = []
        for c in update["challenges"]:
            mark = {"endorse": "✅ 背书", "revise": "✏️ 修正", "oppose": "⛔ 反对"}
            lines.append(
                f"{mark.get(c['stance'], c['stance'])} 「{c['proposal_name']}」："
                f"{c['content']}"
            )
            for ref in c.get("evidence_refs", []):
                ev = f"{ref.get('title', '')}：{ref.get('snippet', '')}"
                if ev not in evidence:
                    evidence.append(ev)
        return {"role": "challenge", "content": f"{src} 质询：\n" + "\n".join(lines),
                "evidence": evidence, "score": None}
    if node_name == "trend_agent":
        a = update["feature_matrix"]
        return {"role": "trend", "content": a["summary"],
                "evidence": _evidence_of(a), "score": None}
    if node_name == "user_agent":
        a = update["user_sentiment"]
        return {"role": "user", "content": a["summary"],
                "evidence": _evidence_of(a), "score": None}
    if node_name == "ip_agent":
        a = update["ip_assessment"]
        top = a["ip_ranking"][0] if a["ip_ranking"] else {}
        content = (
            f"{a.get('strategy_note', '')}\n"
            f"首选 IP：{top.get('ip_name', '无')}"
            f"（热度 {top.get('heat_score', 0)}，窗口期 {top.get('window_estimate', '-')}）"
        )
        return {"role": "ip", "content": content,
                "evidence": _evidence_of(a), "score": None}
    if node_name == "creative_agent":
        a = update["proposal_set"]
        lines = [f"{i}. {p['name']}（{p['product_form']}，{p['price_band']}）"
                 for i, p in enumerate(a["proposals"], 1)]
        return {"role": "creative",
                "content": "创意方案：\n" + "\n".join(lines),
                "evidence": [], "score": None}
    if node_name == "business_agent":
        scores = update["opportunity_scores"]
        top = max(scores, key=lambda s: s["total_score"])
        lines = []
        for s in scores:
            dims = "，".join(
                f"{_DIM_LABEL.get(d.get('dimension'), d.get('dimension'))} "
                f"{d.get('score', 0):.0f}"
                for d in s.get("dimension_scores", [])
            )
            lines.append(f"· {s['proposal_name']}：{s['total_score']:.1f} 分（{dims}）")
        if w := (scores[0].get("weights_used") if scores else None):
            lines.append(
                "权重：" + "，".join(
                    f"{_DIM_LABEL.get(k, k)} {float(w.get(k, 0)):.0%}" for k in _DIM_LABEL
                )
            )
        return {"role": "business",
                "content": "五维机会值评分：\n" + "\n".join(lines),
                "evidence": _evidence_of(top), "score": top["total_score"]}
    if node_name == "gtm_agent":
        plans = update["gtm_plans"]
        lines = []
        for p in plans:
            stops = " → ".join(
                f"{c['country']}(批{c['batch']})" for c in p.get("country_plans", [])
            )
            lines.append(f"· {p['proposal_name']}：{stops}")
            if p.get("caveats"):
                lines.append(f"  保留：{p['caveats'][0]}")
        return {"role": "global",
                "content": f"上市策略 {len(plans)} 份：\n" + "\n".join(lines),
                "evidence": _evidence_of(plans[0]) if plans else [], "score": None}
    if node_name == "decision_engine":
        rec = update["recommendation"]
        return {"role": "decision",
                "content": rec["summary"],
                "evidence": _evidence_of(rec["opportunity_score"]),
                "score": rec["opportunity_score"]["total_score"],
                "report": rec}  # 完整建议书：API report 端点用，四键契约不变
    if node_name == "learning_node":
        log = update["review_logs"][-1]
        snap = log.get("snapshot", {})
        if log.get("appended"):
            # 二过：复盘轮数追加入档
            return {"role": "learning",
                    "content": (f"复盘对话 {snap.get('retro_turns', 0)} 轮已追加入档。"
                                f"历史库开放：随时可继续复盘追问。"),
                    "evidence": [], "score": None,
                    "snapshot": snap}  # 归档快照：API archive 用，四键契约不变
        bad = snap.get("status") == "rejected"
        return {"role": "learning",
                "content": (
                    f"已建档{'（bad case）' if bad else ''}："
                    f"「{snap.get('proposal', '')}」"
                    f"预测分 {snap.get('predicted_score')}，"
                    f"AI 建议 {snap.get('ai_decision')} / 人决策 {snap.get('human_action')}。"
                    f"归档不是封存：复盘对话将追加入档。"
                ),
                "evidence": [], "score": None,
                "snapshot": snap}  # 归档快照：API archive 用，四键契约不变
    if node_name == "retro_qa_node":
        answer = update["review_logs"][-1].get("answer", "")
        return {"role": "retro", "content": answer, "evidence": [], "score": None}
    if node_name.startswith("qa_"):
        answer = update["review_logs"][-1].get("answer", "")
        return {"role": "qa", "content": answer, "evidence": [], "score": None}
    return None  # brief_node / 门节点不产生委员事件


def _describe(decision: dict[str, Any]) -> str:
    action = decision.get("action", "confirm")
    if action == "modify":
        return f"✏️ 修改：{decision.get('suggestion', '')}（回退重跑）"
    if action == "reject":
        return f"❌ 否决立项：{decision.get('reason', '')}（归档为 bad case）"
    if action == "question":
        return f"❓ 疑问：{decision.get('question', '')}"
    if action == "chat":
        return f"💬 复盘：{decision.get('question') or decision.get('content', '')}"
    if action == "done":
        return "📝 本轮复盘结束（已归档，随时可再追问）"
    return "✅ 确定，继续"


# ══════════════════ 驱动入口 ══════════════════

AskHuman = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def _auto_confirm(gate_info: dict[str, Any]) -> dict[str, Any]:
    """默认问人回调：直接确定（CI/演示用；飞书侧实现带 10 秒超时的版本）"""
    return {"action": "confirm"}


async def run_review(
    brief: dict[str, Any],
    ask_human: AskHuman | None = None,
    session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """跑一轮完整评审，以异步事件流输出

    Args:
        brief: 评审输入（Brief 契约，dict 形式）
        ask_human: 门节点问人回调，返回 {"action": confirm/modify/question, ...}。
                   超时逻辑由调用方在此回调内实现（如 asyncio.wait_for 10s）。
        session_id: 会话 ID（checkpoint thread_id，可恢复）

    Yields:
        {"role", "content", "evidence", "score"} —— handler README 约定格式，
        门事件 role 为 act1_gate/human_gate，问答事件 role 为 qa。
    """
    ask = ask_human or _auto_confirm
    Brief.model_validate(brief)
    graph = build_graph(checkpointer=await _get_checkpointer())
    config = {"configurable": {"thread_id": session_id or str(uuid.uuid4())}}

    payload: Any = {
        "brief": brief,
        "session_id": config["configurable"]["thread_id"],
        "current_act": "init",
    }
    while True:
        pending_gate: dict[str, Any] | None = None
        async for chunk in graph.astream(payload, config, stream_mode="updates"):
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    pending_gate = update[0].value
                    continue
                event = _translate(node_name, update)
                if event:
                    yield event
        if pending_gate is None:
            return
        yield {"role": pending_gate["gate"], "content": pending_gate["prompt"],
               "evidence": [], "score": None}
        decision = await ask(pending_gate)
        yield {"role": pending_gate["gate"], "content": _describe(decision),
               "evidence": [], "score": None}
        payload = Command(resume=decision)
