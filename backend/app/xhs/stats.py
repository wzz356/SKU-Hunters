"""小红书数据统计服务（纯函数，接受 SQLite 连接）

提供：
  - 各关键词笔记数量
  - 互动量（点赞+收藏+评论）与互动率
  - 高频标签
  - 发布时间趋势
  - 点赞/收藏/评论 Top 笔记
  - 基础文本词频

互动率说明（诚实标注 basis）：
  - 若笔记含 views（曝光）字段：engagement_rate = 互动量 / 曝光量
  - 否则以"人均互动量 = 总互动量 / 笔记数"作为互动强度代理，
    并在返回中标注 basis="avg_per_note"，不伪装成真实曝光转化率。
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime

from app.xhs.ingestor import STOPWORDS

_WORD_PATTERN = re.compile(r"[a-zA-Z]+|[\u4e00-\u9fa5]{2,}")


def _iter_rows(conn: sqlite3.Connection, keyword: str | None = None):
    q = "SELECT * FROM xhs_notes"
    args: list = []
    if keyword:
        q += " WHERE query_keyword=?"
        args.append(keyword)
    for row in conn.execute(q, args).fetchall():
        yield row


def keyword_counts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT query_keyword AS keyword, COUNT(*) AS count "
        "FROM xhs_notes GROUP BY query_keyword ORDER BY count DESC, keyword"
    ).fetchall()
    return [dict(r) for r in rows]


def engagement(conn: sqlite3.Connection,
               keyword: str | None = None) -> dict:
    rows = _iter_rows(conn, keyword)
    n = likes = collects = comments = views = 0
    for r in rows:
        n += 1
        likes += r["likes"] or 0
        collects += r["collects"] or 0
        comments += r["comments"] or 0
        views += r["views"] or 0
    interactions = likes + collects + comments
    if n == 0:
        return {"note_count": 0, "likes": 0, "collects": 0, "comments": 0,
                "interactions": 0, "engagement_rate": None, "basis": "no_data",
                "views": None}
    if views > 0:
        rate = round(interactions / views, 4)
        basis = "views"
    else:
        rate = round(interactions / n, 2)
        basis = "avg_per_note"
    return {
        "note_count": n,
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "interactions": interactions,
        "engagement_rate": rate,
        "basis": basis,
        "views": views or None,
    }


def top_tags(conn: sqlite3.Connection, n: int = 20,
             keyword: str | None = None) -> list[dict]:
    counter: Counter = Counter()
    for r in _iter_rows(conn, keyword):
        for tag in json.loads(r["tags"] or "[]"):
            if tag:
                counter[tag] += 1
    return [{"tag": t, "count": c} for t, c in counter.most_common(n)]


def publish_trend(conn: sqlite3.Connection,
                  granularity: str = "day",
                  keyword: str | None = None) -> dict:
    """发布时间趋势。granularity: day / month。"""
    buckets: Counter = Counter()
    for r in _iter_rows(conn, keyword):
        t = r["publish_time"]
        if not t:
            continue
        key = _bucket_key(t, granularity)
        if key:
            buckets[key] += 1
    ordered = sorted(buckets.items())
    return {"granularity": granularity,
            "points": [{"period": k, "count": c} for k, c in ordered]}


def _bucket_key(t: str, granularity: str) -> str | None:
    s = str(t).strip()
    # 兼容 ISO / 常见日期格式，仅取前 10 位日期
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if granularity == "month":
            return f"{y:04d}-{mo:02d}"
        return f"{y:04d}-{mo:02d}-{d:02d}"
    # 时间戳
    try:
        ts = int(s)
        dt = datetime.fromtimestamp(ts)
    except (ValueError, TypeError, OSError):
        return None
    if granularity == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def top_notes(conn: sqlite3.Connection, metric: str = "likes",
              n: int = 5, keyword: str | None = None) -> list[dict]:
    if metric not in ("likes", "collects", "comments", "interactions"):
        raise ValueError(f"不支持的 metric: {metric}（likes/collects/comments/interactions）")
    q = "SELECT * FROM xhs_notes"
    args: list = []
    if keyword:
        q += " WHERE query_keyword=?"
        args.append(keyword)
    q += " ORDER BY {metric} DESC LIMIT ?"
    q = q.format(metric=metric if metric != "interactions" else "(likes+collects+comments)")
    args.append(n)
    rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["interactions"] = (r["likes"] or 0) + (r["collects"] or 0) + (r["comments"] or 0)
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    return out


def word_freq(conn: sqlite3.Connection, n: int = 30,
              keyword: str | None = None) -> list[dict]:
    counter: Counter = Counter()
    for r in _iter_rows(conn, keyword):
        text = f"{r['title'] or ''} {r['content'] or ''}"
        for token in _WORD_PATTERN.findall(text):
            t = token.lower()
            if t in STOPWORDS or len(t) < 2:
                continue
            counter[t] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(n)]


def full_stats(conn: sqlite3.Connection, keyword: str | None = None,
               top_n: int = 5, tag_n: int = 20, word_n: int = 30) -> dict:
    """一次聚合全部统计，供 /stats 端点使用。"""
    return {
        "keyword_counts": keyword_counts(conn),
        "engagement": engagement(conn, keyword),
        "top_tags": top_tags(conn, tag_n, keyword),
        "publish_trend": publish_trend(conn, "day", keyword),
        "top_notes": {
            m: top_notes(conn, m, top_n, keyword)
            for m in ("likes", "collects", "comments", "interactions")
        },
        "word_freq": word_freq(conn, word_n, keyword),
        "total_notes": store_count(conn, keyword),
    }


def store_count(conn: sqlite3.Connection, keyword: str | None = None) -> int:
    from app.xhs import store
    return store.count_notes(conn, keyword)
