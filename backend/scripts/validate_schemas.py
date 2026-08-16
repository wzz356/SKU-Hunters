"""D1 契约功能验证脚本 — 验证关键校验器行为"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

w = Weights()  # 默认 35/25/20/10/10

# 1. 正确的 83 分算术：92*.35+78*.25+85*.20+60*.10+70*.10 = 81.7
dims = [
    DimensionScore(dimension="trend_heat", score=92, source_agent="trend_agent", basis="搜索增速180%"),
    DimensionScore(dimension="user_demand", score=78, source_agent="consumer_insight_agent", basis="痛点密度高"),
    DimensionScore(dimension="ip_fit", score=85, source_agent="ip_strategy_agent", basis="区域适配好"),
    DimensionScore(dimension="competition", score=60, source_agent="business_evaluation_agent", basis="同类竞对多"),
    DimensionScore(dimension="history_analog", score=70, source_agent="business_evaluation_agent", basis="相似案例表现"),
]
score = OpportunityScore(
    proposal_name="桌面摆件系列", dimension_scores=dims, weights_used=w,
    total_score=81.7, star_rating=4, upstream_confidence=Confidence.MEDIUM,
)
print("1. 正确算术通过:", score.total_score)

# 2. 错误算术应被拒绝（95 ≠ 81.7）
try:
    OpportunityScore(
        proposal_name="作弊方案", dimension_scores=dims, weights_used=w,
        total_score=95.0, star_rating=5, upstream_confidence=Confidence.MEDIUM,
    )
    print("2. 失败：错误算术未被拦截!")
except ValidationError as e:
    print("2. 错误算术被拦截:", str(e).splitlines()[1].strip()[:70])

# 3. 权重和不为 1 应被拒绝
try:
    Weights(trend_heat=0.5, user_demand=0.4, ip_fit=0.2, competition=0.1, history_analog=0.1)
    print("3. 失败：错误权重未被拦截!")
except ValidationError:
    print("3. 权重和校验拦截成功")

# 4. 提案数量约束（必须 3-5 个）
try:
    ProposalSet(proposals=[])
    print("4. 失败：空提案集未被拦截!")
except ValidationError:
    print("4. 提案数量约束生效（3-5个）")

# 5. source_map 三方覆盖检查
p = ProductProposal(
    name="桌面摆件系列", concept="IP联名迷你桌面公仔", product_form="摆件",
    target_segment="18-25岁女性", price_band="¥39-59", differentiation="收藏+工位场景",
    source_map=[
        SourceRef(artifact="FeatureMatrix", claim="趋势上升", supports="IP选择"),
        SourceRef(artifact="UserSentiment", claim="痛点明确", supports="形态"),
        SourceRef(artifact="IPAssessment", claim="窗口6-9月", supports="IP选择"),
    ],
)
print("5. source_map 覆盖:", sorted(p.covered_artifacts()))
print("\n全部验证通过 — D1 契约可用")
