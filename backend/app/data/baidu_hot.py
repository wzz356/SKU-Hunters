"""百度热搜连接器 — 真实大众搜索趋势信号

数据源：百度热搜公开 JSON 接口（无需登录）
返回实时热搜榜（词条 + 热度值），代表大众搜索关注度，
与微博（社媒情绪）、B站（Z 世代 UGC）互为对照。

失败语义（连接器层统一约定）：
  - HTTP 错误 / 解析错误 / 业务状态非 success → 抛 ConnectorFetchError
  - 成功但榜为空 → 返回空列表（正常结果，不抛异常）
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from .errors import ConnectorFetchError


class BaiduHotConnector:
    """百度实时热搜连接器"""

    BASE_URL = "https://top.baidu.com/api/board"

    HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://top.baidu.com/",
    }

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def get_hot_search(self, limit: int = 30) -> list[dict[str, Any]]:
        """获取实时热搜榜

        Returns:
            [{'word': '词条', 'heat': 7654321, 'rank': 1, 'url': '...'}, ...]
            heat 为百度热度值（原始值，未归一化）
        """
        try:
            resp = httpx.get(
                self.BASE_URL,
                params={"platform": "wise", "tab": "realtime"},
                headers=self.HEADERS, timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ConnectorFetchError("baidu", f"请求/解析失败: {e}") from e

        if not data.get("success"):
            raise ConnectorFetchError("baidu", "业务状态异常: success=false")

        items = []
        rank = 0
        for card in data.get("data", {}).get("cards", []):
            for entry in card.get("content", []):
                word = (entry.get("word") or "").strip()
                if not word:
                    continue
                rank += 1
                items.append({
                    "word": word,
                    "heat": int(entry.get("hotScore", 0) or 0),
                    "rank": rank,
                    "url": entry.get("url") or f"https://www.baidu.com/s?wd={word}",
                })
                if rank >= limit:
                    return items
        return items
