"""第四阶段：旧本地趋势官能力迁移验收测试

覆盖迁移后的 7 项能力：
  1. 确定性指标计算（TrendMetrics 业务规则，全 Python 计算）
  2. 跨源冲突检测（TrendConflictDetector）
  3. Google/B站连接器异常传播（ConnectorFetchError，故障 ≠ 零命中）
  4. data_gaps / caveats 显式记录
  5. unknown 不伪装成确定结论
  6. EvidenceRef 闭环
  7. Google/B站空数据与失败状态区分
"""

import pytest
from app.agents.trend_agent import TrendAgent, get_trend_agent_class
from app.agents.trend_conflict_detector import TrendConflictDetector
from app.agents.trend_metrics import (
    FORMULA_VERSION,
    SourceScore,
    SourceSignal,
    TrendMetrics,
)
from app.data.bilibili_hot import BilibiliConnector
from app.data.errors import ConnectorFetchError
from app.data.google_trends import GoogleTrendsConnector
from app.schemas.evidence import Confidence
from app.schemas.feature import FeatureMatrix

# ══════════════ 1. 确定性指标计算 ══════════════

class TestFormulaVersion:
    def test_formula_version(self):
        assert FORMULA_VERSION == "0.2.0"


class TestComputeEngagementRate:
    def test_normal_case(self):
        assert TrendMetrics.compute_engagement_rate(100000, 5000, 1000) == 0.06

    def test_zero_play(self):
        assert TrendMetrics.compute_engagement_rate(0, 100, 50) == 0.0


class TestComputeHeatIndex:
    def test_excludes_taobao(self):
        scores = [
            SourceScore(source="google_trends", heat_score=60.0, data_quality="high"),
            SourceScore(source="bilibili_ranking", heat_score=40.0, data_quality="high"),
            SourceScore(source="taobao_suggest", heat_score=90.0, data_quality="high"),
        ]
        assert TrendMetrics.compute_heat_index(scores) == 50.0

    def test_no_valid_sources(self):
        scores = [SourceScore(source="google_trends", heat_score=None, data_quality="unknown")]
        assert TrendMetrics.compute_heat_index(scores) is None


class TestJudgeLifecycle:
    def test_unknown_when_no_valid_sources(self):
        scores = [SourceScore(source="google_trends", data_quality="unknown")]
        assert TrendMetrics.judge_lifecycle(scores) == "unknown"

    def test_unknown_when_no_google(self):
        """没有 Google Trends 时不得判断趋势方向"""
        scores = [SourceScore(source="bilibili_ranking", heat_score=80.0, data_quality="high")]
        assert TrendMetrics.judge_lifecycle(scores) == "unknown"

    def test_rising_with_google_and_bilibili(self):
        scores = [
            SourceScore(source="google_trends", heat_score=60.0, direction="rising", data_quality="high"),
            SourceScore(source="bilibili_ranking", heat_score=50.0, data_quality="high"),
        ]
        assert TrendMetrics.judge_lifecycle(scores) == "rising"

    def test_emerging_with_only_google_rising(self):
        """只有 Google 上升且无其他平台支持 → 萌芽期，不直接判 rising"""
        scores = [SourceScore(source="google_trends", heat_score=60.0, direction="rising", data_quality="high")]
        assert TrendMetrics.judge_lifecycle(scores) == "emerging"

    def test_unknown_when_google_direction_unknown(self):
        scores = [SourceScore(source="google_trends", direction="unknown", data_quality="high")]
        assert TrendMetrics.judge_lifecycle(scores) == "unknown"


class TestAssessConfidence:
    def test_high_confidence(self):
        scores = [
            SourceScore(source="google_trends", heat_score=60.0, data_quality="high"),
            SourceScore(source="bilibili_ranking", heat_score=50.0, data_quality="high"),
        ]
        assert TrendMetrics.assess_confidence(scores, 55.0, "rising") == "high"

    def test_unknown_when_no_valid(self):
        scores = [SourceScore(source="google_trends", data_quality="unknown")]
        assert TrendMetrics.assess_confidence(scores, None, "unknown") == "unknown"


class TestScoreGoogleTrends:
    def test_low_base_quality(self):
        """低基数（level < 5）时数据质量降为 low"""
        signal = SourceSignal(
            source="google_trends", keyword="冷门词",
            raw_metrics={"level": 2.0, "growth": 500.0, "breadth": 1, "heat_index": 10.0, "lifecycle": "rising"},
            data_quality="high",
        )
        score = TrendMetrics.compute_source_score(signal)
        assert score.data_quality == "low"


class TestScoreBilibili:
    def test_direction_never_guessed(self):
        """B站截面数据不得猜测方向"""
        signal = SourceSignal(
            source="bilibili_ranking", keyword="史迪奇",
            raw_metrics={"total_views": 800000, "total_results": 3, "scanned_videos": 474},
            data_quality="high",
        )
        score = TrendMetrics.compute_source_score(signal)
        assert score.direction == "unknown"
        assert score.growth is None

    def test_empty_results_low_quality_no_heat(self):
        signal = SourceSignal(
            source="bilibili_ranking", keyword="冷门词",
            raw_metrics={"total_views": 0, "total_results": 0, "scanned_videos": 474},
            data_quality="high",
        )
        score = TrendMetrics.compute_source_score(signal)
        assert score.heat_score is None
        assert score.data_quality == "low"


# ══════════════ 2. 跨源冲突检测 ══════════════

class TestConflictDetector:
    def test_consistent_sources_no_conflict(self):
        scores = [
            SourceScore(source="google_trends", heat_score=70.0, data_quality="high"),
            SourceScore(source="bilibili_ranking", heat_score=65.0, data_quality="high"),
        ]
        assert len(TrendConflictDetector.detect(scores)) == 0

    def test_hot_vs_cold_detected(self):
        scores = [
            SourceScore(source="google_trends", heat_score=80.0, data_quality="high"),
            SourceScore(source="bilibili_ranking", heat_score=10.0, data_quality="high"),
        ]
        types = [c.conflict_type for c in TrendConflictDetector.detect(scores)]
        assert "hot_vs_cold" in types

    def test_domestic_vs_overseas(self):
        scores = [
            SourceScore(source="bilibili_ranking", heat_score=80.0, data_quality="high"),
            SourceScore(source="google_trends", heat_score=10.0, data_quality="high"),
        ]
        types = [c.conflict_type for c in TrendConflictDetector.detect(scores)]
        assert "domestic_vs_overseas" in types

    def test_conflicts_not_averaged(self):
        """冲突不得通过平均分隐藏"""
        scores = [
            SourceScore(source="google_trends", heat_score=90.0, data_quality="high"),
            SourceScore(source="bilibili_ranking", heat_score=5.0, data_quality="high"),
        ]
        assert len(TrendConflictDetector.detect(scores)) > 0

    def test_insufficient_sources(self):
        scores = [SourceScore(source="bilibili_ranking", heat_score=50.0, data_quality="high")]
        types = [c.conflict_type for c in TrendConflictDetector.detect(scores)]
        assert "insufficient_cross_validation" in types


# ══════════════ 3. 连接器异常传播 ══════════════

from unittest.mock import MagicMock, patch

import httpx


def _mock_response(json_data=None, status_code=200, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
    if status_code >= 400:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status_code}", request=MagicMock(), response=resp
            )
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _ranking_payload(titles):
    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "title": t, "bvid": f"BV{i:09d}",
                    "stat": {"view": 1000, "like": 10, "danmaku": 5},
                    "tname": "生活",
                }
                for i, t in enumerate(titles)
            ]
        },
    }


class TestBilibiliConnectorFailureSemantics:
    def test_http_error_raises_not_empty_list(self):
        connector = BilibiliConnector()
        with patch.object(httpx, "get", side_effect=httpx.ConnectError("连接被拒绝")), \
                pytest.raises(ConnectorFetchError) as exc_info:
            connector.get_ranking_videos(160)
        assert "bilibili" in str(exc_info.value)

    def test_business_error_raises(self):
        connector = BilibiliConnector()
        with patch.object(
            httpx, "get", return_value=_mock_response({"code": -352, "message": "风控校验失败"})
        ), pytest.raises(ConnectorFetchError) as exc_info:
            connector.get_ranking_videos(160)
        assert "-352" in str(exc_info.value)

    def test_all_partitions_failed_raises(self):
        connector = BilibiliConnector()
        with patch.object(httpx, "get", side_effect=httpx.ConnectError("网络不通")), \
                pytest.raises(ConnectorFetchError) as exc_info:
            connector.search_keyword("史迪奇")
        assert "全部" in str(exc_info.value)

    def test_partial_failure_degrades_with_status(self):
        connector = BilibiliConnector()
        call_count = {"n": 0}

        def fake_get(url, params=None, headers=None, timeout=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise httpx.ConnectError("分区请求失败")
            return _mock_response(_ranking_payload(["史迪奇开箱", "无关视频"]))

        with patch.object(httpx, "get", side_effect=fake_get):
            result = connector.search_keyword("史迪奇")
        assert len(result["failed_partitions"]) == 2
        assert len(result["scanned_partitions"]) == 3
        assert result["scanned_videos"] == 6

    def test_zero_hit_is_normal_result(self):
        connector = BilibiliConnector()
        with patch.object(
            httpx, "get", return_value=_mock_response(_ranking_payload(["完全无关的视频"]))
        ):
            result = connector.search_keyword("史迪奇")
        assert result["total_results"] == 0
        assert result["failed_partitions"] == []
        assert result["scanned_videos"] == 5


# ══════════════ 4-7. TrendAgent 集成（注入假连接器，全离线） ══════════════

class FakeGoogle:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def compute_heat_index(self, kw, geo=""):
        if self._error:
            raise self._error
        if self._result is not None:
            return dict(self._result)
        return {
            "keyword": kw, "level": 60.0, "growth": 15.0, "breadth": 8,
            "heat_index": 62.0, "lifecycle": "rising", "no_data": False,
        }


class FakeBilibili:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def search_keyword(self, kw):
        if self._error:
            raise self._error
        if self._result is not None:
            return dict(self._result)
        return {
            "keyword": kw, "scanned_videos": 474, "total_results": 3,
            "total_views": 800000, "avg_views": 266667,
            "top_videos": [{
                "title": "史迪奇开箱", "bvid": "BV1", "view": 100000,
                "like": 5000, "danmaku": 1000, "tname": "生活",
                "url": "https://www.bilibili.com/video/BV1",
            }],
            "scanned_partitions": ["生活", "时尚", "动画", "游戏", "鬼畜"],
            "failed_partitions": [],
        }


def _brief(category="解压玩具", market="CN"):
    return {"category": category, "market": market, "budget_range": "mid"}


def _run(agent, **kw):
    import asyncio
    return asyncio.run(agent.run({"brief": _brief(), **kw}))


def _parse(result: dict) -> FeatureMatrix:
    return FeatureMatrix.model_validate(result)


class TestTrendAgentOutputSchema:
    def test_returns_feature_matrix_schema(self):
        agent = TrendAgent(google_connector=FakeGoogle(), bilibili_connector=FakeBilibili())
        out = _run(agent)
        fm = _parse(out)  # 必须是合法 FeatureMatrix
        assert fm.category == "解压玩具"

    def test_normal_multisource(self):
        agent = TrendAgent(google_connector=FakeGoogle(), bilibili_connector=FakeBilibili())
        out = _run(agent)
        fm = _parse(out)
        assert len(fm.trends) == 1
        t = fm.trends[0]
        assert 0 <= t.heat_index <= 100
        # B站热度分低（<30），不支持跨平台上升 → 正确降级为萌芽期（业务规则）
        assert t.lifecycle == "emerging"
        assert "Google Trends" in t.platform and "B站" in t.platform
        assert len(fm.evidence_refs) > 0
        assert fm.confidence in (Confidence.HIGH, Confidence.MEDIUM)


class TestConnectorErrorPropagation:
    def test_google_error_goes_to_caveats_not_blocking(self):
        agent = TrendAgent(
            google_connector=FakeGoogle(error=ConnectorFetchError("google_trends", "网络错误")),
            bilibili_connector=FakeBilibili(),
        )
        out = _run(agent)
        fm = _parse(out)
        # B站数据仍产出结论
        assert len(fm.trends) >= 1
        # Google 故障写入 caveats（data_gaps 映射），带来源归属
        assert any("google_trends" in c and "采集失败" in c for c in fm.caveats)

    def test_all_sources_fail_unknown_confidence(self):
        agent = TrendAgent(
            google_connector=FakeGoogle(error=ConnectorFetchError("google_trends", "网络错误")),
            bilibili_connector=FakeBilibili(error=ConnectorFetchError("bilibili", "全部分区失败")),
        )
        out = _run(agent)
        fm = _parse(out)
        # 无结论：不伪造 TrendItem
        assert len(fm.trends) == 0
        assert fm.confidence == Confidence.UNKNOWN
        assert any("采集失败" in c for c in fm.caveats)


class TestEmptyDataNotFaked:
    def test_google_no_data_not_faked_as_zero(self):
        empty = {
            "keyword": "x", "level": None, "growth": None, "breadth": None,
            "heat_index": None, "lifecycle": "unknown", "no_data": True,
        }
        agent = TrendAgent(
            google_connector=FakeGoogle(result=empty),
            bilibili_connector=FakeBilibili(),  # 有 B站数据
        )
        out = _run(agent)
        fm = _parse(out)
        # B站仍出结论，但 caveats 必须记录 google 无数据
        assert len(fm.trends) >= 1
        assert any("google_trends" in c and "未查询到" in c for c in fm.caveats)

    def test_only_google_no_data_no_trend(self):
        empty = {
            "keyword": "x", "level": None, "growth": None, "breadth": None,
            "heat_index": None, "lifecycle": "unknown", "no_data": True,
        }
        agent = TrendAgent(
            google_connector=FakeGoogle(result=empty),
            bilibili_connector=None,  # 只有 google 且无数据
        )
        out = _run(agent)
        fm = _parse(out)
        assert len(fm.trends) == 0
        assert fm.confidence == Confidence.UNKNOWN


class TestUnknownPreserved:
    def test_lifecycle_unknown_when_only_bilibili(self):
        """只有 B站（无 Google）时 lifecycle 保持 unknown，不判 rising

        注意：不能传 google_connector=None——构造函数会把 None 解释为
        "创建默认真实连接器"，测试结果将取决于 Google 是否可达（网络抖动）。
        显式传故障连接器来模拟"无 Google"。
        """
        agent = TrendAgent(
            google_connector=FakeGoogle(error=ConnectorFetchError("google_trends", "网络错误")),
            bilibili_connector=FakeBilibili(),
        )
        out = _run(agent)
        fm = _parse(out)
        assert len(fm.trends) == 1
        assert fm.trends[0].lifecycle == "unknown"


class TestEvidenceClosedLoop:
    def test_evidence_refs_present_and_traceable(self):
        agent = TrendAgent(google_connector=FakeGoogle(), bilibili_connector=FakeBilibili())
        out = _run(agent)
        fm = _parse(out)
        assert len(fm.evidence_refs) >= 2
        for ev in fm.evidence_refs:
            assert ev.url and ev.title and ev.snippet
        # 有 B站视频级证据（BV 链接）
        assert any("bilibili.com/video/" in ev.url for ev in fm.evidence_refs)


class TestPartialPartitionCaveat:
    def test_bilibili_partial_failure_caveat(self):
        result = FakeBilibili().search_keyword("x")
        result["failed_partitions"] = ["游戏", "鬼畜"]
        agent = TrendAgent(
            google_connector=FakeGoogle(),
            bilibili_connector=FakeBilibili(result=result),
        )
        out = _run(agent)
        fm = _parse(out)
        assert any("游戏" in c and "鬼畜" in c for c in fm.caveats)


class TestGoogleConnectorEmptyData:
    """P1-1：Google 空 DataFrame 必须返回 no_data + None，不得伪装成 0 值"""

    def test_empty_df_returns_no_data_not_zero(self):
        import pandas as pd

        c = GoogleTrendsConnector()
        with patch.object(
            GoogleTrendsConnector, "get_interest_over_time", return_value=pd.DataFrame()
        ):
            result = c.compute_heat_index("冷门到不存在的词")
        assert result["no_data"] is True
        assert result["level"] is None
        assert result["growth"] is None
        assert result["breadth"] is None
        assert result["heat_index"] is None
        assert result["lifecycle"] == "unknown"


class TestExplicitMarketNoDefaultGap:
    """P1-2：显式传入 CN 不得记录为默认市场 gap"""

    def test_explicit_cn_not_recorded_as_default(self):
        agent = TrendAgent(google_connector=FakeGoogle(), bilibili_connector=FakeBilibili())
        out = _run(agent, market="CN")
        fm = _parse(out)
        assert not any("market" in c and "未指定" in c for c in fm.caveats)

    def test_missing_market_recorded_as_gap(self):
        import asyncio

        agent = TrendAgent(google_connector=FakeGoogle(), bilibili_connector=FakeBilibili())
        # brief 不含 market 且 context 也不传 market → 记录默认市场 gap
        out = asyncio.run(agent.run({"brief": {"category": "解压玩具", "budget_range": "mid"}}))
        fm = _parse(out)
        assert any("market" in c and "未指定" in c for c in fm.caveats)


class TestRegistrySwitch:
    def test_default_is_mock(self, monkeypatch):
        monkeypatch.delenv("TREND_AGENT_PROVIDER", raising=False)
        from app.agents.mock_agents import MockTrendAgent
        assert get_trend_agent_class() is MockTrendAgent

    def test_real_when_provider_set(self, monkeypatch):
        monkeypatch.setenv("TREND_AGENT_PROVIDER", "real")
        assert get_trend_agent_class() is TrendAgent

    def test_mock_kept_as_fallback(self, monkeypatch):
        monkeypatch.setenv("TREND_AGENT_PROVIDER", "bogus")
        from app.agents.mock_agents import MockTrendAgent
        assert get_trend_agent_class() is MockTrendAgent
