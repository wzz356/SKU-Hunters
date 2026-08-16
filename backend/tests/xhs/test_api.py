"""小红书 API 测试：导入、列表、统计、运行记录"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.xhs import store
from app.xhs.api import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 重定向默认库到临时文件，避免污染 backend/data/xhs.db
    monkeypatch.setattr(store, "_DB_PATH", tmp_path / "xhs.db")
    with TestClient(app) as c:
        yield c


def _seed(tmp_path):
    f = tmp_path / "seed.json"
    f.write_text(json.dumps({"notes": [
        {"note_url": "u1", "title": "风扇静音", "content": "便携 风扇 静音",
         "publish_time": "2026-07-01", "likes": 300, "collects": 100,
         "comments": 20, "tags": ["小风扇", "便携"], "query_keyword": "小风扇",
         "captured_at": "2026-07-02T00:00:00Z", "source_type": "xhs"},
        {"note_url": "u2", "title": "挂脖实测", "content": "挂脖 风扇 户外",
         "publish_time": "2026-07-05", "likes": 500, "collects": 200,
         "comments": 50, "tags": ["挂脖风扇"], "query_keyword": "挂脖风扇",
         "captured_at": "2026-07-06T00:00:00Z", "source_type": "xhs"},
    ]}, ensure_ascii=False), encoding="utf-8")
    return f


def test_ingest_endpoint(client, tmp_path):
    f = _seed(tmp_path)
    r = client.post("/api/v1/xhs/ingest", json={"paths": [str(f)]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["summary"]["inserted"] == 2
    assert len(data["runs"]) == 1


def test_ingest_empty_paths(client):
    r = client.post("/api/v1/xhs/ingest", json={"paths": []})
    assert r.status_code == 400


def test_list_notes(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/notes")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_notes_keyword_filter(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/notes", params={"keyword": "小风扇"})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["note_url"] == "u1"


def test_stats_endpoint(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_notes"] == 2
    assert len(body["keyword_counts"]) == 2
    assert len(body["top_notes"]["likes"]) == 2
    assert body["engagement"]["interactions"] == 300 + 100 + 20 + 500 + 200 + 50


def test_stats_keywords(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/keywords")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2


def test_stats_engagement(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/engagement")
    assert r.json()["note_count"] == 2
    assert r.json()["basis"] == "avg_per_note"  # 样例无 views


def test_stats_tags(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/tags")
    names = {t["tag"] for t in r.json()["items"]}
    assert "小风扇" in names


def test_stats_trend(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/trend")
    points = r.json()["points"]
    assert points[0]["period"] == "2026-07-01"


def test_stats_trend_invalid_granularity(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/trend", params={"granularity": "week"})
    assert r.status_code == 422


def test_stats_top(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/top", params={"metric": "likes", "n": 1})
    assert r.json()["items"][0]["note_url"] == "u2"


def test_stats_wordfreq(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/stats/wordfreq")
    words = {w["word"] for w in r.json()["items"]}
    assert "风扇" in words


def test_runs(client, tmp_path):
    client.post("/api/v1/xhs/ingest", json={"paths": [str(_seed(tmp_path))]})
    r = client.get("/api/v1/xhs/runs")
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["status"] == "success"


def test_get_note_404(client):
    r = client.get("/api/v1/xhs/notes/nope")
    assert r.status_code == 404
