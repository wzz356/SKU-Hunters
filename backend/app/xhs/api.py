"""小红书数据接入 — API 路由

端点（均挂 /api/v1/xhs，与 v2 企划 / 评审链路隔离）：
  POST /api/v1/xhs/ingest                批量导入本地 JSON/CSV 文件
  GET  /api/v1/xhs/notes                 笔记列表（可按关键词过滤/分页）
  GET  /api/v1/xhs/stats                 全量统计汇总
  GET  /api/v1/xhs/stats/keywords        各关键词笔记数量
  GET  /api/v1/xhs/stats/engagement      互动量与互动率
  GET  /api/v1/xhs/stats/tags            高频标签
  GET  /api/v1/xhs/stats/trend           发布时间趋势（day/month）
  GET  /api/v1/xhs/stats/top             Top 笔记（likes/collects/comments/interactions）
  GET  /api/v1/xhs/stats/wordfreq        基础文本词频
  GET  /api/v1/xhs/runs                  导入运行记录

说明：本阶段仅提供本地导入链路 + 统计接口，不接任何实时采集。
数据看板若要消费，按 docs/xhs/小红书数据接入说明.md 的接入方式对接。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.xhs import ingestor, stats, store
from app.xhs.schemas import IngestRequest, IngestResult

router = APIRouter(prefix="/api/v1/xhs", tags=["xhs"])


@router.post("/ingest", response_model=IngestResult)
def ingest(payload: IngestRequest):
    if not payload.paths:
        raise HTTPException(400, detail={"error": {"code": "EMPTY_PATHS", "message": "paths 不能为空"}})
    result = ingestor.ingest_paths(payload.paths, keyword=payload.keyword)
    return result


@router.get("/notes")
def list_notes(keyword: Optional[str] = None,
               limit: int = Query(50, ge=1, le=500),
               offset: int = Query(0, ge=0)):
    conn = store.connect()
    try:
        total = store.count_notes(conn, keyword)
        items = store.list_notes(conn, keyword, limit, offset)
        return {"total": total, "limit": limit, "offset": offset, "items": items}
    finally:
        conn.close()


@router.get("/notes/{note_id}")
def get_note(note_id: str):
    conn = store.connect()
    try:
        row = conn.execute("SELECT * FROM xhs_notes WHERE id=?", (note_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, detail={"error": {"code": "NOTE_NOT_FOUND", "message": note_id}})
    d = dict(row)
    d["tags"] = __import__("json").loads(d.get("tags") or "[]")
    return d


@router.get("/stats")
def full_stats(keyword: Optional[str] = None):
    conn = store.connect()
    try:
        return stats.full_stats(conn, keyword)
    finally:
        conn.close()


@router.get("/stats/keywords")
def keyword_counts():
    conn = store.connect()
    try:
        return {"items": stats.keyword_counts(conn)}
    finally:
        conn.close()


@router.get("/stats/engagement")
def engagement(keyword: Optional[str] = None):
    conn = store.connect()
    try:
        return stats.engagement(conn, keyword)
    finally:
        conn.close()


@router.get("/stats/tags")
def top_tags(n: int = Query(20, ge=1, le=100), keyword: Optional[str] = None):
    conn = store.connect()
    try:
        return {"items": stats.top_tags(conn, n, keyword)}
    finally:
        conn.close()


@router.get("/stats/trend")
def publish_trend(granularity: str = Query("day", pattern="^(day|month)$"),
                  keyword: Optional[str] = None):
    conn = store.connect()
    try:
        return stats.publish_trend(conn, granularity, keyword)
    finally:
        conn.close()


@router.get("/stats/top")
def top_notes(metric: str = Query("likes", pattern="^(likes|collects|comments|interactions)$"),
              n: int = Query(5, ge=1, le=50), keyword: Optional[str] = None):
    conn = store.connect()
    try:
        return {"metric": metric, "items": stats.top_notes(conn, metric, n, keyword)}
    finally:
        conn.close()


@router.get("/stats/wordfreq")
def word_freq(n: int = Query(30, ge=1, le=200), keyword: Optional[str] = None):
    conn = store.connect()
    try:
        return {"items": stats.word_freq(conn, n, keyword)}
    finally:
        conn.close()


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=200)):
    conn = store.connect()
    try:
        return {"items": store.list_runs(conn, limit)}
    finally:
        conn.close()
