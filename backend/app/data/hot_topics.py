"""热搜聚合器 — 多源真实趋势信号合并 + 关键词匹配

供 Agent / 脚本使用的工具层：一次调用拉取多个公开热搜源
（微博 / 百度 / 抖音 / 小红书 / TikTok），按演示关键词过滤出与本企划相关的真实话题。

故障隔离纪律（与连接器层约定一致）：
  - 单源失败不影响其他源（记入 failed_sources，绝不折叠为"零命中"）；
  - 全部失败 → 抛 ConnectorFetchError（故障，不是"没有相关热搜"）；
  - 关键词零命中 → 返回空 hits（正常结果，附 scanned_sources 供对账）。
"""

from __future__ import annotations

from typing import Any

from .baidu_hot import BaiduHotConnector
from .errors import ConnectorFetchError
from .tiktok_trends import TiktokTrendsConnector
from .uapi_hot import DouyinHotConnector, XiaohongshuHotConnector
from .weibo_hot import WeiboHotConnector

SOURCES = {
    "weibo": WeiboHotConnector,
    "baidu": BaiduHotConnector,
    # 经 UApiPro 聚合 API：名创主渠道 + 登录墙平台的合规替代采集
    "douyin": DouyinHotConnector,
    "xiaohongshu": XiaohongshuHotConnector,
    "tiktok": TiktokTrendsConnector,  # 海外社媒（112 国口径），国内网络受限时记入 failed_sources
}


def fetch_all(timeout: float = 10.0) -> dict[str, Any]:
    """拉取全部热搜源

    Returns:
        {
            'items': [{'source': 'weibo', 'word': ..., 'heat': ..., 'rank': ...}, ...],
            'scanned_sources': ['weibo', 'baidu'],
            'failed_sources': [{'source': 'x', 'detail': '...'}],
        }
    Raises:
        ConnectorFetchError: 全部源失败（故障 ≠ 零命中）
    """
    items: list[dict[str, Any]] = []
    scanned: list[str] = []
    failed: list[dict[str, str]] = []

    for name, cls in SOURCES.items():
        try:
            for entry in cls(timeout=timeout).get_hot_search():
                items.append({"source": name, **entry})
            scanned.append(name)
        except ConnectorFetchError as e:
            failed.append({"source": name, "detail": e.detail})

    if not scanned:
        detail = "; ".join(f"{f['source']}: {f['detail']}" for f in failed)
        raise ConnectorFetchError("hot_topics", f"全部热搜源失败: {detail}")

    return {"items": items, "scanned_sources": scanned, "failed_sources": failed}


def match_keywords(
    payload: dict[str, Any],
    keywords: list[str],
) -> dict[str, Any]:
    """按关键词过滤出相关话题（用于企划场景的真实信号抽样）

    Args:
        payload: fetch_all() 的返回
        keywords: 演示关键词，如 ['小风扇', '露营', '桌面', '治愈']

    Returns:
        {'hits': [...], 'scanned_sources': [...], 'failed_sources': [...],
         'keywords': [...]}
        零命中时 hits 为空列表——这是正常结果，不是故障。
    """
    hits = [
        item for item in payload["items"]
        if any(kw in item["word"] for kw in keywords)
    ]
    return {
        "hits": hits,
        "scanned_sources": payload["scanned_sources"],
        "failed_sources": payload["failed_sources"],
        "keywords": keywords,
    }
