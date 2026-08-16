"""小红书导入器测试：清洗、去重、隐私过滤、批量导入"""

from __future__ import annotations

import json

from app.xhs import ingestor, store


def _write_json(path, data: list | dict):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# ── 清洗 / 隐私 ─────────────────────────────────────────────

def test_parse_int_invalid_returns_none():
    assert ingestor.parse_int("abc") is None
    assert ingestor.parse_int(None) is None
    assert ingestor.parse_int("") is None
    assert ingestor.parse_int("1,200") == 1200
    assert ingestor.parse_int(42) == 42
    assert ingestor.parse_int("  7  ") == 7


def test_sanitize_strips_privacy_text():
    rec = {"title": "联系我 13800138000", "content": "邮箱 test@example.com，证件 110101199001011234"}
    out = ingestor.sanitize_record(rec)
    assert "13800138000" not in (out["title"] or "")
    assert "test@example.com" not in (out["content"] or "")
    assert "110101199001011234" not in (out["content"] or "")


def test_privacy_field_rejected():
    rec = {"note_url": "u1", "title": "t", "phone": "13800138000", "password": "x"}
    assert ingestor._has_privacy_field(rec) is True
    assert ingestor._has_privacy_field({"note_url": "u1", "title": "t"}) is False


def test_sanitize_normalizes_fields():
    rec = {
        "url": "https://x.com/1", "题目": "标题", "点赞": "1,200", "收藏": "abc",
        "评论": 30, "标签": "a,b,c", "keyword": "测试",
    }
    out = ingestor.sanitize_record(rec)
    assert out["note_url"] == "https://x.com/1"
    assert out["likes"] == 1200
    assert out["collects"] is None
    assert out["comments"] == 30
    assert out["tags"] == ["a", "b", "c"]
    assert out["query_keyword"] == "测试"
    assert out["source_type"] == "xhs"


# ── 批量导入 / 去重 ─────────────────────────────────────────

def test_ingest_json_dedup(tmp_path):
    db = tmp_path / "xhs.db"
    f = _write_json(tmp_path / "a.json", {"notes": [
        {"note_url": "u1", "title": "新", "captured_at": "2026-07-02"},
        {"note_url": "u1", "title": "旧", "captured_at": "2026-07-01"},
        {"note_url": "u2", "title": "单独"},
    ]})
    res = ingestor.ingest_paths([str(f)], db_path=str(db))
    # 同批次 u1 两条去重为 1，保留 captured_at 最新
    assert res["summary"]["inserted"] == 2
    assert res["summary"]["skipped"] == 1
    assert res["runs"][0]["status"] == "success"

    conn = store.connect(str(db))
    items = store.list_notes(conn)
    assert len(items) == 2
    by_url = {i["note_url"]: i for i in items}
    assert by_url["u1"]["title"] == "新"  # 保留最新
    conn.close()


def test_ingest_csv_invalid_number(tmp_path):
    db = tmp_path / "xhs.db"
    csv_path = tmp_path / "b.csv"
    csv_path.write_text(
        "id,note_url,title,likes,collects,comments,query_keyword\n"
        "c1,u1,t1,abc,10,2,k1\n"
        "c2,u2,t2,5,,3,k1\n",
        encoding="utf-8-sig",
    )
    res = ingestor.ingest_paths([str(csv_path)], db_path=str(db))
    assert res["summary"]["inserted"] == 2

    conn = store.connect(str(db))
    items = {i["note_url"]: i for i in store.list_notes(conn)}
    assert items["u1"]["likes"] is None  # 非法数字归 None
    assert items["u2"]["collects"] is None
    assert items["u1"]["comments"] == 2
    conn.close()


def test_privacy_record_rejected_and_others_kept(tmp_path):
    db = tmp_path / "xhs.db"
    f = _write_json(tmp_path / "p.json", [
        {"note_url": "ok1", "title": "正常"},
        {"note_url": "bad1", "title": "x", "phone": "13800138000", "password": "y"},
    ])
    res = ingestor.ingest_paths([str(f)], db_path=str(db))
    # bad1 因含隐私字段被拒收
    assert res["summary"]["inserted"] == 1
    assert res["summary"]["invalid"] == 1
    assert res["runs"][0]["status"] == "partial"

    conn = store.connect(str(db))
    assert store.count_notes(conn) == 1
    conn.close()


def test_unsupported_format_fails_run(tmp_path):
    db = tmp_path / "xhs.db"
    txt = tmp_path / "c.txt"
    txt.write_text("x")
    res = ingestor.ingest_paths([str(txt)], db_path=str(db))
    assert res["runs"][0]["status"] == "failed"
    assert res["summary"]["inserted"] == 0
