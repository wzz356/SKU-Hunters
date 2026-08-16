"""BaseRecord 统一契约测试 — 日期/数值/平台校验 + source_url 不伪造"""

from __future__ import annotations

import pytest
from app.schemas.base_data import BaseRecord, BaseRecordPage
from pydantic import ValidationError


def _valid_record(**overrides) -> dict:
    base = {
        "record_id": "rec-001",
        "keyword": "小风扇",
        "platform": "xiaohongshu",
        "category": "小风扇",
        "summary": "便携小风扇夏季通勤需求上升",
        "heat_index": 82.5,
        "interaction": 1200.0,
        "brand": "几素",
        "price_range": "39-99 元",
        "record_date": "2026-08-01",
        "source_url": "https://example.com/fan/001",
        "snapshot_id": "snap-2026-08-10",
        "ingested_at": "2026-08-10T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_base_record_valid():
    """有效记录可构造，字段完整保留"""
    r = BaseRecord.model_validate(_valid_record())
    assert r.record_id == "rec-001"
    assert r.heat_index == 82.5
    assert r.source_url == "https://example.com/fan/001"


def test_record_date_must_be_iso_date():
    """record_date 非 YYYY-MM-DD 抛错"""
    with pytest.raises(ValidationError):
        BaseRecord.model_validate(_valid_record(record_date="2026/08/01"))


def test_ingested_at_must_be_iso8601():
    """ingested_at 非 ISO8601 抛错"""
    with pytest.raises(ValidationError):
        BaseRecord.model_validate(_valid_record(ingested_at="not-a-timestamp"))


def test_source_url_missing_normalized_to_none():
    """source_url 缺失/空/无效 → None（不伪造链接）"""
    r1 = BaseRecord.model_validate(_valid_record(source_url=None))
    assert r1.source_url is None
    r2 = BaseRecord.model_validate(_valid_record(source_url=""))
    assert r2.source_url is None
    r3 = BaseRecord.model_validate(_valid_record(source_url="javascript:alert(1)"))
    assert r3.source_url is None


def test_negative_heat_index_rejected():
    """负 heat_index 被 Field(ge=0) 拒绝"""
    with pytest.raises(ValidationError):
        BaseRecord.model_validate(_valid_record(heat_index=-1.0))


def test_negative_interaction_rejected():
    """负 interaction 被 Field(ge=0) 拒绝"""
    with pytest.raises(ValidationError):
        BaseRecord.model_validate(_valid_record(interaction=-5))


def test_record_page_pagination():
    """BaseRecordPage 分页字段校验"""
    page = BaseRecordPage(records=[], total=0, page=1, page_size=20)
    assert page.has_more is False
    with pytest.raises(ValidationError):
        BaseRecordPage(records=[], total=0, page=0, page_size=20)  # page 从 1 起


def test_platform_must_be_valid_enum():
    """platform 必须是 BasePlatform 枚举，非法值抛错"""
    with pytest.raises(ValidationError):
        BaseRecord.model_validate(_valid_record(platform="unknown_platform"))


def test_heat_index_above_100_rejected():
    """heat_index 超过 100 被 Field(le=100) 拒绝"""
    with pytest.raises(ValidationError):
        BaseRecord.model_validate(_valid_record(heat_index=150.0))


def test_base_query_as_of_validation():
    """BaseQuery 统一查询模型：as_of 校验 YYYY-MM-DD"""
    from app.schemas.base_data import BaseQuery

    q = BaseQuery(keyword="小风扇", as_of="2026-08-01", snapshot_id="snap-x")
    assert q.as_of == "2026-08-01"
    assert q.snapshot_id == "snap-x"
    with pytest.raises(ValidationError):
        BaseQuery(keyword="小风扇", as_of="2026/08/01")
