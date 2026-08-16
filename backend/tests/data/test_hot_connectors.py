"""热搜连接器 + 聚合器测试 — mock httpx，不触网

锁定三件事：
  1. 解析正确性（微博/百度各自的返回结构）
  2. 失败语义（HTTP/业务错误 → ConnectorFetchError；空榜 → 空列表）
  3. 聚合器故障隔离（单源失败不影响其他源；全失败 → 抛错；零命中 ≠ 故障）
"""

from unittest.mock import MagicMock

import pytest
from app.data import hot_topics
from app.data.baidu_hot import BaiduHotConnector
from app.data.errors import ConnectorFetchError
from app.data.tiktok_trends import TiktokTrendsConnector
from app.data.weibo_hot import WeiboHotConnector


def _mock_httpx(monkeypatch, payload=None, status_ok=True):
    """替换 httpx.get 为返回固定 payload 的假实现"""
    resp = MagicMock()
    if not status_ok:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
    resp.json.return_value = payload
    monkeypatch.setattr("httpx.get", lambda *a, **kw: resp)


# ── 微博 ────────────────────────────────────────────────


def test_weibo_parses_realtime_board(monkeypatch):
    _mock_httpx(monkeypatch, {
        "ok": 1,
        "data": {"realtime": [
            {"word": "露营热", "num": 1234567},
            {"word": "  ", "num": 1},          # 空词条应被过滤
            {"word": "小风扇走红", "num": 765432},
        ]},
    })
    items = WeiboHotConnector().get_hot_search()
    assert [i["word"] for i in items] == ["露营热", "小风扇走红"]
    assert items[0]["heat"] == 1234567
    assert items[0]["rank"] == 1
    assert "weibo.com" in items[0]["url"]


def test_weibo_raises_on_business_error(monkeypatch):
    _mock_httpx(monkeypatch, {"ok": 0})
    with pytest.raises(ConnectorFetchError, match="weibo"):
        WeiboHotConnector().get_hot_search()


def test_weibo_raises_on_http_error(monkeypatch):
    _mock_httpx(monkeypatch, status_ok=False)
    with pytest.raises(ConnectorFetchError, match="weibo"):
        WeiboHotConnector().get_hot_search()


def test_weibo_empty_board_is_not_error(monkeypatch):
    _mock_httpx(monkeypatch, {"ok": 1, "data": {"realtime": []}})
    assert WeiboHotConnector().get_hot_search() == []


# ── 百度 ────────────────────────────────────────────────


def test_baidu_parses_cards(monkeypatch):
    _mock_httpx(monkeypatch, {
        "success": True,
        "data": {"cards": [{"content": [
            {"word": "户外露营季", "hotScore": "7654321", "url": "https://x"},
            {"word": "降温神器", "hotScore": "1234567"},
        ]}]},
    })
    items = BaiduHotConnector().get_hot_search()
    assert [i["word"] for i in items] == ["户外露营季", "降温神器"]
    assert items[0]["heat"] == 7654321
    assert items[1]["url"].startswith("https://www.baidu.com/s?wd=")


def test_baidu_raises_on_unsuccess(monkeypatch):
    _mock_httpx(monkeypatch, {"success": False})
    with pytest.raises(ConnectorFetchError, match="baidu"):
        BaiduHotConnector().get_hot_search()


def test_baidu_respects_limit(monkeypatch):
    _mock_httpx(monkeypatch, {
        "success": True,
        "data": {"cards": [{"content": [{"word": f"词{i}", "hotScore": "1"} for i in range(10)]}]},
    })
    assert len(BaiduHotConnector().get_hot_search(limit=3)) == 3


# ── TikTok Creative Center ──────────────────────────────


def test_tiktok_parses_hashtag_board(monkeypatch):
    _mock_httpx(monkeypatch, {
        "code": 0,
        "data": {"list": [
            {"hashtag_name": "summervibes", "video_views": 123456789},
            {"hashtag_name": "  ", "video_views": 1},      # 空词条应被过滤
            {"hashtag_name": "kuromi", "video_views": 987654},
        ]},
    })
    items = TiktokTrendsConnector().get_trending_hashtags("US")
    assert [i["word"] for i in items] == ["summervibes", "kuromi"]
    assert items[0]["heat"] == 123456789
    assert items[0]["country"] == "US"
    assert "creativecenter" in items[0]["url"]


def test_tiktok_raises_on_business_error(monkeypatch):
    _mock_httpx(monkeypatch, {"code": 40100, "msg": "blocked"})
    with pytest.raises(ConnectorFetchError, match="tiktok"):
        TiktokTrendsConnector().get_trending_hashtags()


def test_tiktok_raises_on_http_error(monkeypatch):
    _mock_httpx(monkeypatch, status_ok=False)
    with pytest.raises(ConnectorFetchError, match="tiktok"):
        TiktokTrendsConnector().get_trending_hashtags()


def test_tiktok_empty_board_is_not_error(monkeypatch):
    _mock_httpx(monkeypatch, {"code": 0, "data": {"list": []}})
    assert TiktokTrendsConnector().get_trending_hashtags() == []


# ── 聚合器 ──────────────────────────────────────────────


def test_aggregator_isolates_single_source_failure(monkeypatch):
    ok_item = [{"word": "露营热", "heat": 1, "rank": 1, "url": ""}]
    monkeypatch.setattr(hot_topics.WeiboHotConnector, "get_hot_search",
                        lambda self: ok_item)
    monkeypatch.setattr(hot_topics.TiktokTrendsConnector, "get_hot_search",
                        lambda self: [{"word": "camping", "heat": 1, "rank": 1,
                                       "url": "", "country": "US"}])
    monkeypatch.setattr(hot_topics.DouyinHotConnector, "get_hot_search",
                        lambda self: ok_item)
    monkeypatch.setattr(hot_topics.XiaohongshuHotConnector, "get_hot_search",
                        lambda self: ok_item)

    def boom(self):
        raise ConnectorFetchError("baidu", "HTTP 502")

    monkeypatch.setattr(hot_topics.BaiduHotConnector, "get_hot_search", boom)
    payload = hot_topics.fetch_all()
    assert payload["scanned_sources"] == ["weibo", "douyin", "xiaohongshu", "tiktok"]
    assert payload["failed_sources"] == [{"source": "baidu", "detail": "HTTP 502"}]
    assert payload["items"][0]["source"] == "weibo"
    assert payload["items"][-1]["source"] == "tiktok"


def test_aggregator_raises_when_all_sources_fail(monkeypatch):
    def boom(self):
        raise ConnectorFetchError("x", "超时")

    monkeypatch.setattr(hot_topics.WeiboHotConnector, "get_hot_search", boom)
    monkeypatch.setattr(hot_topics.BaiduHotConnector, "get_hot_search", boom)
    monkeypatch.setattr(hot_topics.DouyinHotConnector, "get_hot_search", boom)
    monkeypatch.setattr(hot_topics.XiaohongshuHotConnector, "get_hot_search", boom)
    monkeypatch.setattr(hot_topics.TiktokTrendsConnector, "get_hot_search", boom)
    with pytest.raises(ConnectorFetchError, match="全部热搜源失败"):
        hot_topics.fetch_all()


def test_match_keywords_zero_hit_is_not_failure():
    payload = {
        "items": [{"source": "weibo", "word": "无关词条", "heat": 1, "rank": 1}],
        "scanned_sources": ["weibo"],
        "failed_sources": [],
    }
    matched = hot_topics.match_keywords(payload, ["小风扇"])
    assert matched["hits"] == []
    assert matched["scanned_sources"] == ["weibo"]


def test_match_keywords_finds_relevant():
    payload = {
        "items": [
            {"source": "weibo", "word": "露营经济带火周边", "heat": 99, "rank": 3},
            {"source": "baidu", "word": "高考分数线", "heat": 1, "rank": 1},
        ],
        "scanned_sources": ["weibo", "baidu"],
        "failed_sources": [],
    }
    matched = hot_topics.match_keywords(payload, ["露营", "风扇"])
    assert [h["word"] for h in matched["hits"]] == ["露营经济带火周边"]
