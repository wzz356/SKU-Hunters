"""FeishuBaseProvider Mock API 测试 — 假 auth + mock requests.post 验证只读 provider 逻辑

不接真实飞书 API：字段名/表 ID 均为假值，仅验证字段转换、分页、fail-closed、边界处理。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.data.base_adapter import (
    BaseProviderError,
    BaseUnavailable,
    FeishuBaseProvider,
    category_matches,
    normalize_category,
)
from app.schemas.base_data import BasePlatform


class _FakeAuth:
    """假认证：返回固定 token，不触发真实 tenant_access_token 获取"""

    def get_token(self) -> str:
        return "fake-token"


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data
        self.status_code = 200

    def json(self) -> dict:
        return self._data


def _date_ms(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _record(**fields) -> dict:
    rid = fields.get("record_id", "rec-x")
    return {"record_id": rid, "fields": fields}


def _resp(items, has_more=False, page_token=None, total=None) -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "has_more": has_more,
            "page_token": page_token or "",
            "total": total if total is not None else len(items),
            "items": items,
        },
    }


def _base_fields(**overrides) -> dict:
    """构造一条合法的飞书字段（字段名按 feishu-base-mapping.md §四 设计假设）"""
    fields = {
        "record_id": "rec-001",
        "keyword": "小风扇",
        "platform": "xiaohongshu",
        "category": "小风扇",
        "summary": "便携小风扇需求上升",
        "heat_index": 82.5,
        "interaction": 1200,
        "brand": "几素",
        "price_range": "39-99 元",
        "record_date": _date_ms("2026-08-01"),
        "source_url": {"link": "https://example.com/fan/001", "text": "链接"},
        "snapshot_id": "snap-20260814T000000Z-1",
        "ingested_at": _date_ms("2026-08-10"),
        "raw_value": '{"likes": 1200}',
    }
    fields.update(overrides)
    return fields


def _provider_with(monkeypatch, responder):
    """构造 provider，注入假 auth，monkeypatch requests.post 为 responder(url, json)"""
    auth = _FakeAuth()
    monkeypatch.setattr(
        "requests.post",
        lambda url, headers=None, json=None, timeout=None, **kw: _FakeResponse(responder(url, json or {})),
    )
    return FeishuBaseProvider(
        auth=auth, app_token="fake-app", data_table_id="tbl-data", summary_table_id="tbl-summary"
    )


def test_normal_return(monkeypatch):
    """正常返回：飞书字段正确转换为 BaseRecord"""
    def responder(url, body):
        return _resp([_record(**_base_fields())])

    provider = _provider_with(monkeypatch, responder)
    page = provider.search_records("小风扇")
    assert page.total == 1
    r = page.records[0]
    assert r.record_id == "rec-001"
    assert r.keyword == "小风扇"
    assert r.platform == BasePlatform.XIAOHONGSHU
    assert r.heat_index == 82.5
    assert r.record_date == "2026-08-01"
    assert r.source_url == "https://example.com/fan/001"
    assert r.raw_value == {"likes": 1200}


def test_pagination(monkeypatch):
    """分页：page_token 游标翻页拉取全量"""
    responses = iter([
        _resp([_record(**_base_fields(record_id="r1"))], has_more=True, page_token="tok1"),
        _resp([_record(**_base_fields(record_id="r2"))], has_more=False),
    ])

    def responder(url, body):
        return next(responses)

    provider = _provider_with(monkeypatch, responder)
    page = provider.search_records("小风扇")
    assert page.total == 2  # 两页都拉取到


def test_pagination_uses_query_param_and_limit(monkeypatch):
    """分页游标走 URL query，数量参数使用飞书 records/search 的 limit。"""
    calls = []

    def post(url, headers=None, json=None, params=None, timeout=None):
        calls.append({"json": json, "params": params})
        if len(calls) == 1:
            return _FakeResponse(_resp([], has_more=True, page_token="next-token"))
        return _FakeResponse(_resp([], has_more=False))

    monkeypatch.setattr("requests.post", post)
    provider = FeishuBaseProvider(
        auth=_FakeAuth(), app_token="fake-app", data_table_id="tbl-data"
    )
    provider.search_records("小风扇")

    assert calls[0]["json"] == {"limit": 500}
    assert calls[0]["params"] == {}
    assert calls[1]["json"] == {"limit": 500}
    assert calls[1]["params"] == {"page_token": "next-token"}


def test_text_fields_and_raw_heat_are_normalized(monkeypatch):
    """飞书文本列表与超 100 的原始互动量可转换为合法 BaseRecord。"""
    fields = _base_fields(
        record_id=[{"text": "rec-list", "type": "text"}],
        keyword=[{"text": "小风扇", "type": "text"}],
        platform=[{"text": "xiaohongshu", "type": "text"}],
        category=[{"text": "小风扇", "type": "text"}],
        summary=[{"text": "摘要", "type": "text"}],
        heat_index=30600,
        brand=[{"text": "几素", "type": "text"}],
        price_range=[{"text": "39-99 元", "type": "text"}],
        snapshot_id=[{"text": "snap-list", "type": "text"}],
        raw_value=[{"text": '{"likes": 30600}', "type": "text"}],
    )

    def responder(url, body):
        return _resp([_record(**fields)])

    provider = _provider_with(monkeypatch, responder)
    record = provider.search_records("小风扇").records[0]

    assert record.record_id == "rec-list"
    assert record.keyword == "小风扇"
    assert record.heat_index == 82.43
    assert record.brand == "几素"
    assert record.raw_value == {"likes": 30600}


def test_missing_fields(monkeypatch):
    """字段缺失：brand/price_range/source_url 缺省 → None（不伪造）"""
    fields = _base_fields(brand=None, price_range=None, source_url=None)

    def responder(url, body):
        return _resp([_record(**fields)])

    provider = _provider_with(monkeypatch, responder)
    r = provider.search_records("小风扇").records[0]
    assert r.brand is None
    assert r.price_range is None
    assert r.source_url is None


def test_permission_error(monkeypatch):
    """权限错误：飞书返回非零 code → BaseProviderError（不伪装成无数据）"""
    def responder(url, body):
        return {"code": 1254001, "msg": "wrong request body", "data": {}}

    provider = _provider_with(monkeypatch, responder)
    with pytest.raises(BaseProviderError):
        provider.search_records("小风扇")


def test_empty_data(monkeypatch):
    """空数据：飞书返回 0 条 → 返回空 BaseRecordPage（不抛异常）"""
    def responder(url, body):
        return _resp([], has_more=False, total=0)

    provider = _provider_with(monkeypatch, responder)
    page = provider.search_records("小风扇")
    assert page.total == 0
    assert page.records == []


def test_snapshot_and_date_filter(monkeypatch):
    """快照与日期过滤：as_of 不读未来，snapshot_id 锁定版本"""
    items = [
        _record(**_base_fields(record_id="r1", record_date=_date_ms("2026-08-01"), snapshot_id="snap-A")),
        _record(**_base_fields(record_id="r2", record_date=_date_ms("2026-08-05"), snapshot_id="snap-A")),
        _record(**_base_fields(record_id="r3", record_date=_date_ms("2026-08-01"), snapshot_id="snap-B")),
    ]

    def responder(url, body):
        return _resp(items)

    provider = _provider_with(monkeypatch, responder)
    # as_of 过滤：只保留 record_date <= 08-02
    page = provider.search_records("小风扇", as_of="2026-08-02")
    assert page.total == 2
    assert {r.record_id for r in page.records} == {"r1", "r3"}
    # snapshot_id 过滤：只保留 snap-A
    page = provider.search_records("小风扇", snapshot_id="snap-A")
    assert page.total == 2
    assert {r.record_id for r in page.records} == {"r1", "r2"}


def test_invalid_platform_skipped(monkeypatch):
    """非法 platform：跳过 + 不归 OTHER（该记录不出现在结果中）"""
    items = [
        _record(**_base_fields(record_id="r1")),
        _record(**_base_fields(record_id="r2", platform="unknown_platform")),
    ]

    def responder(url, body):
        return _resp(items)

    provider = _provider_with(monkeypatch, responder)
    page = provider.search_records("小风扇")
    assert page.total == 1
    assert page.records[0].record_id == "r1"
    # caveat 被记录（不静默吞掉）
    assert len(provider.caveats) == 1
    assert provider.caveats[0]["record_id"] == "r2"
    assert provider.caveats[0]["field"] == "platform"


def test_network_error(monkeypatch):
    """网络/超时错误：requests 异常 → BaseProviderError"""
    import requests

    def raise_request(*args, **kwargs):
        raise requests.ConnectionError("connection timeout")

    auth = _FakeAuth()
    monkeypatch.setattr("requests.post", raise_request)
    provider = FeishuBaseProvider(auth=auth, app_token="fake-app", data_table_id="tbl-data")
    with pytest.raises(BaseProviderError):
        provider.search_records("小风扇")


def test_missing_config_fail_closed(monkeypatch):
    """缺 app_token/table_id → BaseUnavailable（fail-closed）"""
    monkeypatch.delenv("FEISHU_BASE_APP_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_DATA_TABLE_ID", raising=False)
    provider = FeishuBaseProvider(auth=_FakeAuth(), app_token=None, data_table_id=None)
    with pytest.raises(BaseUnavailable):
        provider.search_records("小风扇")


def test_get_summary_reads_summary_table(monkeypatch):
    """get_summary 只读汇总表，不读明细表；无匹配快照 → BaseUnavailable"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(record_id="s1", category="小风扇", snapshot_id="snap-A",
                                  record_count=10, avg_heat_index=75.5,
                                  brands='["几素", "哈尔斯"]')])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["record_count"] == 10
    assert summary["avg_heat_index"] == 75.5
    assert summary["brands"] == ["几素", "哈尔斯"]
    # 无匹配快照 → BaseUnavailable（一期不做静默实时聚合降级）
    with pytest.raises(BaseUnavailable):
        provider.get_summary(category="小风扇", snapshot_id="不存在的快照")


def test_http_error_status(monkeypatch):
    """HTTP 4xx/5xx：即使响应体 code=0 也判失败（先查 HTTP 状态码）"""

    class _ErrorResponse:
        status_code = 500

        def json(self):
            return {"code": 0, "msg": "success", "data": {"has_more": False, "items": []}}

    auth = _FakeAuth()
    monkeypatch.setattr("requests.post", lambda *a, **k: _ErrorResponse())
    provider = FeishuBaseProvider(auth=auth, app_token="fake-app", data_table_id="tbl-data")
    with pytest.raises(BaseProviderError):
        provider.search_records("小风扇")


def test_cache_prevents_duplicate_fetch(monkeypatch):
    """请求级缓存：多次 search_records 只拉一次飞书；clear_cache 后重新拉取"""
    call_count = {"n": 0}

    def responder(url, body):
        call_count["n"] += 1
        return _resp([_record(**_base_fields())])

    provider = _provider_with(monkeypatch, responder)
    provider.search_records("小风扇")
    provider.search_records("小风扇")
    assert call_count["n"] == 1  # 缓存命中，不重复拉取

    provider.clear_cache()
    provider.search_records("小风扇")
    assert call_count["n"] == 2  # 清缓存后重新拉取


def test_get_summary_duplicate_snapshot(monkeypatch):
    """汇总表：相同 snapshot_id 多条 → BaseProviderError（歧义，不静默取第一条）"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([
                _record(record_id="s1", category="小风扇", snapshot_id="snap-A", record_count=10),
                _record(record_id="s2", category="小风扇", snapshot_id="snap-A", record_count=20),
            ])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    with pytest.raises(BaseProviderError):
        provider.get_summary(category="小风扇", snapshot_id="snap-A")


def test_get_summary_selects_latest_as_of(monkeypatch):
    """汇总表：未指定 snapshot_id 时按 as_of 降序选最新"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([
                _record(record_id="s1", category="小风扇", snapshot_id="snap-old",
                        as_of=_date_ms("2026-08-01"), record_count=10),
                _record(record_id="s2", category="小风扇", snapshot_id="snap-new",
                        as_of=_date_ms("2026-08-10"), record_count=20),
            ])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇")
    assert summary["snapshot_id"] == "snap-new"
    assert summary["record_count"] == 20


def test_get_summary_duplicate_as_of(monkeypatch):
    """汇总表：多条相同 as_of（不同 snapshot_id）→ BaseProviderError（歧义）"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([
                _record(record_id="s1", category="小风扇", snapshot_id="snap-A",
                        as_of=_date_ms("2026-08-01"), record_count=10),
                _record(record_id="s2", category="小风扇", snapshot_id="snap-B",
                        as_of=_date_ms("2026-08-01"), record_count=20),
            ])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    with pytest.raises(BaseProviderError):
        provider.get_summary(category="小风扇")

# ── 汇总表文本字段归一化 + brands 兼容补丁 ──────────────────────────

def test_get_summary_text_list_fields_match(monkeypatch):
    """category/snapshot_id 为飞书文本列表 [{"text": "...", "type": "text"}] 时可正常匹配"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                record_count=10, avg_heat_index=75.5,
                brands=[{"text": '["几素", "哈尔斯"]', "type": "text"}],
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["record_count"] == 10
    assert summary["avg_heat_index"] == 75.5
    assert summary["snapshot_id"] == "snap-A"
    assert summary["brands"] == ["几素", "哈尔斯"]

def test_get_summary_by_category_text_list(monkeypatch):
    """get_summary(category='小风扇') 在 category 为文本列表时返回正确汇总（未指定 snapshot_id）"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                as_of=_date_ms("2026-08-10"),
                record_count=216, avg_heat_index=80.0,
                brands=["几素", "哈尔斯"],
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇")
    assert summary["record_count"] == 216
    assert summary["snapshot_id"] == "snap-A"
    assert summary["brands"] == ["几素", "哈尔斯"]

def test_brands_various_formats(monkeypatch):
    """brands 兼容：JSON 字符串 / 文本列表 / 普通字符串 / 已 list / 缺失"""
    def responder(url, body):
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    assert provider._to_brands('["几素", "哈尔斯"]') == ["几素", "哈尔斯"]
    assert provider._to_brands([{"text": '["几素", "哈尔斯"]', "type": "text"}]) == ["几素", "哈尔斯"]
    assert provider._to_brands("几素") == ["几素"]
    assert provider._to_brands(["几素", "哈尔斯"]) == ["几素", "哈尔斯"]
    assert provider._to_brands(None) == []
    assert provider._to_brands("") == []

def test_get_summary_missing_fields_no_fabrication(monkeypatch):
    """汇总表字段缺失时：record_count/brands 不伪造，用 0/空"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                # 缺 record_count / avg_heat_index / brands
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["record_count"] == 0
    assert summary["avg_heat_index"] == 0.0
    assert summary["brands"] == []  # 缺失不伪造

def test_summary_avg_heat_normalized(monkeypatch):
    """汇总表 avg_heat_index 为原始互动量时，对数归一化到 0-100"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "便携小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                avg_heat_index=440322838.4,  # 原始互动量均值
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="便携小风扇", snapshot_id="snap-A")
    assert 0.0 <= summary["avg_heat_index"] <= 100.0  # 归一化到 0-100


# ── 汇总表 pain_points / scenes 解析 ──────────────────────────

def test_summary_pain_points_scenes_json_text(monkeypatch):
    """汇总行 pain_points/scenes 为 JSON 文本字符串 → 正确解析为 list[dict]"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                pain_points='[{"text": "噪音大", "count": 5}, {"text": "续航短", "count": 3}]',
                scenes='[{"name": "桌面办公", "value": 8}, {"name": "户外通勤", "value": 6}]',
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["pain_points"] == [
        {"text": "噪音大", "count": 5.0}, {"text": "续航短", "count": 3.0},
    ]
    assert summary["scenes"] == [
        {"name": "桌面办公", "value": 8.0}, {"name": "户外通勤", "value": 6.0},
    ]

def test_summary_pain_points_scenes_text_list(monkeypatch):
    """pain_points/scenes 为飞书文本列表字段（[{"text": ..., "type": "text"}]）也可解析"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                pain_points=[{"text": '[{"text": "噪音大", "count": 5}]', "type": "text"}],
                scenes=[{"text": '[{"name": "桌面办公", "value": 8}]', "type": "text"}],
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["pain_points"] == [{"text": "噪音大", "count": 5.0}]
    assert summary["scenes"] == [{"name": "桌面办公", "value": 8.0}]

def test_summary_pain_points_scenes_missing(monkeypatch):
    """pain_points/scenes 字段缺失 → []，不伪造"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                # 缺 pain_points / scenes
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["pain_points"] == []
    assert summary["scenes"] == []

def test_summary_pain_points_scenes_broken_json(monkeypatch):
    """pain_points/scenes 为损坏 JSON / dict / 普通字符串 → []，不抛异常"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                pain_points='{broken json',        # 损坏 JSON
                scenes='{"not": "a list"}',         # dict，非 list
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["pain_points"] == []
    assert summary["scenes"] == []

def test_summary_pain_points_scenes_invalid_entries_skipped(monkeypatch):
    """非法条目（非 dict / 空 text / 无 count / 负 count / 不可转 float）跳过且不抛异常"""
    def responder(url, body):
        if "/tbl-summary/" in url:
            return _resp([_record(
                record_id="s1",
                category=[{"text": "小风扇", "type": "text"}],
                snapshot_id=[{"text": "snap-A", "type": "text"}],
                pain_points='['
                    '{"text": "有效痛点", "count": 3},'
                    '"not-a-dict",'
                    '{"text": "  ", "count": 1},'        # 空白 text
                    '{"count": 2},'                       # 缺 text
                    '{"text": "缺count"},'                # 缺 count
                    '{"text": "负count", "count": -1},'   # 负 count
                    '{"text": "坏count", "count": "abc"}' # count 不可转 float
                    ']',
                scenes='['
                    '{"name": "有效场景", "value": 8},'
                    '{"name": "负value", "value": -2},'
                    '{"name": "坏value", "value": "xyz"}'
                    ']',
            )])
        return _resp([])

    provider = _provider_with(monkeypatch, responder)
    summary = provider.get_summary(category="小风扇", snapshot_id="snap-A")
    assert summary["pain_points"] == [{"text": "有效痛点", "count": 3.0}]
    assert summary["scenes"] == [{"name": "有效场景", "value": 8.0}]


# ── 企划品类归一化与父品类匹配 ──────────────────────────

def test_normalize_category_maps_fan_subcategories_to_parent():
    """含「扇」的子品类（含旧任务名「小风扇」）统一归一化为父品类「风扇」"""
    assert normalize_category("小风扇") == "风扇"
    assert normalize_category("便携小风扇") == "风扇"
    assert normalize_category("手持小风扇") == "风扇"
    assert normalize_category("桌面风扇") == "风扇"
    assert normalize_category("塔扇") == "风扇"
    assert normalize_category("循环扇") == "风扇"
    assert normalize_category("风扇") == "风扇"

def test_normalize_category_keeps_non_fan_categories():
    """不含「扇」的品类（雨伞/香薰）原样返回，不归入风扇"""
    assert normalize_category("雨伞") == "雨伞"
    assert normalize_category("香薰") == "香薰"
    assert normalize_category("") == ""
    assert normalize_category(None) is None

def test_category_matches_fan_parent_substring_rule():
    """父品类「风扇」按子串规则匹配：明细 category 含「扇」即匹配"""
    assert category_matches("便携小风扇", "风扇") is True
    assert category_matches("落地扇", "风扇") is True
    assert category_matches("塔扇", "风扇") is True
    assert category_matches("循环扇", "风扇") is True
    assert category_matches("雨伞", "风扇") is False  # 不含「扇」不混入

def test_category_matches_exact_for_normal_categories():
    """普通品类等值匹配，不混入子串"""
    assert category_matches("雨伞", "雨伞") is True
    assert category_matches("香薰", "雨伞") is False
    assert category_matches("雨伞", None) is True
