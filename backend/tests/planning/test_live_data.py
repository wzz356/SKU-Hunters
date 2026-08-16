from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.planning.live_data import build_live_data_board
from app.planning.live_insights import build_live_insight_bundle
from app.schemas.base_data import BaseRecord


def _record(record_id: str, *, category: str, platform: str, heat: float, price: str | None = "39-99", snapshot_id: str = "snap-1") -> BaseRecord:
    return BaseRecord(
        record_id=record_id,
        keyword=f"关键词-{record_id}",
        platform=platform,
        category=category,
        summary=f"真实摘要-{record_id}",
        heat_index=heat,
        interaction=100,
        brand="品牌A",
        price_range=price,
        record_date="2026-08-01",
        source_url=f"https://example.com/{record_id}",
        snapshot_id=snapshot_id,
        ingested_at="2026-08-02T00:00:00+00:00",
    )


class _Adapter:
    def __init__(self, records, summary=None, summary_error=None, summary_calls=None):
        self.records = records
        self.summary = summary
        self.summary_error = summary_error
        self.summary_calls = summary_calls if summary_calls is not None else []

    def search_all(self, keyword="", category=None):
        assert keyword == ""
        if category is None:
            return self.records
        return [record for record in self.records if record.category == category]

    def build_evidence_refs(self, records):
        return [{"url": record.source_url} for record in records if record.source_url]

    def get_summary(self, category=None, as_of=None, snapshot_id=None):
        self.summary_calls.append({"category": category, "snapshot_id": snapshot_id})
        if self.summary_error is not None:
            raise self.summary_error
        if self.summary is None:
            return {}
        return self.summary


def test_live_data_board_aggregates_records_without_fixture_values():
    data = build_live_data_board(
        _Adapter([
            _record("1", category="便携小风扇", platform="xiaohongshu", heat=91),
            _record("2", category="手持小风扇", platform="tiktok", heat=73, price="120-149"),
        ])
    )

    assert data["dataSource"] == "feishu"
    assert data["recordCount"] == 2
    assert {row["name"] for row in data["categoryRank"]} == {"便携小风扇", "手持小风扇"}
    assert data["hotProducts"][0]["heat"] == 91  # 热度指标，非销量
    assert data["voiceTrend"]["xhs"] == [1]
    assert data["voiceTrend"]["douyin"] == [1]
    assert sum(row["recordCount"] for row in data["priceBands"]) == 2


def test_live_insights_use_matching_category_records_and_leave_unavailable_fields_empty():
    data = build_live_insight_bundle(
        "小风扇",
        adapter=_Adapter([
            _record("1", category="便携小风扇", platform="xiaohongshu", heat=91),
            _record("ip", category="IP", platform="weibo", heat=88, price=None),
        ]),
    )

    assert data["dataSource"] == "feishu"
    assert data["recordCount"] == 1
    assert data["trendRadar"]["signals"]
    assert data["insightBase"]["ipPool"]
    assert data["consumerVoice"]["painPoints"] == []
    assert data["consumerVoice"]["scenes"] == []
    assert data["trendGallery"]["colors"] == []


def test_live_insights_reads_summary_pain_points_and_scenes():
    """汇总表提供 pain_points/scenes 时，正确映射为前端契约并在 processLog 标注数量"""
    adapter = _Adapter(
        [_record("1", category="便携小风扇", platform="xiaohongshu", heat=91)],
        summary={
            "pain_points": [{"text": "噪音大", "count": 12}, {"text": "续航短", "count": 8}],
            "scenes": [{"name": "通勤", "value": 30}, {"name": "宿舍", "value": 20}],
        },
    )
    data = build_live_insight_bundle("小风扇", adapter=adapter)

    assert data["dataSource"] == "feishu"
    assert data["consumerVoice"]["painPoints"] == [
        {"text": "噪音大", "count": 12},
        {"text": "续航短", "count": 8},
    ]
    assert data["consumerVoice"]["scenes"] == [
        {"name": "通勤", "value": 30},
        {"name": "宿舍", "value": 20},
    ]
    log = " ".join(data["consumerVoice"]["processLog"])
    assert "痛点 2 条" in log and "场景 2 条" in log
    # 快照正确传递到 get_summary
    assert adapter.summary_calls[-1]["snapshot_id"] == "snap-1"


def test_live_insights_summary_missing_fields_stays_empty():
    """汇总表有行但缺 pain_points/scenes 字段 → 保持空，processLog 如实说明"""
    data = build_live_insight_bundle(
        "小风扇",
        adapter=_Adapter(
            [_record("1", category="便携小风扇", platform="xiaohongshu", heat=91)],
            summary={"brands": ["几素"], "record_count": 10},
        ),
    )
    assert data["consumerVoice"]["painPoints"] == []
    assert data["consumerVoice"]["scenes"] == []
    log = " ".join(data["consumerVoice"]["processLog"])
    assert "未提供结构化痛点/场景字段" in log


def test_live_insights_invalid_summary_entries_skipped():
    """非法条目（空 text/name、非 dict、负值、非法 count）被跳过，不抛异常"""
    data = build_live_insight_bundle(
        "小风扇",
        adapter=_Adapter(
            [_record("1", category="便携小风扇", platform="xiaohongshu", heat=91)],
            summary={
                "pain_points": [
                    {"text": "有效", "count": 5},
                    {"text": "", "count": 3},            # 空 text → 跳过
                    {"count": 3},                        # 缺 text → 跳过
                    {"text": "负值", "count": -1},       # 负 count → 跳过
                    {"text": "非法count", "count": "abc"},  # 非法 count → 跳过
                    "not-a-dict",                        # 非 dict → 跳过
                    {"text": 123, "count": 3},           # text 非 str → 跳过
                ],
                "scenes": [
                    {"name": "通勤", "value": 10},
                    {"name": "", "value": 5},            # 空 name → 跳过
                    {"value": 5},                        # 缺 name → 跳过
                    {"name": "负值", "value": -1},       # 负 value → 跳过
                    {"name": "非法", "value": "x"},      # 非法 value → 跳过
                    "bad",                               # 非 dict → 跳过
                ],
            },
        ),
    )
    assert data["consumerVoice"]["painPoints"] == [{"text": "有效", "count": 5}]
    assert data["consumerVoice"]["scenes"] == [{"name": "通勤", "value": 10}]


def test_live_insights_summary_error_keeps_empty_and_logs_failure():
    """get_summary 抛 BaseUnavailable/BaseProviderError → 空值，processLog 说明读取失败而非暂无数据"""
    for exc in (BaseUnavailable("汇总表不可用"), BaseProviderError("网络错误")):
        data = build_live_insight_bundle(
            "小风扇",
            adapter=_Adapter(
                [_record("1", category="便携小风扇", platform="xiaohongshu", heat=91)],
                summary_error=exc,
            ),
        )
        assert data["consumerVoice"]["painPoints"] == []
        assert data["consumerVoice"]["scenes"] == []
        log = " ".join(data["consumerVoice"]["processLog"])
        assert "汇总表读取失败" in log
        assert "暂无" not in log


def test_live_insights_snapshot_isolation_uses_latest_snapshot_only():
    """多个快照时只保留最新快照的记录，并用该快照读取汇总，不混用"""
    adapter = _Adapter(
        [
            _record("old", category="便携小风扇", platform="xiaohongshu", heat=91, snapshot_id="snap-0"),
            _record("new1", category="便携小风扇", platform="tiktok", heat=73, snapshot_id="snap-1"),
            _record("new2", category="手持小风扇", platform="taobao", heat=60, snapshot_id="snap-1"),
        ],
        summary={"pain_points": [{"text": "有效", "count": 5}], "scenes": [{"name": "通勤", "value": 10}]},
    )
    data = build_live_insight_bundle("小风扇", adapter=adapter)

    # 只保留最新快照 snap-1 的两条记录（排除 snap-0）
    assert data["recordCount"] == 2
    # dataContext 写入选中的快照
    assert data["dataContext"]["snapshot_id"] == "snap-1"
    # get_summary 用选中的快照
    assert adapter.summary_calls[-1]["snapshot_id"] == "snap-1"
    # 汇总痛点/场景正常带出
    assert data["consumerVoice"]["painPoints"] == [{"text": "有效", "count": 5}]


# ── 父品类「风扇」归一化与聚合 ──────────────────────────

def test_build_bundle_normalizes_legacy_fan_category_to_parent():
    """旧任务「小风扇」归一化为父品类「风扇」，聚合所有含「扇」子品类记录"""
    adapter = _Adapter([
        _record("1", category="便携小风扇", platform="xiaohongshu", heat=91),
        _record("2", category="手持小风扇", platform="tiktok", heat=73),
    ])
    data = build_live_insight_bundle("小风扇", adapter=adapter)
    assert data["dataSource"] == "feishu"
    assert data["recordCount"] == 2  # 含「扇」的便携小风扇 + 手持小风扇 都聚合

def test_build_bundle_fan_parent_aggregates_all_subcategories():
    """查询父品类「风扇」匹配落地扇/塔扇等不含「风扇」字样的子品类"""
    adapter = _Adapter([
        _record("1", category="便携小风扇", platform="xiaohongshu", heat=91),
        _record("2", category="落地扇", platform="tiktok", heat=60),
        _record("3", category="塔扇", platform="taobao", heat=55),
        _record("4", category="循环扇", platform="taobao", heat=50),
        _record("5", category="雨伞", platform="taobao", heat=40),  # 不归入风扇
    ])
    data = build_live_insight_bundle("风扇", adapter=adapter)
    assert data["recordCount"] == 4  # 只聚合含「扇」的 4 条，雨伞排除
    assert data["dataContext"]["record_count"] == 4

def test_build_bundle_fan_parent_reads_fan_summary():
    """父品类归一化后，get_summary 收到的是父品类名「风扇」"""
    adapter = _Adapter(
        [_record("1", category="便携小风扇", platform="xiaohongshu", heat=91)],
        summary={"pain_points": [{"text": "噪音大", "count": 3}], "scenes": [{"name": "桌面", "value": 5}]},
    )
    data = build_live_insight_bundle("小风扇", adapter=adapter)
    # get_summary 使用归一化后的父品类
    assert adapter.summary_calls[-1]["category"] == "风扇"
    assert data["consumerVoice"]["painPoints"] == [{"text": "噪音大", "count": 3}]
