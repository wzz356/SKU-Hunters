"""B站连接器 — 真实 UGC 趋势信号（从旧本地趋势官迁移升级）

数据源：B站公开 API
- 热门视频榜: 全站真实热门内容
- 搜索接口: 关键词相关视频的播放/互动数据

B站是 Z 世代浓度最高的中文内容平台，
其数据对名创优品核心客群（18-25岁）的趋势判断价值极高。

失败语义（重要，沿用旧趋势官约定）：
  - HTTP 错误 / 解析错误 / 业务状态码非 0 → 抛 ConnectorFetchError
  - 查询成功但零命中 → 返回空列表（正常结果，不抛异常）
  - search_keyword 逐分区容错：部分分区失败时降级运行并在返回中
    携带 scanned_partitions / failed_partitions；全部分区失败时
    抛 ConnectorFetchError（故障，不是零命中）
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from .errors import ConnectorFetchError


class BilibiliConnector:
    """B站趋势数据连接器"""

    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com",
    }

    # 与潮玩/IP消费最相关的分区
    RANKING_PARTITIONS: ClassVar[dict[int, str]] = {
        160: "生活",
        155: "时尚",
        1: "动画",
        4: "游戏",
        119: "鬼畜",
    }

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    @staticmethod
    def _parse_video_list(data: dict) -> list[dict[str, Any]]:
        """把排行榜/热门接口的原始条目解析为统一视频结构"""
        return [
            {
                "title": item.get("title", ""),
                "bvid": item.get("bvid", ""),
                "view": item.get("stat", {}).get("view", 0),
                "like": item.get("stat", {}).get("like", 0),
                "danmaku": item.get("stat", {}).get("danmaku", 0),
                "tname": item.get("tname", ""),
                "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
            }
            for item in data.get("data", {}).get("list", [])
        ]

    def _get_json(self, url: str, params: dict, context: str) -> dict:
        """统一请求与校验：任何失败都抛 ConnectorFetchError，绝不返回空值。

        Raises:
            ConnectorFetchError: HTTP 错误 / JSON 解析失败 / 业务状态码非 0
        """
        try:
            resp = httpx.get(
                url, params=params, headers=self.HEADERS, timeout=self.timeout
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ConnectorFetchError("bilibili", f"{context} 请求失败: {e}") from e

        try:
            data = resp.json()
        except ValueError as e:
            raise ConnectorFetchError("bilibili", f"{context} 响应非 JSON") from e

        code = data.get("code")
        if code != 0:
            raise ConnectorFetchError(
                "bilibili",
                f"{context} 业务错误: code={code}, message={data.get('message', '')}",
            )
        return data

    def get_popular_videos(
        self, page: int = 1, page_size: int = 20
    ) -> list[dict[str, Any]]:
        """获取全站热门视频（真实榜单数据）

        Raises:
            ConnectorFetchError: 请求失败 / 解析失败 / 业务错误
        """
        url = "https://api.bilibili.com/x/web-interface/popular"
        params = {"ps": page_size, "pn": page}
        data = self._get_json(url, params, f"全站热门(page={page})")
        return self._parse_video_list(data)

    def get_ranking_videos(self, rid: int) -> list[dict[str, Any]]:
        """获取分区排行榜（真实榜单数据，动态更新）

        Raises:
            ConnectorFetchError: 请求失败 / 解析失败 / 业务错误（如 -352 风控）
        """
        url = "https://api.bilibili.com/x/web-interface/ranking/v2"
        params = {"rid": rid, "type": "all"}
        partition = self.RANKING_PARTITIONS.get(rid, str(rid))
        data = self._get_json(url, params, f"分区榜[{partition}]")
        return self._parse_video_list(data)

    def search_keyword(self, keyword: str) -> dict[str, Any]:
        """关键词在分区热门内容中的曝光信号

        策略：扫描生活/时尚/动画/游戏/鬼畜五个分区的实时排行榜，
        统计提及关键词的视频数与播放量。
        分区榜比全站热门对 IP 级趋势更敏感。

        Returns:
            除原有统计字段外，还包含：
              - scanned_partitions: 采集成功的分区名列表
              - failed_partitions:  采集失败的分区名列表（降级标记）

        Raises:
            ConnectorFetchError: 全部分区均采集失败（无法产出任何有效扫描）
        """
        all_videos: list[dict[str, Any]] = []
        scanned_partitions: list[str] = []
        failed_partitions: list[str] = []
        failure_reasons: list[str] = []

        for rid, partition_name in self.RANKING_PARTITIONS.items():
            try:
                videos = self.get_ranking_videos(rid)
                all_videos.extend(videos)
                scanned_partitions.append(partition_name)
            except ConnectorFetchError as e:
                failed_partitions.append(partition_name)
                failure_reasons.append(str(e))

        if not scanned_partitions:
            # 全部分区失败：这是故障，不是零命中
            raise ConnectorFetchError(
                "bilibili",
                f"全部 {len(self.RANKING_PARTITIONS)} 个分区采集失败: "
                + "; ".join(failure_reasons),
            )

        kw = keyword.lower()
        matched = [
            v for v in all_videos
            if kw in v["title"].lower() or kw in v["tname"].lower()
        ]
        total_views = sum(v["view"] for v in matched)

        return {
            "keyword": keyword,
            "scanned_videos": len(all_videos),
            "total_results": len(matched),
            "total_views": total_views,
            "avg_views": round(total_views / max(len(matched), 1), 0),
            "top_videos": sorted(matched, key=lambda x: x["view"], reverse=True)[:5],
            "scanned_partitions": scanned_partitions,
            "failed_partitions": failed_partitions,
        }
