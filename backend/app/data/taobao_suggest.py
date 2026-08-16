"""淘宝联想词连接器 — 真实消费者搜索需求信号

数据源：淘宝官方搜索联想接口（公开、无需登录）
返回用户在淘宝真实输入的关联搜索词及热度权重，
是消费者真实购买意图的直接信号。
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

import httpx


class TaobaoSuggestConnector:
    """淘宝搜索联想词连接器"""

    BASE_URL = "https://suggest.taobao.com/sug"

    # 商品形态信号词（analyze_demand 与真 Agent 共用，单一来源）
    FORM_KEYWORDS: ClassVar[list[str]] = [
        "娃衣", "公仔", "挂件", "盲盒", "毛绒", "手办", "摆件",
        "收纳", "钥匙扣", "抱枕", "灯", "杯", "包", "衣服",
    ]

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def get_suggestions(self, keyword: str) -> list[dict[str, Any]]:
        """获取搜索联想词列表

        Args:
            keyword: 搜索关键词，如 'labubu'

        Returns:
            [{'query': '拉布布娃衣', 'heat': 100}, ...]
            heat 为 0-100 的相对热度权重
        """
        params = {"code": "utf-8", "q": keyword, "callback": "cb"}
        try:
            resp = httpx.get(self.BASE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []

        # 解析 JSONP: cb({"result":[["拉布布","100"],...]})
        match = re.search(r"cb\((.*)\)", resp.text, re.DOTALL)
        if not match:
            return []

        import json
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        return [
            {"query": item[0], "heat": int(item[1])}
            for item in data.get("result", [])
            if len(item) >= 2
        ]

    def analyze_demand(self, keyword: str) -> dict[str, Any]:
        """分析关键词的消费者需求信号

        Returns:
            {
                'keyword': 原始关键词,
                'demand_breadth': 关联需求数量,
                'avg_heat': 平均热度,
                'top_demands': 热度 Top5 需求词,
                'product_signals': 识别出的商品形态信号（如"娃衣/挂件/盲盒"）
            }
        """
        suggestions = self.get_suggestions(keyword)
        if not suggestions:
            return {
                "keyword": keyword,
                "demand_breadth": 0,
                "avg_heat": 0,
                "top_demands": [],
                "product_signals": [],
            }

        top = sorted(suggestions, key=lambda x: x["heat"], reverse=True)[:5]
        avg_heat = sum(s["heat"] for s in suggestions) / len(suggestions)

        # 从联想词中抽取商品形态信号
        signals = sorted({
            form
            for s in suggestions
            for form in self.FORM_KEYWORDS
            if form in s["query"]
        })

        return {
            "keyword": keyword,
            "demand_breadth": len(suggestions),
            "avg_heat": round(avg_heat, 1),
            "top_demands": top,
            "product_signals": signals,
        }
