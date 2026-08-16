"""Mock Agents — 编排层先行验证用的假 Agent

返回固定的、通过 schema 校验的产物（model_dump 后的 dict），
让 LangGraph 图的并行/汇聚/interrupt 在真 Agent 就绪前先跑通。

真 Agent 出炉后：只需在 graph.py 的 AGENT_REGISTRY 里替换类，
图结构与节点包装层零改动。
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base_agent import BaseAgent
from app.schemas import (
    Confidence,
    CountryPlan,
    DimensionScore,
    EvidenceRef,
    FeatureMatrix,
    GTMPlan,
    IPAssessment,
    IPCandidate,
    OpportunityScore,
    PainPoint,
    ProductProposal,
    ProposalSet,
    RiskWarning,
    SentimentStat,
    SourceRef,
    TrendItem,
    UserSentiment,
    Weights,
)


def _min_confidence(values: list[str]) -> Confidence:
    """置信度取最低值——沿链路衰减，不放大（实现已迁 real_common.min_confidence）"""
    from app.agents.real_common import min_confidence

    return min_confidence(values)


class MockTrendAgent(BaseAgent):
    """假趋势官：固定 FeatureMatrix"""

    name = "trend_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")
        return FeatureMatrix(
            category=category,
            region=brief.get("market", "global"),
            trends=[
                TrendItem(
                    keyword=f"{category}解压",
                    heat_index=92,
                    platform="taobao",
                    lifecycle="rising",
                ),
                TrendItem(
                    keyword="桌面美学",
                    heat_index=74,
                    platform="bilibili",
                    lifecycle="rising",
                ),
            ],
            summary=f"「{category}」搜索增速 180%，处于上升期；桌面场景讨论量同步走高。",
            analysis_date="2026-08-09",
            evidence_refs=[
                EvidenceRef(
                    url="https://s.taobao.com/search?q=mock",
                    title="淘宝搜索联想词",
                    snippet=f"{category}相关联想词环比增速 180%",
                ),
                EvidenceRef(
                    url="https://www.bilibili.com/v/popular/rank/mock",
                    title="B站分区排行",
                    snippet="桌面美学类视频周榜占比提升",
                ),
            ],
            confidence=Confidence.HIGH,
        ).model_dump()


class MockUserAgent(BaseAgent):
    """假用户官：固定 UserSentiment"""

    name = "consumer_insight_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")
        return UserSentiment(
            product_category=category,
            sentiment=SentimentStat(positive=0.62, neutral=0.28, negative=0.10),
            pain_points=[
                PainPoint(
                    description="盲盒没地方放，工位收纳困难",
                    frequency=0.41,
                    severity="high",
                ),
                PainPoint(description="工位缺摆件装饰，香薰夜灯需求上升", frequency=0.35),
            ],
            motivation_tags=["收藏", "工位装饰", "解压"],
            summary="工位场景痛点密度高，收藏+解压是前两大购买动机。",
            evidence_refs=[
                EvidenceRef(
                    url="https://www.bilibili.com/video/mock",
                    title="B站评论抽样（n=500）",
                    snippet="41% 评论提及收纳/摆放痛点",
                ),
            ],
            confidence=Confidence.MEDIUM,
        ).model_dump()


class MockIPAgent(BaseAgent):
    """假 IP官：固定 IPAssessment"""

    name = "ip_strategy_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        return IPAssessment(
            category=brief.get("category", "潮玩"),
            market=brief.get("market", "CN"),
            ip_ranking=[
                IPCandidate(
                    ip_name="Chiikawa",
                    heat_score=85,
                    lifecycle_stage="peak",
                    window_estimate="6-9个月",
                    regional_fit=88,
                ),
                IPCandidate(
                    ip_name="Loopy",
                    heat_score=72,
                    lifecycle_stage="rising",
                    window_estimate="9-12个月",
                    regional_fit=80,
                ),
            ],
            licensing_risk="无已知风险",
            strategy_note="成熟形态快反，优先工位场景联名。",
            evidence_refs=[
                EvidenceRef(
                    url="https://mock.ip-licensing.example/chiikawa",
                    title="IP 授权信息库",
                    snippet="Chiikawa 窗口期 6-9 个月，东南亚付费意愿高",
                ),
            ],
            confidence=Confidence.MEDIUM,
        ).model_dump()


class MockCreativeAgent(BaseAgent):
    """假创意官：固定 3 个互异方案，source_map 覆盖三方情报"""

    name = "product_ideation_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")

        def _src(supports: str) -> list[SourceRef]:
            return [
                SourceRef(
                    artifact="FeatureMatrix",
                    claim="搜索增速 180%，处于上升期",
                    supports=supports,
                ),
                SourceRef(
                    artifact="UserSentiment",
                    claim="工位场景痛点密度高",
                    supports=supports,
                ),
                SourceRef(
                    artifact="IPAssessment",
                    claim="Chiikawa 窗口期 6-9 个月",
                    supports=supports,
                ),
            ]

        return ProposalSet(
            proposals=[
                ProductProposal(
                    name=f"{category}桌面摆件系列",
                    concept="Chiikawa 联名迷你桌面公仔，主打工位解压",
                    product_form="摆件",
                    target_segment="18-25岁女性白领",
                    price_band="¥39-59",
                    source_map=_src("形态与IP选择"),
                    differentiation="工位场景 + 收藏属性",
                ),
                ProductProposal(
                    name=f"{category}收纳挂袋系列",
                    concept="Loopy 联名盲盒收纳挂袋，解决没地方放",
                    product_form="收纳",
                    target_segment="学生党收藏玩家",
                    price_band="¥29-39",
                    source_map=_src("形态"),
                    differentiation="直击收纳痛点，低客单走量",
                ),
                ProductProposal(
                    name=f"{category}香薰夜灯系列",
                    concept="治愈系 IP 香薰夜灯，卧室场景延伸",
                    product_form="香薰夜灯",
                    target_segment="22-30岁独居青年",
                    price_band="¥59-69",
                    source_map=_src("人群与价格带"),
                    differentiation="场景差异化，避开摆件竞对红海",
                ),
            ],
            ideation_note="三方案在形态/场景/价位上互异，均通过预算过滤。",
        ).model_dump()


class MockBusinessAgent(BaseAgent):
    """假商业官：对每个提案出五维评分，总分为真实加权算术"""

    name = "business_evaluation_agent"

    # 每个提案的五维分项（trend/user/ip/competition/history），Top1 确定性最高
    _DIM_TABLE: ClassVar[dict[int, tuple[float, ...]]] = {
        0: (92.0, 78.0, 85.0, 60.0, 70.0),   # → 81.7
        1: (80.0, 88.0, 72.0, 55.0, 60.0),   # → 75.85
        2: (70.0, 65.0, 68.0, 62.0, 55.0),   # → 65.85
    }
    _DIM_META: ClassVar[list[tuple[str, str, str]]] = [
        ("trend_heat", "trend_agent", "搜索增速180%，上升期"),
        ("user_demand", "consumer_insight_agent", "工位痛点密度高"),
        ("ip_fit", "ip_strategy_agent", "窗口期与区域适配"),
        ("competition", "business_evaluation_agent", "同类在售数量"),
        ("history_analog", "business_evaluation_agent", "知识库相似案例表现"),
    ]

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        proposal_set = context.get("proposal_set", {})
        weights = Weights.model_validate(context.get("weights", {}))
        upstream = context.get("upstream_confidences", [])
        weight_map = weights.model_dump()

        scores = []
        for i, proposal in enumerate(proposal_set.get("proposals", [])):
            raw = self._DIM_TABLE.get(i, (60.0, 60.0, 60.0, 60.0, 60.0))
            dims = [
                DimensionScore(
                    dimension=name, score=raw[j],
                    source_agent=agent, basis=basis,
                )
                for j, (name, agent, basis) in enumerate(self._DIM_META)
            ]
            total = round(
                sum(d.score * weight_map[d.dimension] for d in dims), 2
            )
            scores.append(
                OpportunityScore(
                    proposal_name=proposal["name"],
                    dimension_scores=dims,
                    weights_used=weights,
                    total_score=total,
                    star_rating=max(1, min(5, round(total / 20))),
                    risk_warnings=[
                        RiskWarning(
                            risk="同类竞品密度高，窗口期内可能价格战",
                            source_dimension="competition",
                            severity="medium",
                        )
                    ],
                    upstream_confidence=_min_confidence(upstream),
                    evidence_refs=[
                        EvidenceRef(
                            url="https://mock.score.example/detail",
                            title="五维评分明细",
                            snippet=f"{proposal['name']} 加权总分 {total}",
                        )
                    ],
                    confidence=_min_confidence(upstream),
                ).model_dump()
            )
        return {"opportunity_scores": scores}


class MockGTMAgent(BaseAgent):
    """假全球化官（Phase 2 占位）：最小 GTMPlan"""

    name = "go_to_market_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        proposal_set = context.get("proposal_set", {})
        market = brief.get("market", "CN")
        plans = [
            GTMPlan(
                proposal_name=p["name"],
                country_plans=[
                    CountryPlan(
                        country=market,
                        batch=1,
                        price_band=p["price_band"],
                        timing="首批2周内",
                        rationale="目标市场区域适配度最高（占位）",
                    )
                ],
                localization_notes=["（Phase 2 占位）"],
            ).model_dump()
            for p in proposal_set.get("proposals", [])
        ]
        return {"gtm_plans": plans}
