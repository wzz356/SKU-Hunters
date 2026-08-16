"""D1 契约测试 — 验证关键 schema 校验器行为

由 scripts/validate_schemas.py 转化而来，作为 CI 回归测试：
改 schema 或权重逻辑时，这些约束不允许劣化。
"""

import pytest
from app.schemas import (
    Confidence,
    DimensionScore,
    OpportunityScore,
    ProductProposal,
    ProposalSet,
    SourceRef,
    Weights,
)
from pydantic import ValidationError


def _make_dims() -> list[DimensionScore]:
    """五维分项：92/78/85/60/70，对应文档中 83 分的解剖示例"""
    return [
        DimensionScore(dimension="trend_heat", score=92, source_agent="trend_agent", basis="搜索增速180%"),
        DimensionScore(dimension="user_demand", score=78, source_agent="consumer_insight_agent", basis="痛点密度高"),
        DimensionScore(dimension="ip_fit", score=85, source_agent="ip_strategy_agent", basis="区域适配好"),
        DimensionScore(dimension="competition", score=60, source_agent="business_evaluation_agent", basis="同类竞对多"),
        DimensionScore(dimension="history_analog", score=70, source_agent="business_evaluation_agent", basis="相似案例表现"),
    ]


def test_default_weights_sum_to_one():
    w = Weights()  # 默认 35/25/20/10/10
    assert abs(w.trend_heat + w.user_demand + w.ip_fit + w.competition + w.history_analog - 1.0) < 1e-9


def test_correct_arithmetic_accepted():
    """92*.35+78*.25+85*.20+60*.10+70*.10 = 81.7"""
    score = OpportunityScore(
        proposal_name="桌面摆件系列", dimension_scores=_make_dims(), weights_used=Weights(),
        total_score=81.7, star_rating=4, upstream_confidence=Confidence.MEDIUM,
    )
    assert score.total_score == 81.7


def test_wrong_arithmetic_rejected():
    """95 ≠ 81.7，必须被拦截——机会值是可追溯的算术，不是一种感觉"""
    with pytest.raises(ValidationError):
        OpportunityScore(
            proposal_name="作弊方案", dimension_scores=_make_dims(), weights_used=Weights(),
            total_score=95.0, star_rating=5, upstream_confidence=Confidence.MEDIUM,
        )


def test_invalid_weights_rejected():
    """权重和不为 1 应被拒绝"""
    with pytest.raises(ValidationError):
        Weights(trend_heat=0.5, user_demand=0.4, ip_fit=0.2, competition=0.1, history_analog=0.1)


def test_proposal_count_constraint():
    """提案数量必须为 3-5 个，空提案集应被拒绝"""
    with pytest.raises(ValidationError):
        ProposalSet(proposals=[])


def test_source_map_covers_three_insight_agents():
    """每个提案的 source_map 必须覆盖趋势/用户/IP 三方证据"""
    p = ProductProposal(
        name="桌面摆件系列", concept="IP联名迷你桌面公仔", product_form="摆件",
        target_segment="18-25岁女性", price_band="¥39-59", differentiation="收藏+工位场景",
        source_map=[
            SourceRef(artifact="FeatureMatrix", claim="趋势上升", supports="IP选择"),
            SourceRef(artifact="UserSentiment", claim="痛点明确", supports="形态"),
            SourceRef(artifact="IPAssessment", claim="窗口6-9月", supports="IP选择"),
        ],
    )
    assert sorted(p.covered_artifacts()) == ["FeatureMatrix", "IPAssessment", "UserSentiment"]
