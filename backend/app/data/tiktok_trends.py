"""TikTok Creative Center 连接器 — 海外社媒趋势信号（112 国口径）

数据源：TikTok Creative Center 公开热榜 JSON（广告主选品工具，免登录）
按国家代码拉取热门 hashtag 榜——对应题目考点「海外社媒情绪」与
「全球 112 国场景」的真实数据补位。

失败语义（连接器层统一约定）：
  - HTTP 错误 / 解析错误 / 业务码非 0 → 抛 ConnectorFetchError
  - 成功但榜为空 → 返回空列表（正常结果，不抛异常）
  - 国内网络访问受限时由聚合器记入 failed_sources（故障隔离），
    不影响微博/百度等国内源
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from .errors import ConnectorFetchError


class TiktokTrendsConnector:
    """TikTok Creative Center 热门 hashtag 连接器"""

    BASE_URL = "https://ads.tiktok.com/creative_radar_api/v1/popular_trend/hashtag/list"

    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://ads.tiktok.com/business/creativecenter/",
    }

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def get_trending_hashtags(
        self, country_code: str = "US", period: int = 7, limit: int = 20
    ) -> list[dict[str, Any]]:
        """获取指定国家的热门 hashtag 榜

        Args:
            country_code: 国家代码（US/JP/TH/ID…，对应 112 国市场）
            period: 统计窗口天数（7/30/120）
            limit: 返回条数

        Returns:
            [{'word': 'hashtag', 'heat': 视频播放量, 'rank': 1,
              'url': ..., 'country': 'US'}, ...]
        """
        try:
            resp = httpx.get(
                self.BASE_URL,
                params={"period": period, "country_code": country_code,
                        "page": 1, "limit": limit},
                headers=self.HEADERS, timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConnectorFetchError("tiktok", f"请求/解析失败: {type(e).__name__}") from e

        if data.get("code") != 0:
            raise ConnectorFetchError(
                "tiktok", f"业务状态异常: code={data.get('code')} msg={data.get('msg', '')[:80]}"
            )

        items = []
        for i, entry in enumerate(data.get("data", {}).get("list", [])[:limit]):
            word = (entry.get("hashtag_name") or "").strip()
            if not word:
                continue
            items.append({
                "word": word,
                "heat": entry.get("video_views"),
                "rank": i + 1,
                "url": f"https://ads.tiktok.com/business/creativecenter/hashtag/{word}",
                "country": country_code,
            })
        return items

    # 与微博/百度连接器对齐的接口名，聚合器统一调用
    def get_hot_search(self, limit: int = 20) -> list[dict[str, Any]]:
        """默认拉美国榜（聚合器 fetch_all 用）"""
        return self.get_trending_hashtags(country_code="US", limit=limit)
