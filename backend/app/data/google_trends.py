"""Google Trends 连接器 — 真实趋势数据接入

使用 pytrends 抓取 Google Trends 真实数据：
- interest_over_time: 关键词搜索热度时序
- related_queries: 关联查询（上升最快的真实用户搜索）
- trending_searches: 各地区实时热搜
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
from pytrends.request import TrendReq


class GoogleTrendsConnector:
    """Google Trends 真实数据连接器"""

    def __init__(self, hl: str = "en-US", tz: int = 360, retries: int = 3):
        self.hl = hl
        self.tz = tz
        self.retries = retries
        self._client: TrendReq | None = None

    @property
    def client(self) -> TrendReq:
        if self._client is None:
            self._client = TrendReq(hl=self.hl, tz=self.tz, timeout=(10, 30))
        return self._client

    def _with_retry(self, fn, *args, **kwargs):
        """带重试的请求封装，Google Trends 限流时指数退避"""
        last_err = None
        for attempt in range(self.retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — 限流/网络/解析异常统一重试
                last_err = e
                if attempt < self.retries - 1:
                    time.sleep(2 ** (attempt + 1))
        raise last_err

    def get_interest_over_time(
        self, keywords: list[str], timeframe: str = "today 3-m", geo: str = ""
    ) -> pd.DataFrame:
        """获取关键词搜索热度时序数据

        Args:
            keywords: 关键词列表（最多5个）
            timeframe: 时间范围，如 'today 3-m'（近3个月）
            geo: 地区代码，如 'TH'（泰国）、'JP'（日本），空为全球

        Returns:
            DataFrame，列为关键词，值为 0-100 的热度指数
        """
        self.client.build_payload(keywords, timeframe=timeframe, geo=geo)
        df = self._with_retry(self.client.interest_over_time)
        if "isPartial" in df.columns:
            df = df.drop(columns=["isPartial"])
        return df

    def get_related_queries(
        self, keyword: str, timeframe: str = "today 3-m", geo: str = ""
    ) -> dict[str, Any]:
        """获取关联查询 — 发现上升最快的真实用户搜索词

        Returns:
            {'top': DataFrame, 'rising': DataFrame}，rising 即"正在爆发"的搜索词
        """
        self.client.build_payload([keyword], timeframe=timeframe, geo=geo)
        result = self._with_retry(self.client.related_queries)
        return result.get(keyword, {"top": None, "rising": None})

    def get_trending_searches(self, region: str = "united_states") -> pd.DataFrame:
        """获取地区实时热搜榜

        Args:
            region: 如 'united_states', 'thailand', 'japan'
        """
        return self._with_retry(self.client.trending_searches, pn=region)

    def compute_heat_index(
        self, keyword: str, timeframe: str = "today 3-m", geo: str = ""
    ) -> dict[str, Any]:
        """计算趋势热度指数（Trend Heat Index）

        三维度综合：
        - level: 当前热度水平（近7天均值，0-100）
        - growth: 增长斜率（近7天 vs 前7天的变化率）
        - breadth: 关联查询广度（rising 查询数量）

        Returns:
            {'keyword': str, 'level': float, 'growth': float,
             'breadth': int, 'heat_index': float, 'lifecycle': str}
        """
        df = self.get_interest_over_time([keyword], timeframe=timeframe, geo=geo)
        if df.empty:
            # 查询无数据：指标返回 None（不是 0）并显式标记 no_data。
            # 0 是一个有效热度值，用 0 表示"无数据"会把缺失误报成正常结果。
            return {
                "keyword": keyword, "level": None, "growth": None,
                "breadth": None, "heat_index": None,
                "lifecycle": "unknown", "no_data": True,
            }

        series = df[keyword]
        recent = series.iloc[-7:].mean()
        previous = series.iloc[-14:-7].mean() if len(series) >= 14 else series.iloc[:-7].mean()
        growth = ((recent - previous) / max(previous, 1)) * 100

        related = self.get_related_queries(keyword, timeframe=timeframe, geo=geo)
        rising = related.get("rising")
        breadth = len(rising) if rising is not None and not rising.empty else 0

        # 加权合成：水平40% + 增长40% + 广度20%
        growth_score = min(max(growth, -50) + 50, 100)  # 归一化到 0-100
        breadth_score = min(breadth * 5, 100)
        heat_index = recent * 0.4 + growth_score * 0.4 + breadth_score * 0.2

        # 生命周期判断
        if growth > 20:
            lifecycle = "rising"
        elif growth > -10:
            lifecycle = "peak"
        else:
            lifecycle = "declining"

        return {
            "keyword": keyword,
            "level": round(float(recent), 1),
            "growth": round(float(growth), 1),
            "breadth": breadth,
            "heat_index": round(heat_index, 1),
            "lifecycle": lifecycle,
            "no_data": False,
        }