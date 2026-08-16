"""BaseDataAdapter 与 provider 测试 — 延迟初始化 / provider 模式 / fail-closed / as_of / snapshot / 分页 / 缓存"""

from __future__ import annotations

import pytest
from app.data.base_adapter import (
    BaseDataAdapter,
    BaseUnavailable,
    FeishuBaseProvider,
    MockBaseProvider,
)
from app.schemas.base_data import BaseRecordPage
from pydantic import ValidationError


def _clear_base_env(monkeypatch):
    for k in (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_BASE_APP_TOKEN",
        "FEISHU_DATA_TABLE_ID",
        "FEISHU_SUMMARY_TABLE_ID",
        "BASE_PROVIDER_MODE",
    ):
        monkeypatch.delenv(k, raising=False)


def _mock_adapter():
    """显式构造 mock 模式的 adapter（绕过环境变量，测试稳定）"""
    return BaseDataAdapter(provider=MockBaseProvider())


def test_import_and_construct_without_config(monkeypatch):
    """缺环境变量时 import + 构造不失败（延迟初始化，调用时才判断）"""
    _clear_base_env(monkeypatch)
    adapter = BaseDataAdapter()
    assert adapter is not None  # 构造成功，不抛错


def test_default_mode_is_disabled(monkeypatch):
    """默认 BASE_PROVIDER_MODE=disabled：任何 Base 数据调用 fail-closed"""
    _clear_base_env(monkeypatch)
    adapter = BaseDataAdapter()
    with pytest.raises(BaseUnavailable):
        adapter.search_records("小风扇")


def test_mock_mode_uses_fixture(monkeypatch):
    """显式 BASE_PROVIDER_MODE=mock 时使用本地 fixture provider"""
    _clear_base_env(monkeypatch)
    monkeypatch.setenv("BASE_PROVIDER_MODE", "mock")
    adapter = BaseDataAdapter()
    assert isinstance(adapter.provider, MockBaseProvider)


def test_feishu_provider_unavailable_without_config(monkeypatch):
    """FeishuBaseProvider 无 app_token/table_id → 调用时抛 BaseUnavailable（与无数据区分）"""
    _clear_base_env(monkeypatch)
    provider = FeishuBaseProvider(app_token=None, data_table_id=None, summary_table_id=None)
    with pytest.raises(BaseUnavailable):
        provider.search_records("小风扇")


def test_feishu_mode_without_config_fail_closed(monkeypatch):
    """BASE_PROVIDER_MODE=feishu 但缺配置 → 显式 fail-closed"""
    _clear_base_env(monkeypatch)
    monkeypatch.setenv("BASE_PROVIDER_MODE", "feishu")
    adapter = BaseDataAdapter()
    with pytest.raises(BaseUnavailable):
        adapter.search_records("小风扇")


def test_as_of_filters_future():
    """as_of 边界：不返回 record_date 晚于 as_of 的记录（防学习官用未来数据）"""
    adapter = _mock_adapter()
    page = adapter.search_records("小风扇", as_of="2026-08-02")
    assert page.total > 0
    for r in page.records:
        assert r.record_date <= "2026-08-02"


def test_snapshot_id_isolation_in_summary():
    """snapshot_id 隔离（get_summary）：按快照过滤，不同快照结果不同"""
    adapter = _mock_adapter()
    all_summary = adapter.get_summary(category="小风扇")
    snap_summary = adapter.get_summary(category="小风扇", snapshot_id="snap-2026-08-10")
    assert snap_summary["snapshot_id"] == "snap-2026-08-10"
    assert snap_summary["record_count"] <= all_summary["record_count"]


def test_snapshot_id_isolation_in_search_records():
    """snapshot_id 隔离（search_records）：锁定快照，忽略其他版本"""
    adapter = _mock_adapter()
    page = adapter.search_records("小风扇", snapshot_id="snap-2026-08-10")
    assert page.total > 0
    for r in page.records:
        assert r.snapshot_id == "snap-2026-08-10"


def test_search_all_collects_all_pages():
    """search_all 翻页收集全部记录，而非只取默认 page_size=20 的第一页"""
    # 构造超过一页（page_size 设为 2）的 provider，验证 search_all 翻页完整
    many = [dict(_fixture_record(), record_id=f"r-{i}", keyword=f"词{i}") for i in range(25)]
    provider = MockBaseProvider(records=many)
    adapter = BaseDataAdapter(provider=provider)
    # 直接验证 search_all 内部翻页：分页拿第一页 2 条 + 后续页，最终应拿到 25 条
    all_records = adapter.search_all("")
    assert len(all_records) == 25


class _CountingProvider:
    """计数 provider：验证缓存避免重复调用"""

    def __init__(self):
        self.search_calls = 0
        self.summary_calls = 0

    def search_records(self, keyword, platform=None, category=None, as_of=None, snapshot_id=None, page=1, page_size=20):
        self.search_calls += 1
        return BaseRecordPage(records=[], total=0, page=page, page_size=page_size)

    def get_summary(self, category=None, as_of=None, snapshot_id=None):
        self.summary_calls += 1
        return {"category": category or "all", "record_count": 0}

    def get_date_distribution(self, keyword, as_of=None, snapshot_id=None):
        return []


def test_cache_prevents_duplicate_call():
    """相同查询命中缓存，不重复调用 provider"""
    provider = _CountingProvider()
    adapter = BaseDataAdapter(provider=provider)
    adapter.search_records("小风扇")
    adapter.search_records("小风扇")
    assert provider.search_calls == 1


def test_cache_key_includes_query_conditions():
    """缓存 key 含查询条件：不同 as_of / 不同 snapshot_id / 不同 keyword 走不同缓存"""
    provider = _CountingProvider()
    adapter = BaseDataAdapter(provider=provider)
    adapter.search_records("小风扇", as_of="2026-08-02")
    adapter.search_records("小风扇", as_of="2026-08-05")
    adapter.search_records("小风扇", snapshot_id="snap-2026-08-10")
    adapter.search_records("保温杯")
    assert provider.search_calls == 4


def test_no_data_distinct_from_failure():
    """无数据（空结果）与数据源故障（BaseUnavailable）严格区分"""
    adapter = _mock_adapter()  # 本地 fixture，无故障
    page = adapter.search_records("完全不存在的关键词xyz")
    assert page.total == 0  # 无数据，不抛异常


def _fixture_record() -> dict:
    return {
        "keyword": "小风扇",
        "platform": "xiaohongshu",
        "category": "小风扇",
        "summary": "便携小风扇需求上升",
        "heat_index": 82.5,
        "interaction": 1200.0,
        "brand": "几素",
        "price_range": "39-99 元",
        "record_date": "2026-08-01",
        "source_url": "https://example.com/fan/001",
        "snapshot_id": "snap-2026-08-10",
        "ingested_at": "2026-08-10T10:00:00+00:00",
    }


def test_search_records_validates_as_of():
    """实际调用链路：search_records 非法 as_of 触发 BaseQuery 校验（不只是模型本身）"""
    adapter = _mock_adapter()
    with pytest.raises(ValidationError):
        adapter.search_records("小风扇", as_of="2026/99/99")


def test_get_summary_validates_as_of():
    """实际调用链路：get_summary 非法 as_of 触发 BaseQuery 校验"""
    adapter = _mock_adapter()
    with pytest.raises(ValidationError):
        adapter.get_summary(category="小风扇", as_of="not-a-date")


def test_get_date_distribution_validates_as_of():
    """实际调用链路：get_date_distribution 非法 as_of 触发 BaseQuery 校验"""
    adapter = _mock_adapter()
    with pytest.raises(ValidationError):
        adapter.get_date_distribution("小风扇", as_of="2026/13/45")


class _InfiniteHasMoreProvider:
    """异常 provider：持续返回 has_more=True 但无记录，模拟会致死循环的故障"""

    def search_records(self, keyword, platform=None, category=None, as_of=None, snapshot_id=None, page=1, page_size=20):
        return BaseRecordPage(records=[], total=0, page=page, page_size=page_size, has_more=True)

    def get_summary(self, category=None, as_of=None, snapshot_id=None):
        return {"category": category or "all", "record_count": 0}

    def get_date_distribution(self, keyword, as_of=None, snapshot_id=None):
        return []


def test_search_all_no_progress_protection():
    """search_all 防死循环：provider 持续 has_more=True 但无记录时，无进展保护终止翻页"""
    adapter = BaseDataAdapter(provider=_InfiniteHasMoreProvider())
    records = adapter.search_all("")
    assert records == []  # 不进入死循环，快速返回
