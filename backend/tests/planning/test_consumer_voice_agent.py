"""Consumer Voice Agent — 回归测试

覆盖：
1. 引用校验（_fuzzy_index）：painPoint/consumerVoice/supportsOpportunityIds 必须命中真实数据，
   归一化模糊匹配，不靠字符串全等。
2. 证据构建（_build_evidence/_extract_platform）：平台/关键词/数量代码从采集数据提取，不编造。
3. 决策画像/归因链 schema 契约（不产假数据）。
"""

from __future__ import annotations

from app.planning.consumer_voice_agent import (
    _build_evidence,
    _clean_pain,
    _extract_platform,
    _fuzzy_index,
    _fuzzy_quote_index,
    _pain_voice,
)
from app.schemas.planning import DecisionUserProfile, PainPointChain


def test_fuzzy_index_matches_paraphrase():
    candidates = ["防晒伞每天背着太重了", "蕉下伞骨软不抗风"]
    assert _fuzzy_index(candidates, "防晒伞太重") == 0
    assert _fuzzy_index(candidates, "伞骨软") == 1
    assert _fuzzy_index(candidates, "不存在") == -1
    assert _fuzzy_index(candidates, "") == -1


def test_fuzzy_quote_index_matches_truncation():
    quotes = ["她最怕那种把小风扇的风力吹成台风级别的，感觉贴脸一吹明天头疼", "噪音小到室友听不见"]
    assert _fuzzy_quote_index(quotes, "她最怕那种把小风扇的风力吹成台风级别") == 0  # 截断命中
    assert _fuzzy_quote_index(quotes, "噪音小到室友听不见") == 1
    assert _fuzzy_quote_index(quotes, "自造的原声") == -1


def test_extract_platform():
    assert _extract_platform("小红书 + Instagram「高颜值雨伞」") == "小红书"
    assert _extract_platform("什么值得买 2026-05") == "什么值得买"
    assert _extract_platform("抖音 + 巨量算数") == "抖音"


def test_clean_pain():
    assert _clean_pain("用户痛点-风感") == "风感"
    assert _clean_pain("漏水/密封性差,放包里湿文件") == "漏水"


def test_pain_voice_extracts_embedded_voice():
    full = "雨伞不结实 一次性伞 吐槽合集：小红书+微博大量吐槽'现在的雨伞越来越不结实'"
    assert _pain_voice(full).startswith("小红书+微博大量吐槽")
    assert _pain_voice("用户痛点-风感") == "用户痛点-风感"  # 无冒号则原样返回


def test_build_evidence_count_is_real_voice_count():
    ev = _build_evidence("太重/不便携", ["原声1", "原声2"], ["小红书 + 采集源"])
    assert ev["count"] == 2
    assert ev["platform"] == "小红书"
    assert "太重" in ev["keywords"]


def test_decision_profile_no_demographics():
    p = DecisionUserProfile(
        user_segment="城市通勤人群",
        usage_scenario=["地铁", "办公室"],
        user_task=["随身降温"],
        purchase_motivation=["颜值", "便携"],
        decision_factors=["重量", "IP", "续航"],
    )
    # 无 age/gender/occupation 字段 —— 决策画像不做人口属性
    assert "age" not in DecisionUserProfile.model_fields and "gender" not in DecisionUserProfile.model_fields


def test_chain_schema_references_pool_by_id():
    chain = PainPointChain(
        priority=5,
        pain_point="防晒伞每天背着太重",
        consumer_voice=["防晒伞每天背着太重了"],
        demand_interpretation="用户希望一把伞同时满足遮阳+携带",
        supports_opportunity_ids=["opp-1"],
        evidence_source={"platform": "小红书", "keywords": ["太重"], "count": 1},
    )
    assert chain.supports_opportunity_ids == ["opp-1"]  # 引用 id，非文本
