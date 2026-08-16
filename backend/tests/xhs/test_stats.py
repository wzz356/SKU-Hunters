"""小红书统计服务测试：关键词、互动、标签、趋势、Top、词频"""

from __future__ import annotations

from app.xhs import stats, store

BASE = {
    "id": None, "note_url": None, "title": "", "content": "", "publish_time": None,
    "likes": None, "collects": None, "comments": None, "views": None,
    "tags": [], "query_keyword": "", "captured_at": "2026-07-01T00:00:00Z",
    "source_type": "xhs", "source_url": None,
}


def _mk(url, **kv):
    d = dict(BASE)
    d["note_url"] = url
    d["id"] = url
    d.update(kv)
    return d


def _sample_db(tmp_path):
    db = str(tmp_path / "stats.db")
    conn = store.connect(db)
    store.upsert_notes(conn, [
        _mk("n1", title="夏日便携小风扇 静音", content="风扇 静音 便携 续航",
            likes=300, collects=100, comments=20, views=5000,
            tags=["小风扇", "便携"], query_keyword="小风扇",
            publish_time="2026-07-01"),
        _mk("n2", title="挂脖风扇 户外实测", content="挂脖 风扇 户外 通勤",
            likes=500, collects=200, comments=50, views=8000,
            tags=["挂脖风扇", "户外"], query_keyword="挂脖风扇",
            publish_time="2026-07-05"),
        _mk("n3", title="labubu 娃衣 摆拍", content="labubu 娃衣 潮玩",
            likes=800, collects=400, comments=100,
            tags=["labubu", "娃衣"], query_keyword="labubu",
            publish_time="2026-07-08"),
        # 无 views 的笔记，用于验证互动率降级
        _mk("n4", title="桌面摆件 治愈", content="桌面 摆件 治愈 好物",
            likes=100, collects=30, comments=5,
            tags=["桌面摆件", "治愈"], query_keyword="桌面摆件",
            publish_time="2026-07-08"),
    ])
    return conn


def test_keyword_counts(tmp_path):
    conn = _sample_db(tmp_path)
    counts = {c["keyword"]: c["count"] for c in stats.keyword_counts(conn)}
    assert counts["小风扇"] == 1
    assert counts["挂脖风扇"] == 1
    assert sum(counts.values()) == 4
    conn.close()


def test_engagement_with_views(tmp_path):
    conn = _sample_db(tmp_path)
    # 只看 n1（含 views=5000）→ 真实互动率 = interactions/views
    e = stats.engagement(conn, keyword="小风扇")
    assert e["note_count"] == 1
    assert e["likes"] == 300
    assert e["views"] == 5000
    assert e["basis"] == "views"
    assert e["engagement_rate"] == round((300 + 100 + 20) / 5000, 4)
    conn.close()


def test_engagement_overall_avg_per_note_when_no_views(tmp_path):
    conn = _sample_db(tmp_path)
    e = stats.engagement(conn)
    # n3/n4 无 views → basis 应为 avg_per_note（整体含无 views 笔记）
    assert e["interactions"] == (300 + 100 + 20) + (500 + 200 + 50) + (800 + 400 + 100) + (100 + 30 + 5)
    assert e["note_count"] == 4
    assert e["basis"] in ("avg_per_note", "views")
    conn.close()


def test_top_tags(tmp_path):
    conn = _sample_db(tmp_path)
    tags = stats.top_tags(conn, n=5)
    assert tags[0]["count"] == 1
    names = {t["tag"] for t in tags}
    assert "小风扇" in names
    assert "labubu" in names
    conn.close()


def test_publish_trend_day(tmp_path):
    conn = _sample_db(tmp_path)
    trend = stats.publish_trend(conn, "day")
    periods = {p["period"]: p["count"] for p in trend["points"]}
    assert periods["2026-07-01"] == 1
    assert periods["2026-07-05"] == 1
    assert periods["2026-07-08"] == 2
    conn.close()


def test_publish_trend_month(tmp_path):
    conn = _sample_db(tmp_path)
    trend = stats.publish_trend(conn, "month")
    assert trend["points"][0]["period"] == "2026-07"
    assert trend["points"][0]["count"] == 4
    conn.close()


def test_top_notes_likes(tmp_path):
    conn = _sample_db(tmp_path)
    top = stats.top_notes(conn, "likes", n=3)
    assert [t["note_url"] for t in top] == ["n3", "n2", "n1"]
    conn.close()


def test_top_notes_interactions(tmp_path):
    conn = _sample_db(tmp_path)
    top = stats.top_notes(conn, "interactions", n=1)
    # n3: 800+400+100=1300
    assert top[0]["note_url"] == "n3"
    assert top[0]["interactions"] == 1300
    conn.close()


def test_word_freq(tmp_path):
    conn = _sample_db(tmp_path)
    words = {w["word"]: w["count"] for w in stats.word_freq(conn, n=50)}
    assert "风扇" in words and words["风扇"] >= 2
    assert "labubu" in words
    assert "桌面" in words
    conn.close()
