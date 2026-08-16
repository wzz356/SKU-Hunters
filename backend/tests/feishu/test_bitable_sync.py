"""多维表格归档同步 — 字段映射与 fail-soft 行为（不碰真实飞书 API）"""

from __future__ import annotations

import feishu.bitable_sync as bs


def _sample_plan() -> dict:
    """与 pipeline 真实结构一致：brief 为 snake_case，plan_card 为 camelCase"""
    return {
        "plan_id": "plan_20260812_ab12",
        "brief": {
            "theme": "2027夏季户外生活系列",
            "category": "小风扇",
            "market": "中国大陆",
            "audience": "通勤白领",
            "price_range": [39, 99],
            "cost_limit": 25,
            "ip_strategy": ["三丽鸥"],
            "launch_window": "2027.04",
            "goals": [],
        },
        "plan_card": {
            "name": "云朵便携风扇",
            "concept": "像云朵一样轻的桌面风扇",
            "pricing": {"price": "59 元", "reason": "卡位价格带腰部"},
            "schedule": [
                {"time": "2027.02", "action": "打样"},
                {"time": "2027.04", "action": "首发"},
            ],
            "opportunityId": "opp_1",
            "source": "fixture",
        },
        "status": "archived",
        "archived_at": "2026-08-12T10:30:00+00:00",
    }


def test_build_fields_mapping():
    """snake brief + camel card → 多维表格字段，嵌套对象正确拍平"""
    fields = bs.build_fields(_sample_plan())

    assert fields["plan_id"] == "plan_20260812_ab12"
    assert fields["theme"] == "2027夏季户外生活系列"
    assert fields["category"] == "小风扇"
    assert fields["price_range"] == "39-99"
    assert fields["ip_strategy"] == "三丽鸥"
    assert fields["launch_window"] == "2027.04"
    assert fields["concept"] == "像云朵一样轻的桌面风扇"
    assert fields["pricing_price"] == "59 元"
    assert fields["pricing_reason"] == "卡位价格带腰部"
    assert fields["schedule"] == "2027.02 打样\n2027.04 首发"
    assert fields["status"] == "archived"
    assert fields["source_plan_id"] == ""  # 原创企划为空
    assert isinstance(fields["archived_at"], int)  # 毫秒时间戳


def test_build_fields_tolerates_missing_card():
    """plan_card 为空（异常情况）时不抛异常，卡片字段留空"""
    plan = _sample_plan()
    plan["plan_card"] = None
    plan["archived_at"] = "not-a-date"

    fields = bs.build_fields(plan)
    assert fields["concept"] == ""
    assert fields["pricing_price"] == ""
    assert "archived_at" not in fields  # 非法日期不写入


def test_sync_skipped_when_not_configured(monkeypatch):
    """未配置多维表格参数时 fail-soft 跳过，不抛异常"""
    monkeypatch.setattr(bs, "_syncer", None)
    monkeypatch.delenv("FEISHU_BITABLE_APP_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_BITABLE_TABLE_ID", raising=False)

    assert bs.sync_plan_to_bitable(_sample_plan()) is False


def test_sync_failure_does_not_raise(monkeypatch):
    """飞书 API 报错时 fail-soft：返回 False，不向上抛"""

    class _BrokenSyncer:
        def ensure_fields(self):
            raise RuntimeError("网络错误")

        def create_record(self, plan):
            raise AssertionError("不应走到这一步")

    monkeypatch.setattr(bs, "_get_syncer", lambda: _BrokenSyncer())
    assert bs.sync_plan_to_bitable(_sample_plan()) is False


def test_archive_card_content():
    """归档卡片：从 camelCase plan_card 提取摘要，字段齐全"""
    from feishu.notify import build_archive_card

    plan = _sample_plan()
    plan["plan_card"].update({
        "name": "云朵便携风扇",
        "costCheck": {"passed": True, "price": 59, "costLimit": 25, "margin": 0.58},
    })
    card = build_archive_card(plan, "http://localhost:5173")

    assert card["header"]["title"]["content"] == "📦 企划案已归档"
    texts = [e.get("text", {}).get("content", "") for e in card["elements"] if e["tag"] == "div"]
    body = "\n".join(texts)
    assert "云朵便携风扇" in body
    assert "59 元" in body
    assert "2027.02 打样" in body
    assert "✅ 通过" in body and "58%" in body
    button = card["elements"][-1]["actions"][0]
    assert button["url"].endswith("/tasks/plan_20260812_ab12")
