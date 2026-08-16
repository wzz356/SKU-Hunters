"""Base 数据统一契约 — 跨平台采集记录的归一化视图

BaseRecord 是 Agent 消费的唯一数据形状。四个时间/版本字段严格区分：
- raw_value：原始采集值（未归一化，保留现场）
- snapshot_id：数据快照标识（同一业务对象的不同数据版本）
- record_date：业务日期（数据描述的事实发生时间，YYYY-MM-DD）
- ingested_at：入库时间（数据进入系统的时间，ISO8601）

as_of / snapshot 查询以 record_date / snapshot_id 为界，防止学习官读取未来数据。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BasePlatform(str, Enum):
    """来源平台（归一化枚举）"""

    GOOGLE_TRENDS = "google_trends"
    BILIBILI = "bilibili"
    XIAOHONGSHU = "xiaohongshu"
    TIKTOK = "tiktok"
    TAOBAO = "taobao"
    WEIBO = "weibo"
    BAIDU = "baidu"
    FEISHU = "feishu"
    OTHER = "other"


class BaseRecord(BaseModel):
    """跨平台归一化记录"""

    record_id: str = Field(..., description="记录唯一标识")
    keyword: str = Field(..., min_length=1, description="关键词/搜索词")
    platform: BasePlatform = Field(..., description="来源平台（归一化枚举）")
    category: str = Field(default="", description="品类")
    summary: str = Field(default="", description="内容摘要")
    heat_index: float | None = Field(default=None, ge=0, le=100, description="归一化热度指数（0-100）")
    interaction: float | None = Field(default=None, ge=0, description="互动量")
    brand: str | None = Field(default=None, description="品牌")
    price_range: str | None = Field(default=None, description="价格带")
    record_date: str = Field(..., description="业务日期（YYYY-MM-DD）")
    source_url: str | None = Field(default=None, description="来源链接；缺失不伪造")
    snapshot_id: str = Field(..., description="快照标识")
    ingested_at: str = Field(..., description="入库时间（ISO8601）")
    raw_value: dict[str, Any] | None = Field(default=None, description="原始采集值（未归一化）")

    @field_validator("record_date")
    @classmethod
    def _valid_record_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"record_date 必须为 YYYY-MM-DD，收到 {v!r}") from e
        return v

    @field_validator("ingested_at")
    @classmethod
    def _valid_ingested_at(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"ingested_at 必须为 ISO8601，收到 {v!r}") from e
        return v

    @field_validator("source_url")
    @classmethod
    def _valid_source_url(cls, v: str | None) -> str | None:
        """缺失/空 → None（不伪造链接）；非 http(s) → None（无效链接不可点击）"""
        if v is None or v.strip() == "":
            return None
        if not v.startswith(("http://", "https://")):
            return None
        return v


class BaseRecordPage(BaseModel):
    """分页查询结果"""

    records: list[BaseRecord] = Field(default_factory=list, description="当前页记录")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, ge=1, description="页码（1 起）")
    page_size: int = Field(default=20, ge=1, le=200, description="每页大小")
    has_more: bool = Field(default=False, description="是否还有下一页")


class BaseQuery(BaseModel):
    """统一 Base 查询模型 — 集中承载 as_of / snapshot_id 时间与版本边界

    - as_of：业务日期上界（YYYY-MM-DD），过滤掉 record_date 晚于它的记录，防未来数据。
    - snapshot_id：快照锁定（复盘时间机器），锁定某一数据快照，忽略其他版本。
    所有查询（search / summary / distribution）的这两个边界参数统一走本模型校验。
    """

    keyword: str = Field(default="", description="关键词/搜索词（空 = 全部）")
    platform: BasePlatform | None = Field(default=None, description="平台过滤")
    category: str | None = Field(default=None, description="品类过滤")
    as_of: str | None = Field(default=None, description="业务日期上界（YYYY-MM-DD）")
    snapshot_id: str | None = Field(default=None, description="快照锁定")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)

    @field_validator("as_of")
    @classmethod
    def _valid_as_of(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError as e:
            raise ValueError(f"as_of 必须为 YYYY-MM-DD，收到 {v!r}") from e
        return v
