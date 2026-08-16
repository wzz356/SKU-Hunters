"""Competitive Map Agent — 回归测试

覆盖三件事：
1. 需求满足矩阵：评分必须绑 reason（裸数字丢弃）、竞品/需求引用命中真实数据。
2. 机会空位：supportsOpportunityIds 强绑机会池 id，命中不了丢弃（不生成新机会）。
3. schema 契约：CompetitorNeedScore 评分 0-5，OpportunityGap 带引用 id。
"""

from __future__ import annotations

from app.planning.competitive_map_agent import _build_matrix_and_gaps
from app.schemas.planning import CompetitorNeedScore, OpportunityGap


def test_matrix_score_requires_reason():
    data = {
        "needSatisfaction": [
            {"competitor": "小米桌面风扇", "need": "静音", "score": 2, "reason": ["用户反馈噪音大"]},
            {"competitor": "小米桌面风扇", "need": "便携", "score": 4},  # 裸数字 → 丢弃
            {"competitor": "不存在品牌", "need": "静音", "score": 3, "reason": ["x"]},  # 竞品命中不了 → 丢弃
            {"competitor": "小米桌面风扇", "need": "静音", "score": 9, "reason": ["超限钳制"]},  # 9 → 钳到 5
        ],
        "opportunityGaps": [],
    }
    matrix, _ = _build_matrix_and_gaps(
        data,
        product_names=["小米桌面风扇"],
        need_dims=["静音", "便携"],
        pool_ids=["opp-1"],
    )
    assert len(matrix) == 2
    assert matrix[0]["score"] == 2 and matrix[0]["reason"]
    assert matrix[1]["score"] == 5  # 9 钳制到 5


def test_gap_requires_pool_id():
    data = {
        "needSatisfaction": [],
        "opportunityGaps": [
            {"userNeed": "通勤降温", "competitorGap": "竞品不便携", "opportunity": "户外便携风扇",
             "supportsOpportunityIds": ["opp-1"], "why": ["通勤痛点"]},
            {"userNeed": "x", "competitorGap": "y", "opportunity": "新机会",  # 无合法 id → 丢弃
             "supportsOpportunityIds": ["not-exist"], "why": []},
        ],
    }
    _, gaps = _build_matrix_and_gaps(data, ["小米"], ["静音"], ["opp-1"])
    assert len(gaps) == 1
    assert gaps[0]["supportsOpportunityIds"] == ["opp-1"]


def test_need_score_schema():
    s = CompetitorNeedScore(competitor="小米", need="静音", score=3, reason=["用户反馈"])
    assert s.score == 3 and s.reason == ["用户反馈"]


def test_opportunity_gap_schema():
    g = OpportunityGap(
        user_need="通勤降温", competitor_gap="竞品不便携", opportunity="户外便携风扇",
        supports_opportunity_ids=["opp-1"], why=["通勤痛点"],
    )
    assert g.supports_opportunity_ids == ["opp-1"]
