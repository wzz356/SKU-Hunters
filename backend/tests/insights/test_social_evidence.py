"""社媒证据注入器 — 保温杯真实采集 JSON 的映射正确性"""

from __future__ import annotations

from app.insights.loaders.social_evidence import SocialEvidenceLoader, _first_number

L = SocialEvidenceLoader()


def test_first_number():
    assert _first_number("约80-120元") == 80.0
    assert _first_number("高频, 217条") == 217.0
    assert _first_number("无数字") == 0.0


def test_list_topics_has_baowenbei():
    assert any(t.startswith("保温杯") for t in L.list_topics())


def test_trend_radar_mapping():
    b = L.get_insight_bundle("保温杯")
    tr = b["trendRadar"]
    assert len(tr["signals"]) >= 5
    s = tr["signals"][0]
    assert {"name", "metric", "period", "domains", "opportunity"} <= set(s)
    assert len(tr["hotWords"]) >= 5


def test_consumer_voice_mapping():
    cv = L.get_insight_bundle("保温杯")["consumerVoice"]
    assert cv["painPoints"][0]["count"] >= 0
    assert len(cv["quotes"]) >= 5
    assert cv["summary"]


def test_competitive_map_has_images():
    cm = L.get_insight_bundle("保温杯")["competitiveMap"]
    assert len(cm["products"]) >= 5
    # 采集数据里竞品带图
    assert any(p["imageUrl"] for p in cm["products"])
    assert all(p["design"] >= 0 for p in cm["products"])


def test_trend_gallery_mapping():
    tg = L.get_insight_bundle("保温杯")["trendGallery"]
    assert len(tg["colors"]) >= 3
    assert len(tg["expressions"]) >= 1


def test_voice_format_consumer_voice(tmp_path):
    """全量原声（voice_of_user 格式）能转成消费者之声（自带夹具，不依赖采集文件）"""
    import json

    voice = {
        "note": "原声采集样本",
        "voice_of_user": [
            {"speaker": "上班族A", "source_note": "三联生活实验室", "raw_quote": "挂脖风扇卷头发太吓人了",
             "scenario": "通勤", "sentiment": "negative", "category": "安全焦虑"},
            {"speaker": "学生B", "source_note": "小红书评论", "raw_quote": "图书馆用噪音有点大",
             "scenario": "通勤", "sentiment": "negative", "category": "安全焦虑"},
            {"speaker": "宝妈C", "source_note": "微博", "raw_quote": "续航还行，出门一天够用",
             "scenario": "户外", "sentiment": "positive", "category": "续航"},
        ],
    }
    (tmp_path / "测试voice_2026-08-15.json").write_text(
        json.dumps(voice, ensure_ascii=False), encoding="utf-8")
    cv = SocialEvidenceLoader(root=tmp_path).to_consumer_voice("测试voice")
    assert len(cv["quotes"]) == 3
    # 原声带说话人+来源，可对账
    assert "三联生活实验室" in cv["quotes"][0]["source"]
    # 负面类别聚成痛点
    assert any("安全焦虑" in p["text"] for p in cv["painPoints"])
    # 场景有非零权重
    assert any(s["value"] > 0 for s in cv["scenes"])
