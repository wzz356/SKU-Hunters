"""微博热搜连接器 — 真实社媒趋势信号

数据源：微博热搜公开接口（无需登录）
返回实时热搜榜（词条 + 热度值），是中文社媒情绪与话题趋势的
直接信号——对应 fixtures 里「社媒趋势」的真实数据源。

失败语义（连接器层统一约定）：
  - HTTP 错误 / 解析错误 / 业务状态非 ok → 抛 ConnectorFetchError
  - 成功但榜为空 → 返回空列表（正常结果，不抛异常）

注：小红书/抖音为登录墙 + 强反爬平台，不做不可靠抓取；
微博热搜是其社媒趋势功能的诚实替代源。
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from .errors import ConnectorFetchError


class WeiboHotConnector:
    """微博实时热搜连接器"""

    BASE_URL = "https://weibo.com/ajax/side/hotSearch"

    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://weibo.com/",
    }

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def get_hot_search(self, limit: int = 50) -> list[dict[str, Any]]:
        """获取实时热搜榜

        Returns:
            [{'word': '词条', 'heat': 1234567, 'rank': 1, 'url': '...'}, ...]
            heat 为微博热度值（原始值，未归一化）
        """
        try:
            resp = httpx.get(
                self.BASE_URL, headers=self.HEADERS, timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConnectorFetchError("weibo", f"请求/解析失败: {e}") from e

        if data.get("ok") != 1:
            raise ConnectorFetchError("weibo", f"业务状态异常: ok={data.get('ok')}")

        items = []
        for i, entry in enumerate(data.get("data", {}).get("realtime", [])[:limit]):
            word = entry.get("word", "").strip()
            if not word:
                continue
            items.append({
                "word": word,
                "heat": entry.get("num"),
                "rank": i + 1,
                "url": f"https://s.weibo.com/weibo?q=%23{word}%23",
            })
        return items
