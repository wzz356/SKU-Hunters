"""UApiPro 热榜连接器测试 — mock httpx，不触网

锁定三件事：
  1. 三种模式的解析正确性（实时榜 / 时光机快照 / 历史检索）
  2. 失败语义（HTTP/业务错误 → ConnectorFetchError；空榜/零命中 → 空列表）
  3. 聚合器兼容形状（get_hot_search 的 word/heat/rank/url）
  4. daily_hits 逐日序列（本地匹配、best_rank 计算）
"""

from unittest.mock import MagicMock

import pytest

from app.data.errors import ConnectorFetchError
from app.data.uapi_hot import (
    DouyinHotConnector,
    UapiHotConnector,
    XiaohongshuHotConnector,
)


def _mock_httpx(monkeypatch, payload=None, status_ok=True):
    resp = MagicMock()
    if not status_ok:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
    resp.json.return_value = payload
    monkeypatch.setattr("httpx.get", lambda *a, **kw: resp)
    return resp


BOARD_PAYLOAD = {
    "type": "douyin",
    "update_time": "2026-08-14T03:01:42.434Z",
    "list": [
        {"index": 1, "title": "露营装备爆火", "url": "https://x/1", "hot_value": "1200万", "extra": {}},
        {"index": 2, "title": "", "url": "https://x/2"},  # 空标题应被过滤
        {"index": 3, "title": "无关词条", "url": "https://x/3", "hot_value": "100万"},
    ],
}


# ── 实时榜 / 时光机 ──────────────────────────────────────


def test_realtime_board_parsing(monkeypatch):
    _mock_httpx(monkeypatch, BOARD_PAYLOAD)
    board = DouyinHotConnector().get_hot_board()
    assert board["platform"] == "douyin"
    assert [i["title"] for i in board["items"]] == ["露营装备爆火", "无关词条"]
    assert board["items"][0]["rank"] == 1
    assert board["items"][0]["hot_value"] == "1200万"


def test_timemachine_passes_ms_timestamp(monkeypatch):
    captured = {}

    def fake_get(url, params=None, **kw):
        captured.update(params or {})
        resp = MagicMock()
        resp.json.return_value = {**BOARD_PAYLOAD, "snapshot_time": 1786591604698}
        return resp

    monkeypatch.setattr("httpx.get", fake_get)
    board = DouyinHotConnector().get_hot_board(time_ms=1786591604698)
    assert captured["time"] == 1786591604698
    assert board["snapshot_time"] == 1786591604698


def test_empty_board_is_not_error(monkeypatch):
    _mock_httpx(monkeypatch, {"type": "douyin", "update_time": "", "snapshot_time": 0, "list": []})
    assert DouyinHotConnector().get_hot_board(time_ms=1)["items"] == []


def test_business_error_raises(monkeypatch):
    _mock_httpx(monkeypatch, {"code": "INVALID_PARAMETER", "message": "type is required"})
    with pytest.raises(ConnectorFetchError, match="INVALID_PARAMETER"):
        DouyinHotConnector().get_hot_board()


def test_http_error_raises(monkeypatch):
    _mock_httpx(monkeypatch, status_ok=False)
    with pytest.raises(ConnectorFetchError, match="douyin"):
        DouyinHotConnector().get_hot_board()


def test_missing_platform_raises():
    with pytest.raises(ConnectorFetchError, match="platform"):
        UapiHotConnector().get_hot_board()


# ── 历史检索 ──────────────────────────────────────────────


def test_search_history_parsing(monkeypatch):
    _mock_httpx(monkeypatch, {
        "type": "weibo", "keyword": "iPhone", "count": 1,
        "items": [{"source": "sina", "snapshot_ts": 1786073834820, "rank": 1,
                   "title": "iPhone18Pro十二大升级", "hot_value": "375万", "url": "https://x"}],
    })
    conn = UapiHotConnector(platform="weibo")
    result = conn.search_history("iPhone", 1786073834820, 1786675019401)
    assert result["count"] == 1
    assert result["items"][0]["snapshot_ts"] == 1786073834820


def test_search_history_zero_hit_is_normal(monkeypatch):
    _mock_httpx(monkeypatch, {"type": "weibo", "keyword": "风扇", "count": 0, "items": []})
    conn = UapiHotConnector(platform="weibo")
    result = conn.search_history("风扇", 0, 1)
    assert result["count"] == 0 and result["items"] == []


# ── 聚合器兼容形状 ────────────────────────────────────────


def test_aggregator_compatible_shape(monkeypatch):
    _mock_httpx(monkeypatch, BOARD_PAYLOAD)
    items = XiaohongshuHotConnector().get_hot_search(limit=1)
    assert len(items) == 1
    assert items[0] == {
        "word": "露营装备爆火", "heat": "1200万", "rank": 1, "url": "https://x/1",
    }


# ── 逐日命中序列 ──────────────────────────────────────────


def test_daily_hits_counts_and_best_rank(monkeypatch):
    def fake_get(url, params=None, **kw):
        resp = MagicMock()
        resp.json.return_value = {
            "type": "douyin", "snapshot_time": params.get("time"),
            "list": [
                {"index": 5, "title": "小风扇爆火", "url": "", "hot_value": ""},
                {"index": 9, "title": "小风扇测评", "url": "", "hot_value": ""},
                {"index": 1, "title": "无关", "url": "", "hot_value": ""},
            ],
        }
        return resp

    monkeypatch.setattr("httpx.get", fake_get)
    series = DouyinHotConnector().daily_hits("小风扇", days=3)
    assert len(series) == 3
    assert all(s["hits"] == 2 for s in series)
    assert all(s["best_rank"] == 5 for s in series)
    assert [s["date"] for s in series] == sorted(s["date"] for s in series)  # 日期升序


def test_daily_hits_zero_hit_day(monkeypatch):
    _mock_httpx(monkeypatch, {"type": "douyin", "snapshot_time": 0, "list": []})
    series = DouyinHotConnector().daily_hits("小风扇", days=2)
    assert [s["hits"] for s in series] == [0, 0]
    assert [s["best_rank"] for s in series] == [None, None]
