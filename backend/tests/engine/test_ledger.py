"""学习官台账读取端测试 — 飞轮闭环（历史档案反哺新会议）

锁定三件事：
  1. select_analogs 纯函数：未建档场次被过滤、同品类排前、limit、字段 compact
  2. query_analogs 故障降级：store 任何异常 → []（会议不阻塞）
  3. format_analogs：关键字段都在材料行里，缺分数显示"无评分"
"""

import pytest

from app.engine import ledger

_ROWS = [
    # 时间倒序（store.list_all 契约）：最新在前
    {"brief": {"category": "香薰"}, "archive": {
        "proposal": "无火香薰石", "predicted_score": 71.0,
        "ai_decision": "approve", "human_action": "confirm",
        "status": "archived", "retro_turns": 1}},
    {"brief": {"category": "小风扇"}, "archive": {
        "proposal": "库洛米旧款风扇", "predicted_score": 45.0,
        "ai_decision": "reject", "human_action": "reject",
        "status": "rejected", "retro_turns": 2}},
    {"brief": {"category": "小风扇"}, "archive": None},          # 未建档 → 过滤
    {"brief": {"category": "保温杯"}, "archive": {
        "proposal": "大容量运动保温杯", "predicted_score": None,
        "ai_decision": "approve", "human_action": "confirm",
        "status": "archived", "retro_turns": 0}},
]


class TestSelectAnalogs:
    def test_filters_unarchived_and_compacts(self):
        result = ledger.select_analogs(_ROWS, "小风扇")
        assert len(result) == 3  # archive=None 的行被过滤
        first = result[0]
        assert first["proposal"] == "库洛米旧款风扇"  # 同品类排前
        assert first["category"] == "小风扇"
        assert "brief" not in first and "archive" not in first  # compact

    def test_category_match_first_then_recency(self):
        result = ledger.select_analogs(_ROWS, "小风扇")
        assert [r["category"] for r in result] == ["小风扇", "香薰", "保温杯"]

    def test_substring_match(self):
        """互为子串算同品类（"小风扇" vs "桌面小风扇"）"""
        rows = [{"brief": {"category": "桌面小风扇"}, "archive": {
            "proposal": "x", "predicted_score": 1, "ai_decision": "approve",
            "human_action": "confirm", "status": "archived", "retro_turns": 0}}]
        assert ledger.select_analogs(rows, "小风扇")[0]["category"] == "桌面小风扇"

    def test_limit_and_empty(self):
        assert len(ledger.select_analogs(_ROWS, "小风扇", limit=2)) == 2
        assert ledger.select_analogs([], "小风扇") == []


class TestQueryAnalogs:
    def test_store_failure_returns_empty(self, monkeypatch):
        """台账故障绝不阻塞会议"""
        def _boom():
            raise RuntimeError("db locked")
        monkeypatch.setattr("app.store.list_all", _boom)
        assert ledger.query_analogs("小风扇") == []

    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr("app.store.list_all", lambda: _ROWS)
        result = ledger.query_analogs("小风扇")
        assert result[0]["proposal"] == "库洛米旧款风扇"


class TestFormatAnalogs:
    def test_key_fields_present(self):
        lines = ledger.format_analogs(ledger.select_analogs(_ROWS, "小风扇"))
        assert "库洛米旧款风扇" in lines[0]
        assert "45.0 分" in lines[0]
        assert "reject" in lines[0]
        assert "复盘 2 轮" in lines[0]

    def test_missing_score(self):
        lines = ledger.format_analogs(ledger.select_analogs(_ROWS, "保温杯", limit=1))
        assert "无评分" in lines[0]

    def test_empty(self):
        assert ledger.format_analogs([]) == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
