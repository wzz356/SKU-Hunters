"""小红书公开数据接入 — 存储层（SQLite）

独立于 committee.db 的 xhs.db，避免与 v2 企划流程 / 评审链路的数据耦合。
表：
  - xhs_notes           笔记主表（按 note_url 去重，隐私字段不入库）
  - xhs_ingestion_runs  每次导入的运行记录（关键词/时间/状态/数量）

安全边界：本层只存小红书公开内容数据；手机号、真实姓名、私信、登录凭证等
隐私字段在入库前被 ingestor 层剥离，store 层在 schema 上不做这些列。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

# app/xhs/store.py -> parents[2] = backend/
_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "xhs.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()

# 隐私字段：入库前必须剥离（ingestor 也做一层，这里 schema 兜底不建这些列）
PRIVACY_FIELD_NAMES = {
    "phone", "mobile", "tel", "real_name", "id_card", "idcard", "id_no",
    "password", "passwd", "pwd", "token", "access_token", "secret",
    "private_message", "dm", "chat", "login_credential", "cookie", "author_id",
}

XHS_NOTE_COLUMNS = [
    "id", "note_url", "title", "content", "publish_time",
    "likes", "collects", "comments", "views",
    "tags", "query_keyword", "captured_at", "source_type", "source_url",
    "created_at",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS xhs_notes (
    id            TEXT PRIMARY KEY,
    note_url      TEXT UNIQUE,
    title         TEXT,
    content       TEXT,
    publish_time  TEXT,
    likes         INTEGER,
    collects      INTEGER,
    comments      INTEGER,
    views         INTEGER,
    tags          TEXT,
    query_keyword TEXT,
    captured_at   TEXT,
    source_type   TEXT DEFAULT 'xhs',
    source_url    TEXT,
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_xhs_notes_keyword  ON xhs_notes(query_keyword);
CREATE INDEX IF NOT EXISTS idx_xhs_notes_pubtime  ON xhs_notes(publish_time);
CREATE INDEX IF NOT EXISTS idx_xhs_notes_likes    ON xhs_notes(likes);
CREATE INDEX IF NOT EXISTS idx_xhs_notes_tags     ON xhs_notes(tags);

CREATE TABLE IF NOT EXISTS xhs_ingestion_runs (
    run_id      TEXT PRIMARY KEY,
    keyword     TEXT,
    file_path   TEXT,
    status      TEXT,
    total       INTEGER,
    inserted    INTEGER,
    updated     INTEGER,
    skipped     INTEGER,
    invalid     INTEGER,
    started_at  TEXT,
    finished_at TEXT,
    message     TEXT
);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """返回指定库（或默认库）的连接。测试可传入临时路径实现隔离。"""
    path = str(db_path) if db_path is not None else str(_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init(conn)
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── xhs_notes ───────────────────────────────────────────────

def upsert_notes(conn: sqlite3.Connection, records: list[dict]) -> dict:
    """按 note_url 去重 upsert。records 已被 ingestor 清洗 + 隐私过滤。

    返回统计：{"inserted": n, "updated": n}
    """
    inserted = updated = 0
    for r in records:
        rec = {c: r.get(c) for c in XHS_NOTE_COLUMNS}
        rec["tags"] = _dump_tags(rec.get("tags"))
        rec.setdefault("created_at", _now())
        rec.setdefault("source_type", "xhs")
        existing = conn.execute(
            "SELECT note_url FROM xhs_notes WHERE note_url=?", (rec.get("note_url"),)
        ).fetchone()
        if existing is None:
            conn.execute(
                f"INSERT INTO xhs_notes({','.join(XHS_NOTE_COLUMNS)}) "
                f"VALUES({','.join('?' * len(XHS_NOTE_COLUMNS))})",
                [rec.get(c) for c in XHS_NOTE_COLUMNS],
            )
            inserted += 1
        else:
            sets = ",".join(f"{c}=?" for c in XHS_NOTE_COLUMNS if c != "note_url")
            vals = [rec.get(c) for c in XHS_NOTE_COLUMNS if c != "note_url"]
            conn.execute(
                f"UPDATE xhs_notes SET {sets} WHERE note_url=?",
                (*vals, rec.get("note_url")),
            )
            updated += 1
    conn.commit()
    return {"inserted": inserted, "updated": updated}


def _dump_tags(tags) -> str:
    if tags is None:
        return "[]"
    if isinstance(tags, str):
        return tags
    return json.dumps(tags, ensure_ascii=False)


def list_notes(conn: sqlite3.Connection, keyword: str | None = None,
               limit: int = 50, offset: int = 0) -> list[dict]:
    q = "SELECT * FROM xhs_notes"
    args: list = []
    if keyword:
        q += " WHERE query_keyword=?"
        args.append(keyword)
    q += " ORDER BY captured_at DESC, likes DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    return out


def count_notes(conn: sqlite3.Connection, keyword: str | None = None) -> int:
    if keyword:
        return conn.execute(
            "SELECT COUNT(*) c FROM xhs_notes WHERE query_keyword=?", (keyword,)
        ).fetchone()["c"]
    return conn.execute("SELECT COUNT(*) c FROM xhs_notes").fetchone()["c"]


# ── xhs_ingestion_runs ──────────────────────────────────────

def add_run(conn: sqlite3.Connection, run: dict) -> None:
    cols = ["run_id", "keyword", "file_path", "status", "total", "inserted",
            "updated", "skipped", "invalid", "started_at", "finished_at", "message"]
    conn.execute(
        f"INSERT INTO xhs_ingestion_runs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
        [run.get(c) for c in cols],
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM xhs_ingestion_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_all(conn: sqlite3.Connection) -> dict:
    """清空数据（供测试/重置用），不影响表结构。"""
    n1 = conn.execute("DELETE FROM xhs_notes").rowcount
    n2 = conn.execute("DELETE FROM xhs_ingestion_runs").rowcount
    conn.commit()
    return {"notes_cleared": n1, "runs_cleared": n2}
