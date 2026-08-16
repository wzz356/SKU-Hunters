"""SQLite 持久化 — 替代内存 dict，服务器重启数据不丢失"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "committee.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_local = threading.local()

def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(_DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn

def init():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id  TEXT PRIMARY KEY,
            brief       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            current_act TEXT DEFAULT 'brief_locked',
            status      TEXT DEFAULT 'running',
            live_feed   TEXT DEFAULT '[]',
            report      TEXT,
            archive     TEXT,
            digest_parts TEXT DEFAULT '[]',
            final_action TEXT,
            error       TEXT
        );
        CREATE TABLE IF NOT EXISTS retro_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(session_id),
            question   TEXT NOT NULL,
            answer     TEXT NOT NULL,
            timestamp  TEXT NOT NULL
        );
    """)
    c.commit()

def _json(v): return json.dumps(v, ensure_ascii=False) if v is not None else None
def _from(v): return json.loads(v) if v else v

def create(sid: str, brief: dict) -> None:
    init()
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute(
        "INSERT INTO sessions(session_id,brief,created_at,live_feed,digest_parts) VALUES(?,?,?,?,?)",
        (sid, _json(brief), now, "[]", "[]"),
    ).connection.commit()  # type: ignore[union-attr]

def create_or_update(sid: str, **kv):
    """终态落盘：UPSERT 全量写入（不先删父行，避免 retro_logs 外键悬空）"""
    if not kv: return
    init()
    now = kv.get("created_at") or datetime.now(timezone.utc).isoformat()
    _jsonify = lambda v: _json(v) if isinstance(v, (dict, list)) else v
    _conn().execute(
        """INSERT INTO sessions
           (session_id,brief,created_at,current_act,status,live_feed,report,archive,digest_parts,final_action,error)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(session_id) DO UPDATE SET
             brief=excluded.brief, created_at=excluded.created_at,
             current_act=excluded.current_act, status=excluded.status,
             live_feed=excluded.live_feed, report=excluded.report,
             archive=excluded.archive, digest_parts=excluded.digest_parts,
             final_action=excluded.final_action, error=excluded.error""",
        (sid,
         _jsonify(kv.get("brief", {})), now,
         kv.get("current_act", "act5_retro"), kv.get("status", "completed"),
         _jsonify(kv.get("live_feed", [])), _jsonify(kv.get("report")),
         _jsonify(kv.get("archive")), _jsonify(kv.get("digest_parts", [])),
         kv.get("final_action"), kv.get("error")),
    ).connection.commit()  # type: ignore[union-attr]

def update(sid: str, **kv):
    if not kv: return
    init()
    sets = ", ".join(f"{k}=?" for k in kv)
    vals = [_json(v) if isinstance(v, (dict, list)) else v for v in kv.values()]
    _conn().execute(
        f"UPDATE sessions SET {sets} WHERE session_id=?", (*vals, sid)
    ).connection.commit()  # type: ignore[union-attr]

def get(sid: str) -> dict | None:
    init()
    row = _conn().execute("SELECT * FROM sessions WHERE session_id=?", (sid,)).fetchone()
    if not row: return None
    d = dict(row)
    for k in ("live_feed", "report", "archive", "digest_parts"):
        d[k] = _from(d.get(k))
    d["brief"] = _from(d.get("brief")) or {}
    d["retro_logs"] = list_retro_logs(sid)
    # 运行时字段（不持久化）
    d["pending_gate"] = None
    d["gate_future"] = None
    return d

def list_all() -> list[dict]:
    init()
    rows = _conn().execute("SELECT session_id,brief,created_at,status,archive FROM sessions ORDER BY created_at DESC").fetchall()
    return [{**dict(r), "brief": _from(r["brief"]) or {},
             "archive": _from(r["archive"]),
             "retro_turns": (_from(r["archive"]) or {}).get("retro_turns", 0)}
            for r in rows]

def add_retro_log(sid: str, question: str, answer: str) -> dict:
    init()
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute(
        "INSERT INTO retro_logs(session_id,question,answer,timestamp) VALUES(?,?,?,?)",
        (sid, question, answer, now),
    ).connection.commit()  # type: ignore[union-attr]
    return {"question": question, "answer": answer, "timestamp": now}

def list_retro_logs(sid: str) -> list[dict]:
    init()
    rows = _conn().execute(
        "SELECT question,answer,timestamp FROM retro_logs WHERE session_id=? ORDER BY id", (sid,)
    ).fetchall()
    return [dict(r) for r in rows]

def close():
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None
