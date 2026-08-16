"""CommitteeState — LangGraph 五幕编排的共享状态对象

贯穿圆桌会议全程的状态载体。对应剧本 0.2 会议状态机：
BRIEF_LOCKED → ACT1 → GATE → ACT2 → CHALLENGE → ACT3 → ACT4 → HUMAN_GATE → ACT5

设计要点：
- artifacts 存 dict（各 Schema 的 model_dump），节点间序列化安全
- conflicts/review_logs 用 operator.add 累积（LangGraph reducer），
  并行节点写入不互相覆盖
- human_decision 为 None 时 HUMAN_GATE 挂起（interrupt）
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class CommitteeState(TypedDict, total=False):
    """圆桌会议全局状态（total=False：各节点只写自己负责的键）"""

    # ── BRIEF_LOCKED ──
    brief: dict                       # Brief.model_dump()
    weights: dict                     # Weights.model_dump()（模板或自定义）

    # ── ACT1 洞察陈述（三官并行写入）──
    feature_matrix: dict              # 趋势官 FeatureMatrix
    user_sentiment: dict              # 用户官 UserSentiment
    ip_assessment: dict               # IP官 IPAssessment

    # ── ACT2 方案提出 ──
    proposal_set: dict                # 创意官 ProposalSet
    challenges: Annotated[list[dict], operator.add]   # 质询记录（背书/修正/反对）

    # ── ACT3 顺序评审（business 先，gtm 后串行）──
    opportunity_scores: list[dict]    # 商业官 OpportunityScore[]
    gtm_plans: list[dict]             # 全球化官 GTMPlan[]（Phase 2）

    # ── ACT4 决策输出 ──
    recommendation: dict              # 立项建议书（Decision Engine 合成）
    human_decision: dict | None       # 人工决定：approved/rejected/revised + 理由

    # ── ACT5 复盘 ──
    retro_reports: Annotated[list[dict], operator.add]

    # ── 贯穿全程 ──
    conflicts: Annotated[list[dict], operator.add]    # ConflictRecord 累积
    review_logs: Annotated[list[dict], operator.add]  # ReviewResult 累积
    current_act: str                  # 当前幕标记：brief/act1/act1_gate/...
    session_id: str                   # 会议 ID（多维表格台账外键）
