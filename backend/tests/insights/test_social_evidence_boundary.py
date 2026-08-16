"""社媒证据 JSON 边界防护测试 — 缺失字段不 KeyError，跳过或补默认值"""

from __future__ import annotations

import json

from app.insights.loaders.social_evidence import SocialEvidenceLoader


def _loader(tmp_path, data: dict) -> SocialEvidenceLoader:
    path = tmp_path / "test_topic.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return SocialEvidenceLoader(root=tmp_path)


def test_missing_trend_signal_name_and_metric(tmp_path):
    """缺 name/metric 的趋势信号被跳过，不 KeyError"""
    data = {
        "trend_signals": [
            {"name": "正常信号", "metric": "热度 80", "period": "近7天"},
            {"metric": "热度 60", "period": "近7天"},  # 缺 name
            {"name": "缺 metric", "period": "近7天"},  # 缺 metric
        ]
    }
    tr = _loader(tmp_path, data).to_trend_radar("test_topic")
    assert len(tr["signals"]) == 1
    assert tr["signals"][0]["name"] == "正常信号"
    assert any("跳过" in log for log in tr["processLog"])


def test_missing_pain_point_text_and_count(tmp_path):
    """缺 text 的痛点被跳过；缺 count 用默认 0"""
    data = {
        "consumer_voice": {
            "pain_points": [
                {"text": "太重了", "count": 12},
                {"count": 5},  # 缺 text → 跳过
            ],
            "scenes": [],
            "quotes": [],
        }
    }
    cv = _loader(tmp_path, data).to_consumer_voice("test_topic")
    assert len(cv["painPoints"]) == 1
    assert cv["painPoints"][0]["text"] == "太重了"
    assert cv["painPoints"][0]["count"] == 12


def test_missing_scene(tmp_path):
    """缺 scene 的场景被跳过"""
    data = {
        "consumer_voice": {
            "pain_points": [],
            "scenes": [
                {"scene": "通勤", "weight": "高"},
                {"weight": "中"},  # 缺 scene → 跳过
            ],
            "quotes": [],
        }
    }
    cv = _loader(tmp_path, data).to_consumer_voice("test_topic")
    assert len(cv["scenes"]) == 1
    assert cv["scenes"][0]["name"] == "通勤"


def test_missing_product_name_and_price(tmp_path):
    """缺 name 的竞品被跳过；缺 price 用默认 0"""
    data = {
        "competitive_map": {
            "products": [
                {"name": "小风扇", "price": 49},
                {"price": 99},  # 缺 name → 跳过
            ],
            "gap_zone": "",
            "price_bands": [],
        }
    }
    cm = _loader(tmp_path, data).to_competitive_map("test_topic")
    assert len(cm["products"]) == 1
    assert cm["products"][0]["name"] == "小风扇"


def test_empty_lists(tmp_path):
    """空列表不崩溃，返回空结构"""
    data = {"trend_signals": [], "competitive_map": {"products": []}}
    loader = _loader(tmp_path, data)
    assert loader.to_trend_radar("test_topic")["signals"] == []
    assert loader.to_competitive_map("test_topic")["products"] == []


def test_missing_structure(tmp_path):
    """JSON 结构整体缺失不崩溃，返回空结构"""
    data = {}  # 无任何顶层键
    loader = _loader(tmp_path, data)
    bundle = loader.get_insight_bundle("test_topic")
    assert bundle["trendRadar"]["signals"] == []
    assert bundle["consumerVoice"]["painPoints"] == []
    assert bundle["competitiveMap"]["products"] == []
