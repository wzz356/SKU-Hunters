"""Asset Fit Agent / 商品决策卡补全 — 回归测试

覆盖：
1. AssetFit schema：ip/ipReason/opportunityId 契约，ip 引用真实名创资产。
2. _cross_ref：按机会池 id 交叉引用 痛点/竞品空白/资产适配，保持 id 贯穿。
"""

from __future__ import annotations

from app.planning.opportunity_engine import _cross_ref
from app.schemas.planning import AssetFit


def test_cross_ref_links_pool_id():
    bundle = {
        "consumerVoice": {"painPointChains": [
            {"painPoint": "风感", "supportsOpportunityIds": ["opp-1"]},
        ]},
        "competitiveMap": {"opportunityGaps": [
            {"competitorGap": "竞品偏重", "supportsOpportunityIds": ["opp-1"]},
        ]},
        "assetFit": [
            {"opportunityId": "opp-1", "ip": "库洛米", "ipReason": "人群重叠"},
        ],
    }
    pain, gap, fit = _cross_ref(bundle, "opp-1")
    assert pain == "风感"
    assert gap == "竞品偏重"
    assert fit["ip"] == "库洛米" and fit["ipReason"] == "人群重叠"


def test_cross_ref_missing_is_empty_not_fake():
    bundle = {
        "consumerVoice": {"painPointChains": []},
        "competitiveMap": {"opportunityGaps": []},
        "assetFit": [],
    }
    pain, gap, fit = _cross_ref(bundle, "opp-999")
    assert pain == "" and gap == "" and fit is None


def test_asset_fit_schema_ip_reason_bound():
    a = AssetFit(opportunity_id="opp-1", ip="库洛米", ip_reason="人群重叠",
                 color="紫", material="ABS", packaging="盲盒")
    assert a.ip == "库洛米" and a.ip_reason == "人群重叠"
    assert a.opportunity_id == "opp-1"
