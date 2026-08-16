"""Scoped View 隔离测试 — 每个 View 只暴露自己的方法，依赖受限查询端口"""

from __future__ import annotations

from app.data.base_adapter import BaseDataAdapter, MockBaseProvider, RestrictedQueryPort
from app.data.scoped_views import (
    BusinessSummaryView,
    ConsumerDataView,
    GTMMarketView,
    IPDataView,
    LearningLedgerReadView,
    RetroLedgerWriter,
    TrendDataView,
)


def _port() -> RestrictedQueryPort:
    """构造受限查询端口（不把完整 adapter 暴露给 View）"""
    return RestrictedQueryPort(BaseDataAdapter(provider=MockBaseProvider()))


def test_view_does_not_expose_adapter():
    """View 不公开 raw adapter（依赖受限端口 _port，无公开 adapter / 私有 _adapter）"""
    view = TrendDataView(_port())
    assert not hasattr(view, "adapter")
    assert not hasattr(view, "_adapter")
    # View 持有的是受限查询端口，公共接口仅限只读查询
    assert hasattr(view, "_port")


def test_trend_view_only_trend_methods():
    """TrendDataView 只暴露趋势方法，不暴露消费者/IP/商业方法"""
    view = TrendDataView(_port())
    assert hasattr(view, "search_trend_signals")
    assert hasattr(view, "compute_heat_index")
    assert not hasattr(view, "get_reviews_by_category")   # 消费者方法
    assert not hasattr(view, "search_ip_mentions")         # IP 方法
    assert not hasattr(view, "get_brand_concentration")    # 商业方法


def test_consumer_view_only_consumer_methods():
    """ConsumerDataView 不暴露趋势/IP 方法"""
    view = ConsumerDataView(_port())
    assert hasattr(view, "get_reviews_by_category")
    assert hasattr(view, "get_search_intent")
    assert not hasattr(view, "search_trend_signals")
    assert not hasattr(view, "search_ip_mentions")


def test_ip_view_only_ip_methods():
    """IPDataView 不暴露消费者/商业方法"""
    view = IPDataView(_port())
    assert hasattr(view, "search_ip_mentions")
    assert hasattr(view, "get_brand_top20")
    assert not hasattr(view, "get_reviews_by_category")
    assert not hasattr(view, "get_brand_concentration")


def test_learning_view_is_read_only():
    """LearningLedgerReadView 只读：不含任何写入方法"""
    view = LearningLedgerReadView(_port())
    assert hasattr(view, "get_decision_record")
    assert not hasattr(view, "append_retro_entry")   # 写入方法在独立端口
    assert not hasattr(view, "write")
    assert not hasattr(view, "save")


def test_views_are_mutually_exclusive():
    """不同 View 的方法集互不重叠（除 build_evidence_refs 公共工具外）"""
    views = [
        TrendDataView(_port()),
        ConsumerDataView(_port()),
        IPDataView(_port()),
        BusinessSummaryView(_port()),
        GTMMarketView(_port()),
    ]
    common = {"build_evidence_refs"}  # 只允许证据引用工具共享
    seen: dict[str, str] = {}
    for v in views:
        for m in dir(v):
            if m.startswith("_") or m in common:
                continue
            if callable(getattr(v, m, None)):
                if m in seen:
                    assert False, f"方法 {m} 被 {seen[m]} 和 {type(v).__name__} 共享"
                seen[m] = type(v).__name__


def test_retro_ledger_writer_append_only():
    """RetroLedgerWriter 只追加不覆盖，返回写入条目"""
    writer = RetroLedgerWriter()
    e1 = writer.append_retro_entry("s1", "q1", "a1")
    e2 = writer.append_retro_entry("s1", "q2", "a2")
    assert e1["question"] == "q1"
    assert e2["question"] == "q2"
    assert len(writer._ledger) == 2  # 两条都在，未覆盖


def test_aggregation_uses_all_records_not_first_page():
    """聚合方法翻页取全量：超过默认 page_size 的记录也能被统计"""
    many = [
        {
            "record_id": f"r-{i}", "keyword": f"词{i}", "platform": "xiaohongshu",
            "category": "小风扇", "summary": "s", "heat_index": 50.0, "interaction": 1.0,
            "brand": "品牌A", "price_range": "39-99 元", "record_date": "2026-08-01",
            "source_url": None, "snapshot_id": "snap-x", "ingested_at": "2026-08-10T10:00:00+00:00",
        }
        for i in range(25)
    ]
    port = RestrictedQueryPort(BaseDataAdapter(provider=MockBaseProvider(records=many)))
    view = BusinessSummaryView(port)
    brand_concentration = view.get_brand_concentration("小风扇")
    # 25 条全部统计，而非只统计默认 page_size=20 的第一页
    assert brand_concentration["品牌A"] == 25
