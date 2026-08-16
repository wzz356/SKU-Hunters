"""小红书数据接入 — Pydantic 输出模型（契约）"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class XhsNote(BaseModel):
    id: str
    note_url: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    publish_time: Optional[str] = None
    likes: Optional[int] = None
    collects: Optional[int] = None
    comments: Optional[int] = None
    views: Optional[int] = None
    tags: list[str] = Field(default_factory=list)
    query_keyword: Optional[str] = None
    captured_at: Optional[str] = None
    source_type: str = "xhs"
    source_url: Optional[str] = None


class IngestRequest(BaseModel):
    """批量导入请求：paths 为本地文件绝对/相对路径列表。"""
    paths: list[str]
    keyword: Optional[str] = None


class IngestSummary(BaseModel):
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    invalid: int = 0
    total: int = 0


class IngestResult(BaseModel):
    summary: IngestSummary
    runs: list[dict[str, Any]] = Field(default_factory=list)


class Engagement(BaseModel):
    note_count: int
    likes: int = 0
    collects: int = 0
    comments: int = 0
    interactions: int = 0
    engagement_rate: Optional[float] = None
    basis: str
    views: Optional[int] = None
