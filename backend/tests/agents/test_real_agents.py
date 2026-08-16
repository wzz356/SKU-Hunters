"""真 LLM 委员 Agent 测试 — user/ip/business/gtm（mock 连接器 + mock LLM，不触网）

锁定四件事：
  1. Registry 切换：默认 Mock / =real 真类 /  bogus 回退 / 总开关兜底与覆盖
  2. 契约锁定：真 Agent 输出过各自 schema 强校验（与 Mock 输出同构）
  3. 降级纪律：LLM 失败/脏 JSON → 回退 Mock；user/ip 数据全故障 → Mock；
     gtm 数据故障 → 仍真输出（confidence=low）；零命中 → unknown 合法输出
  4. 铁律：EvidenceRef.url 全部来自连接器 payload（LLM 无法伪造）；
     business 总分 = 代码加权算术（LLM 返回的 total 无效）
"""

import asyncio
import json

import pytest

from app.agents import real_common
from app.agents.business_agent import BusinessAgent, get_business_agent_class
from app.agents.gtm_agent import GTMAgent, get_gtm_agent_class
from app.agents.ip_agent import IPAgent, get_ip_agent_class
from app.agents.mock_agents import (
    MockBusinessAgent,
    MockGTMAgent,
    MockIPAgent,
    MockUserAgent,
)
from app.agents.user_agent import UserAgent, get_user_agent_class
from app.data.errors import ConnectorFetchError
from app.schemas import GTMPlan, IPAssessment, OpportunityScore, UserSentiment

BRIEF = {
    "category": "小风扇", "market": "CN", "budget_range": "mid",
    "candidate_pool": ["库洛米", "Loopy"],
}

SUGGESTIONS = [
    {"query": "小风扇静音学生", "heat": 88},
    {"query": "小风扇续航", "heat": 66},
    {"query": "小风扇桌面", "heat": 44},
]

HOT_BOARD = [
    {"word": "小风扇爆火", "heat": 123456, "rank": 5, "url": "https://hot.example/1"},
]

BILI_RESULT = {
    "keyword": "库洛米", "scanned_videos": 100, "total_results": 3,
    "total_views": 250000, "avg_views": 83333.0,
    "top_videos": [
        {"title": "库洛米开箱", "bvid": "BV1xx", "view": 120000, "like": 1,
         "danmaku": 1, "tname": "生活",
         "url": "https://www.bilibili.com/video/BV1xx"},
    ],
    "scanned_partitions": ["生活"], "failed_partitions": [],
}


# ── Fake 连接器（依赖注入，照 test_trend_migration 模式）─────────


class FakeTaobao:
    def __init__(self, suggestions=None, fail=False):
        self._suggestions = suggestions if suggestions is not None else SUGGESTIONS
        self._fail = fail

    def get_suggestions(self, keyword):
        if self._fail:
            raise ConnectorFetchError("taobao", "HTTP 500")
        return self._suggestions

    def analyze_demand(self, keyword):
        return {"keyword": keyword, "demand_breadth": len(self._suggestions),
                "avg_heat": 66.0, "top_demands": self._suggestions[:5],
                "product_signals": []}


class FakeHot:
    def __init__(self, board=None, fail=False):
        self._board = HOT_BOARD if board is None else board
        self._fail = fail

    def get_hot_search(self, limit=50):
        if self._fail:
            raise ConnectorFetchError("fake", "HTTP 502")
        return self._board


class FakeBili:
    def __init__(self, result=None, fail=False):
        self._result = BILI_RESULT if result is None else result
        self._fail = fail

    def search_keyword(self, keyword):
        if self._fail:
            raise ConnectorFetchError("bilibili", "全部分区失败")
        return self._result


class FakeTiktok:
    def __init__(self, board=None, fail=False):
        self._board = board if board is not None else [
            {"word": "minifan", "heat": 999, "rank": 1,
             "url": "https://tiktok.example/minifan", "country": "US"},
        ]
        self._fail = fail

    def get_trending_hashtags(self, country_code="US", period=7, limit=20):
        if self._fail:
            raise ConnectorFetchError("tiktok", "网络受限")
        return self._board


def _mock_llm(monkeypatch, payload):
    """patch 统一 LLM 入口（真 Agent 内为函数级延迟 import，patch 模块属性即生效）"""
    monkeypatch.setattr(
        "app.engine.llm.complete",
        lambda *a, **kw: (json.dumps(payload) if payload is not None else None),
    )


def _run(agent, context):
    return asyncio.run(agent.run(context))


# ── ① Registry 切换 ────────────────────────────────────────────


class TestRegistrySwitch:
    @pytest.mark.parametrize("env_name,factory,real_cls,mock_cls", [
        ("USER_AGENT_PROVIDER", get_user_agent_class, UserAgent, MockUserAgent),
        ("IP_AGENT_PROVIDER", get_ip_agent_class, IPAgent, MockIPAgent),
        ("BUSINESS_AGENT_PROVIDER", get_business_agent_class,
         BusinessAgent, MockBusinessAgent),
        ("GTM_AGENT_PROVIDER", get_gtm_agent_class, GTMAgent, MockGTMAgent),
    ])
    def test_switch(self, monkeypatch, env_name, factory, real_cls, mock_cls):
        monkeypatch.delenv(env_name, raising=False)
        monkeypatch.delenv("AGENT_PROVIDER", raising=False)
        assert factory() is mock_cls

        monkeypatch.setenv(env_name, "real")
        assert factory() is real_cls

        monkeypatch.setenv(env_name, "bogus")
        assert factory() is mock_cls

    @pytest.mark.parametrize("env_name,factory,real_cls", [
        ("USER_AGENT_PROVIDER", get_user_agent_class, UserAgent),
        ("IP_AGENT_PROVIDER", get_ip_agent_class, IPAgent),
        ("BUSINESS_AGENT_PROVIDER", get_business_agent_class, BusinessAgent),
        ("GTM_AGENT_PROVIDER", get_gtm_agent_class, GTMAgent),
    ])
    def test_master_switch(self, monkeypatch, env_name, factory, real_cls):
        """总开关 AGENT_PROVIDER=real 兜底；分开关显式设置时覆盖总开关"""
        monkeypatch.delenv(env_name, raising=False)
        monkeypatch.setenv("AGENT_PROVIDER", "real")
        assert factory() is real_cls

        monkeypatch.setenv(env_name, "mock")  # 分开关覆盖总开关
        assert factory() is not real_cls


def test_provider_enabled_precedence(monkeypatch):
    monkeypatch.delenv("USER_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    assert real_common.provider_enabled("USER_AGENT_PROVIDER") is False
    monkeypatch.setenv("AGENT_PROVIDER", "real")
    assert real_common.provider_enabled("USER_AGENT_PROVIDER") is True
    monkeypatch.setenv("USER_AGENT_PROVIDER", "mock")
    assert real_common.provider_enabled("USER_AGENT_PROVIDER") is False


# ── ② UserAgent ────────────────────────────────────────────────

USER_LLM = {
    "sentiment": {"positive": 0.6, "neutral": 0.3, "negative": 0.1},
    "pain_points": [
        {"description": "学生党要静音", "severity": "high",
         "source_queries": ["小风扇静音学生"]},
        {"description": "材料里编不出来的痛点", "severity": "low",
         "source_queries": ["不存在的词"]},
    ],
    "motivation_tags": ["降温", "桌面美学"],
    "persona": "18-25 岁学生/初入职场，宿舍与工位场景",
    "price_sensitivity": "¥39-79 敏感度最低",
    "summary": "静音与续航是前两大痛点。",
    "caveats": ["样本偏差"],
}


class TestUserAgent:
    def test_contract_and_frequency(self, monkeypatch):
        """契约锁定 + frequency 代码算（88/88=1.0）+ 无依据痛点被丢弃"""
        _mock_llm(monkeypatch, USER_LLM)
        agent = UserAgent(taobao=FakeTaobao(), weibo=FakeHot(), baidu=FakeHot())
        result = _run(agent, {"brief": BRIEF})
        validated = UserSentiment.model_validate(result)

        assert validated.product_category == "小风扇"
        assert len(validated.pain_points) == 1  # 编不出依据的痛点被丢
        assert validated.pain_points[0].frequency == 1.0
        assert "学生" in validated.summary  # persona 合并进摘要
        assert any("语义保守估计" in c for c in validated.caveats)

    def test_evidence_urls_from_connector(self, monkeypatch):
        """证据铁律：每条 EvidenceRef.url 来自连接器 payload，LLM 无法伪造"""
        _mock_llm(monkeypatch, USER_LLM)
        agent = UserAgent(taobao=FakeTaobao(), weibo=FakeHot(), baidu=FakeHot())
        result = _run(agent, {"brief": BRIEF})
        urls = [r["url"] for r in result["evidence_refs"]]
        assert urls, "有数据时必须有证据"
        for u in urls:
            assert u == "https://hot.example/1" or u.startswith(
                "https://s.taobao.com/search?q=")

    def test_llm_failure_falls_back_to_mock(self, monkeypatch):
        _mock_llm(monkeypatch, None)
        agent = UserAgent(taobao=FakeTaobao(), weibo=FakeHot(), baidu=FakeHot())
        result = _run(agent, {"brief": BRIEF})
        expected = _run(MockUserAgent(), {"brief": BRIEF})
        assert result == expected

    def test_dirty_json_falls_back_to_mock(self, monkeypatch):
        monkeypatch.setattr("app.engine.llm.complete", lambda *a, **kw: "不是JSON")
        agent = UserAgent(taobao=FakeTaobao(), weibo=FakeHot(), baidu=FakeHot())
        result = _run(agent, {"brief": BRIEF})
        assert result == _run(MockUserAgent(), {"brief": BRIEF})

    def test_all_sources_failed_falls_back(self, monkeypatch):
        """数据全故障 → Mock（故障 ≠ 零命中）；LLM 不应被调用"""
        _mock_llm(monkeypatch, USER_LLM)
        agent = UserAgent(taobao=FakeTaobao(fail=True),
                          weibo=FakeHot(fail=True), baidu=FakeHot(fail=True))
        result = _run(agent, {"brief": BRIEF})
        assert result == _run(MockUserAgent(), {"brief": BRIEF})

    def test_zero_hit_is_legal_unknown(self, monkeypatch):
        """零命中 → confidence=unknown + 空证据，过 _check_evidence 记 C5 不 raise"""
        _mock_llm(monkeypatch, USER_LLM)
        agent = UserAgent(taobao=FakeTaobao(suggestions=[]),
                          weibo=FakeHot(board=[]), baidu=FakeHot(board=[]))
        result = _run(agent, {"brief": BRIEF})
        assert result["confidence"] == "unknown"
        assert result["evidence_refs"] == []

        from app.engine.graph import _check_evidence
        conflicts = _check_evidence(result, "user_sentiment", "act1")
        assert len(conflicts) == 1
        assert conflicts[0]["conflict_type"].value == "c5_insufficient"


# ── ③ IPAgent ──────────────────────────────────────────────────

IP_LLM = {
    "candidates": [
        {"ip_name": "库洛米", "lifecycle_stage": "peak", "window_estimate": "6-9个月",
         "regional_fit": 88, "rejected": False, "reject_reason": None},
        {"ip_name": "Loopy", "lifecycle_stage": "rising", "window_estimate": "9-12个月",
         "regional_fit": 80, "rejected": False, "reject_reason": None},
    ],
    "licensing_risk": "无已知风险（未接入授权信息库）",
    "strategy_note": "成熟形态快反。",
    "caveats": [],
}


class TestIPAgent:
    def test_contract_and_code_heat(self, monkeypatch):
        """契约锁定 + heat_score 代码算（覆盖 LLM 值）+ 按热度降序"""
        payload = json.loads(json.dumps(IP_LLM))
        payload["candidates"][0]["heat_score"] = 1  # LLM 试图写热度 → 应被覆盖
        _mock_llm(monkeypatch, payload)
        agent = IPAgent(taobao=FakeTaobao(), bilibili=FakeBili())
        result = _run(agent, {"brief": BRIEF})
        validated = IPAssessment.model_validate(result)

        assert [c.ip_name for c in validated.ip_ranking] == ["库洛米", "Loopy"]
        top = validated.ip_ranking[0]
        assert top.heat_score != 1  # 代码值覆盖 LLM 值
        assert top.heat_score > 0
        assert top.lifecycle_stage == "peak"
        heats = [c.heat_score for c in validated.ip_ranking]
        assert heats == sorted(heats, reverse=True)

    def test_evidence_urls_from_connector(self, monkeypatch):
        _mock_llm(monkeypatch, IP_LLM)
        agent = IPAgent(taobao=FakeTaobao(), bilibili=FakeBili())
        result = _run(agent, {"brief": BRIEF})
        urls = [r["url"] for r in result["evidence_refs"]]
        assert urls
        for u in urls:
            assert u == "https://www.bilibili.com/video/BV1xx" or u.startswith(
                "https://s.taobao.com/search?q=")

    def test_empty_pool_falls_back(self, monkeypatch):
        """候选池为空 → Mock（不烧 LLM）"""
        _mock_llm(monkeypatch, IP_LLM)
        agent = IPAgent(taobao=FakeTaobao(), bilibili=FakeBili())
        brief = {**BRIEF, "candidate_pool": []}
        result = _run(agent, {"brief": brief})
        assert result == _run(MockIPAgent(), {"brief": brief})

    def test_all_sources_failed_falls_back(self, monkeypatch):
        _mock_llm(monkeypatch, IP_LLM)
        agent = IPAgent(taobao=FakeTaobao(fail=True), bilibili=FakeBili(fail=True))
        result = _run(agent, {"brief": BRIEF})
        assert result == _run(MockIPAgent(), {"brief": BRIEF})

    def test_zero_hit_is_legal_unknown(self, monkeypatch):
        zero_bili = {**BILI_RESULT, "total_results": 0, "total_views": 0,
                     "top_videos": []}
        _mock_llm(monkeypatch, IP_LLM)
        agent = IPAgent(taobao=FakeTaobao(suggestions=[]),
                        bilibili=FakeBili(result=zero_bili))
        result = _run(agent, {"brief": BRIEF})
        assert result["confidence"] == "unknown"
        assert result["evidence_refs"] == []
        assert all(c["heat_score"] == 0 for c in result["ip_ranking"])

        from app.engine.graph import _check_evidence
        conflicts = _check_evidence(result, "ip_assessment", "act1")
        assert len(conflicts) == 1
        assert conflicts[0]["conflict_type"].value == "c5_insufficient"

    def test_llm_failure_falls_back(self, monkeypatch):
        _mock_llm(monkeypatch, None)
        agent = IPAgent(taobao=FakeTaobao(), bilibili=FakeBili())
        result = _run(agent, {"brief": BRIEF})
        assert result == _run(MockIPAgent(), {"brief": BRIEF})


# ── ④ BusinessAgent ────────────────────────────────────────────

PROPOSAL_SET = {
    "proposals": [
        {"name": "库洛米磁吸小风扇", "concept": "IP+磁吸+桌面", "product_form": "风扇",
         "target_segment": "学生", "price_band": "¥39-59", "differentiation": "磁吸"},
        {"name": "透明渐变手持扇", "concept": "渐变外观", "product_form": "风扇",
         "target_segment": "通勤族", "price_band": "¥29-49", "differentiation": "外观"},
    ],
    "ideation_note": "",
}

WEIGHTS = {"trend_heat": 0.3, "user_demand": 0.25, "ip_fit": 0.2,
           "competition": 0.1, "history_analog": 0.15}

BUSINESS_LLM = {
    "scores": [
        {
            "proposal_name": "库洛米磁吸小风扇",
            "dimensions": {
                "trend_heat": {"score": 90, "basis": "搜索增速"},
                "user_demand": {"score": 80, "basis": "痛点密度"},
                "ip_fit": {"score": 85, "basis": "窗口期"},
                "competition": {"score": 60, "basis": "竞品"},
                "history_analog": {"score": 70, "basis": "类比"},
            },
            "risk_warnings": [
                {"risk": "价格战", "source_dimension": "competition",
                 "severity": "bogus"},  # 非法 severity → 钳到 medium
            ],
        },
        {
            "proposal_name": "透明渐变手持扇",
            "dimensions": {
                "trend_heat": {"score": 70, "basis": "增速"},
                "user_demand": {"score": 75, "basis": "痛点"},
                "ip_fit": {"score": 50, "basis": "无IP"},
                "competition": {"score": 65, "basis": "竞品"},
                "history_analog": {"score": 60, "basis": "类比"},
            },
            "risk_warnings": [],
        },
    ],
}

BUSINESS_CTX = {
    "brief": BRIEF,
    "weights": WEIGHTS,
    "proposal_set": PROPOSAL_SET,
    "challenges": [],
    "upstream_confidences": ["high", "medium", "low"],
    "feature_matrix": {"summary": "趋势摘要",
                       "evidence_refs": [{"url": "https://fm.example/1",
                                          "title": "趋势证据", "snippet": "s"}]},
    "user_sentiment": {"summary": "用户摘要", "evidence_refs": []},
    "ip_assessment": {"summary": "IP摘要", "evidence_refs": []},
}


class TestBusinessAgent:
    def test_contract_and_code_total(self, monkeypatch):
        """总分 = 代码加权算术（LLM 返回错乱 total 无效）；置信度取上游最低"""
        payload = json.loads(json.dumps(BUSINESS_LLM))
        payload["scores"][0]["total_score"] = 9999  # LLM 试图写总分 → 应被忽略
        _mock_llm(monkeypatch, payload)
        result = _run(BusinessAgent(), BUSINESS_CTX)

        scores = [OpportunityScore.model_validate(s)
                  for s in result["opportunity_scores"]]
        assert len(scores) == 2
        top = scores[0]
        # 手算：90*.3 + 80*.25 + 85*.2 + 60*.1 + 70*.15 = 27+20+17+6+10.5 = 80.5
        assert top.total_score == 80.5
        assert top.star_rating == 4
        assert top.upstream_confidence == "low"  # 衰减到上游最低
        assert top.risk_warnings[0].severity == "medium"  # 非法值被钳
        # 证据来自上游 artifact 抽样
        assert top.evidence_refs[0].url == "https://fm.example/1"

    def test_missing_dimension_falls_back(self, monkeypatch):
        """缺维度 → 整体回退 Mock（不部分输出）"""
        payload = json.loads(json.dumps(BUSINESS_LLM))
        del payload["scores"][0]["dimensions"]["ip_fit"]
        _mock_llm(monkeypatch, payload)
        result = _run(BusinessAgent(), BUSINESS_CTX)
        assert result == _run(MockBusinessAgent(), BUSINESS_CTX)

    def test_out_of_range_score_falls_back(self, monkeypatch):
        payload = json.loads(json.dumps(BUSINESS_LLM))
        payload["scores"][1]["dimensions"]["trend_heat"]["score"] = 150
        _mock_llm(monkeypatch, payload)
        result = _run(BusinessAgent(), BUSINESS_CTX)
        assert result == _run(MockBusinessAgent(), BUSINESS_CTX)

    def test_llm_failure_falls_back(self, monkeypatch):
        _mock_llm(monkeypatch, None)
        result = _run(BusinessAgent(), BUSINESS_CTX)
        assert result == _run(MockBusinessAgent(), BUSINESS_CTX)


# ── ⑤ GTMAgent ─────────────────────────────────────────────────

GTM_LLM = {
    "plans": [
        {
            "proposal_name": "库洛米磁吸小风扇",
            "country_plans": [
                {"country": "CN", "batch": 1, "price_band": "¥39-59",
                 "timing": "首批2周内", "rationale": "热搜命中"},
            ],
            "localization_notes": ["贴中文包装"],
            "deferred_markets": [],
            "dependencies": "",
        },
        {
            "proposal_name": "透明渐变手持扇",
            "country_plans": [
                {"country": "CN", "batch": 1, "price_band": "¥29-49",
                 "timing": "首批2周内", "rationale": "经验判断"},
            ],
            "localization_notes": [],
            "deferred_markets": [],
            "dependencies": "",
        },
    ],
}

GTM_CTX = {"brief": BRIEF, "proposal_set": PROPOSAL_SET, "challenges": []}


class TestGTMAgent:
    def test_contract_cn_market(self, monkeypatch):
        _mock_llm(monkeypatch, GTM_LLM)
        agent = GTMAgent(weibo=FakeHot(), baidu=FakeHot())
        result = _run(agent, GTM_CTX)
        plans = [GTMPlan.model_validate(p) for p in result["gtm_plans"]]
        assert len(plans) == 2
        assert plans[0].country_plans[0].batch == 1
        assert plans[0].confidence == "medium"  # 热搜有命中
        assert plans[0].evidence_refs[0].url == "https://hot.example/1"

    def test_data_failure_still_real_output_low_confidence(self, monkeypatch):
        """数据故障不回退 Mock——仍真输出且 confidence=low（与 Mock 不同构）"""
        _mock_llm(monkeypatch, GTM_LLM)
        agent = GTMAgent(weibo=FakeHot(fail=True), baidu=FakeHot(fail=True))
        result = _run(agent, GTM_CTX)
        mock_result = _run(MockGTMAgent(), GTM_CTX)
        assert result != mock_result
        assert all(p["confidence"] == "low" for p in result["gtm_plans"])
        assert all(p["caveats"] for p in result["gtm_plans"])
        GTMPlan.model_validate(result["gtm_plans"][0])

    def test_overseas_market_uses_tiktok(self, monkeypatch):
        """海外市场走 TikTok 话题榜（112 国口径），证据来自其 payload"""
        _mock_llm(monkeypatch, GTM_LLM)
        agent = GTMAgent(tiktok=FakeTiktok())
        ctx = {"brief": {**BRIEF, "market": "US", "category": "minifan"},
               "proposal_set": PROPOSAL_SET, "challenges": []}
        result = _run(agent, ctx)
        urls = [r["url"] for p in result["gtm_plans"] for r in p["evidence_refs"]]
        assert urls and all(u == "https://tiktok.example/minifan" for u in urls)

    def test_llm_failure_falls_back(self, monkeypatch):
        _mock_llm(monkeypatch, None)
        agent = GTMAgent(weibo=FakeHot(), baidu=FakeHot())
        result = _run(agent, GTM_CTX)
        assert result == _run(MockGTMAgent(), GTM_CTX)


class TestFuzzyGet:
    """方案名模糊匹配：LLM 抄名时丢/改标点（真机冒烟发现的回退原因）"""

    def test_exact_match(self):
        assert real_common.fuzzy_get({"方案A": 1}, "方案A") == 1

    def test_punctuation_stripped(self):
        m = {"玉桂狗挂脖手持两用随身风扇": 2}
        assert real_common.fuzzy_get(m, "玉桂狗挂脖/手持两用随身风扇") == 2

    def test_brackets_and_spaces_stripped(self):
        m = {"方案「库洛米裙摆风扇」（手持）": 3}
        assert real_common.fuzzy_get(m, "库洛米裙摆风扇") == 3

    def test_no_match_returns_none(self):
        assert real_common.fuzzy_get({"方案A": 1}, "方案B") is None
        assert real_common.fuzzy_get({"方案A": 1}, "") is None


# ── ⑥ 学习官台账反哺（飞轮闭环）─────────────────────────────────

ANALOG = {
    "proposal": "库洛米旧款风扇", "category": "小风扇",
    "predicted_score": 45.0, "ai_decision": "reject",
    "human_action": "reject", "status": "rejected", "retro_turns": 2,
}


def _capture_llm(monkeypatch, payload):
    """patch complete 并捕获 user prompt（验证材料装配）"""
    captured = {}

    def _spy(system, user, **kw):
        captured["user"] = user
        return json.dumps(payload)

    monkeypatch.setattr("app.engine.llm.complete", _spy)
    return captured


# 创意官测试上下文：三官 Artifact 齐全（输出契约硬校验的前置），
# 用户官 summary 含全部 product_form 形态信号（契约 4：形态须有用户信号依据）
_CREATIVE_FM = {"summary": "小风扇趋势上行", "evidence_refs": []}
_CREATIVE_US = {
    "summary": "学生与通勤族偏好摆件、挂脖、桌面形态的小风扇",
    "pain_points": [{"description": "宿舍噪音大"}],
    "motivation_tags": ["静音"],
}
_CREATIVE_IP = {
    "summary": "库洛米热度高",
    "ip_ranking": [{"ip_name": "库洛米", "heat_score": 88, "window_estimate": "6-9个月"}],
}
_CREATIVE_CTX = {
    "brief": BRIEF,
    "feature_matrix": _CREATIVE_FM,
    "user_sentiment": _CREATIVE_US,
    "ip_assessment": _CREATIVE_IP,
}

# 三方案两两至少两维不同（契约 2：形态/场景/价位），价格带均在 mid 预算内
_CREATIVE_PAYLOAD = {"proposals": [
    {"name": "方案A", "concept": "宿舍静音摆件", "product_form": "摆件",
     "target_segment": "学生", "price_band": "¥39-59",
     "differentiation": "静音"},
    {"name": "方案B", "concept": "通勤挂脖", "product_form": "挂脖",
     "target_segment": "通勤族", "price_band": "¥39-59",
     "differentiation": "便携"},
    {"name": "方案C", "concept": "桌面大风力", "product_form": "桌面",
     "target_segment": "学生", "price_band": "¥49-69",
     "differentiation": "风力"},
], "ideation_note": "note"}


class TestHistoryFeedback:
    def test_business_material_has_analogs(self, monkeypatch):
        captured = _capture_llm(monkeypatch, BUSINESS_LLM)
        ctx = {**BUSINESS_CTX, "history_analogs": [ANALOG]}
        _run(BusinessAgent(), ctx)
        assert "历史相似案例" in captured["user"]
        assert "库洛米旧款风扇" in captured["user"]
        assert "reject" in captured["user"]

    def test_business_material_empty_analogs_honest(self, monkeypatch):
        captured = _capture_llm(monkeypatch, BUSINESS_LLM)
        _run(BusinessAgent(), {**BUSINESS_CTX, "history_analogs": []})
        assert "无历史档案" in captured["user"]

    def test_creative_negative_examples(self, monkeypatch):
        from app.agents.creative_agent import CreativeAgent

        captured = _capture_llm(monkeypatch, _CREATIVE_PAYLOAD)
        ctx = {**_CREATIVE_CTX, "history_analogs": [ANALOG]}
        result = _run(CreativeAgent(), ctx)
        assert "历史教训" in captured["user"]
        assert "库洛米旧款风扇" in captured["user"]
        assert len(result["proposals"]) == 3  # 契约不受影响

    def test_creative_no_analogs_no_section(self, monkeypatch):
        from app.agents.creative_agent import CreativeAgent

        captured = _capture_llm(monkeypatch, _CREATIVE_PAYLOAD)
        _run(CreativeAgent(), dict(_CREATIVE_CTX))  # 无 history_analogs 键
        assert "历史教训" not in captured["user"]
