"""UApiPro 热榜连接器 — 40+ 平台实时榜 + 时光机历史回溯 + 关键词历史检索

数据源：UApiPro 全网热榜聚合 API（https://uapis.cn，免费，免 key 可调）。
一个端点覆盖三种模式：

  实时榜    GET /api/v1/misc/hotboard?type={platform}
  时光机    同上 + time={毫秒时间戳} → 返回离该时间最近的历史快照
  历史检索  同上 + keyword={词} + time_start/time_end={毫秒} → 命中条目流

价值：补齐两个关键缺口——
  ① 时间纵深：历史快照可回溯，增速从"冻结数字"变"实测环比"
  ② 平台覆盖：抖音（名创主渠道）、小红书（登录墙平台的诚实替代抓取）
     都在其 40+ 平台列表里

失败语义（连接器层统一约定）：
  - HTTP 错误 / 解析错误 / 业务错误（返回 code+message）→ 抛 ConnectorFetchError
  - 成功但榜为空 / 检索零命中 → 返回空列表（正常结果，不抛异常）

注：免费层免 key 即调即用；UAPIPRO_API_KEY 目前不发送，
未来触发限流时再按官方文档接入。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import httpx

from .errors import ConnectorFetchError

_CST = timezone(timedelta(hours=8))


class UapiHotConnector:
    """UApiPro 热榜连接器（platform 指定平台，子类可预设）"""

    BASE_URL = "https://uapis.cn/api/v1/misc/hotboard"
    PLATFORM: str = ""  # 子类预设平台名；空则必须调用时显式传

    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }

    def __init__(self, platform: str | None = None, timeout: float = 10.0):
        self.platform = platform or self.PLATFORM
        self.timeout = timeout

    # ── 内部：统一请求与业务错误校验 ──────────────────────

    def _get(self, params: dict[str, Any], context: str) -> dict[str, Any]:
        source = f"uapi:{self.platform}"
        try:
            resp = httpx.get(
                self.BASE_URL, params=params,
                headers=self.HEADERS, timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConnectorFetchError(source, f"请求/解析失败: {type(e).__name__}") from e
        # 业务错误：{"code": "...", "message": "..."}（无 list/items 字段）
        if "code" in data and "list" not in data and "items" not in data:
            raise ConnectorFetchError(
                source, f"业务错误: {data.get('code')} {data.get('message', '')}"
            )
        return data

    def _require_platform(self) -> str:
        if not self.platform:
            raise ConnectorFetchError("uapi", "未指定平台（platform 必填）")
        return self.platform

    # ── ① 实时榜 / 时光机快照 ────────────────────────────

    def get_hot_board(self, time_ms: int | None = None) -> dict[str, Any]:
        """获取热榜：time_ms 为空 = 实时榜；传毫秒时间戳 = 时光机历史快照

        Returns:
            {"platform", "update_time", "snapshot_time",
             "items": [{"rank", "title", "hot_value", "url"}, ...]}
            榜为空时 items=[]（正常结果）
        """
        platform = self._require_platform()
        params: dict[str, Any] = {"type": platform}
        if time_ms is not None:
            params["time"] = time_ms
        data = self._get(params, "热榜")
        items = [
            {
                "rank": entry.get("index", 0),
                "title": entry.get("title", ""),
                "hot_value": entry.get("hot_value", ""),
                "url": entry.get("url", ""),
            }
            for entry in data.get("list", [])
            if entry.get("title")
        ]
        return {
            "platform": data.get("type", platform),
            "update_time": data.get("update_time", ""),
            "snapshot_time": data.get("snapshot_time"),
            "items": items,
        }

    # ── ② 关键词历史检索 ─────────────────────────────────

    def search_history(
        self, keyword: str, time_start_ms: int, time_end_ms: int
    ) -> dict[str, Any]:
        """在历史热榜快照中检索关键词（零命中是正常结果）

        Returns:
            {"platform", "keyword", "count",
             "items": [{"snapshot_ts", "rank", "title", "hot_value", "url"}, ...]}
        """
        platform = self._require_platform()
        data = self._get(
            {
                "type": platform,
                "keyword": keyword,
                "time_start": time_start_ms,
                "time_end": time_end_ms,
            },
            "历史检索",
        )
        return {
            "platform": data.get("type", platform),
            "keyword": data.get("keyword", keyword),
            "count": data.get("count", 0),
            "items": data.get("items", []),
        }

    # ── ③ 逐日命中序列（时间纵深的原料）───────────────────

    def daily_hits(self, keyword: str, days: int = 7, hour: int = 12) -> list[dict[str, Any]]:
        """回溯过去 N 天、每天 {hour} 点（北京时间）的快照，统计关键词命中

        每个平台每天一次请求，关键词匹配在本地完成（对 API 友好）。

        Returns:
            [{"date": "2026-08-08", "snapshot_time": ..., "hits": int,
              "best_rank": int | None}, ...] 按日期升序
        """
        today = datetime.now(_CST).date()
        series = []
        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)
            noon = datetime(day.year, day.month, day.day, hour, tzinfo=_CST)
            board = self.get_hot_board(time_ms=int(noon.timestamp() * 1000))
            matched = [i for i in board["items"] if keyword in i["title"]]
            series.append({
                "date": day.isoformat(),
                "snapshot_time": board["snapshot_time"],
                "hits": len(matched),
                "best_rank": min((i["rank"] for i in matched), default=None),
            })
        return series

    # ── 聚合器兼容接口（与 WeiboHotConnector 等同构）───────

    def get_hot_search(self, limit: int = 50) -> list[dict[str, Any]]:
        """实时榜，返回聚合器统一形状 [{'word','heat','rank','url'}]"""
        board = self.get_hot_board()
        return [
            {
                "word": i["title"],
                "heat": i["hot_value"],
                "rank": i["rank"],
                "url": i["url"],
            }
            for i in board["items"][:limit]
        ]


# ── 平台预设子类（注册进聚合器用）───────────────────────────


class DouyinHotConnector(UapiHotConnector):
    """抖音热榜 — 名创主渠道声量"""

    PLATFORM = "douyin"


class XiaohongshuHotConnector(UapiHotConnector):
    """小红书热榜 — 登录墙平台的合规替代采集（经聚合 API）"""

    PLATFORM = "xiaohongshu"
