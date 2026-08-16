"""Scoped Views — Agent 数据权限视图（只读）+ 独立写入端口

每个 View 持有受限查询端口（RestrictedQueryPort / BaseQueryPort），不持有完整
BaseDataAdapter；View 只暴露权限范围内的方法，且聚合方法一律翻页取全量（避免只统计
默认 page_size=20 的第一页）。
- 创意官（product_ideation）不注入任何数据视图，只接收三官 Artifact。
- LearningLedgerReadView 只读，写入走独立 RetroLedgerWriter（内存测试实现）。
- 权限范围（谁能看什么）见各 View docstring，并写入测试。

隔离边界说明：这是「应用层能力隔离」——View 依赖受限查询端口协议，公共接口不含
adapter 管理方法；但 Python 反射可绕过，非进程级安全边界。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.data.base_adapter import BaseQueryPort


class _ReadView:
    """只读 View 基类：持有受限查询端口（BaseQueryPort），不持有完整 adapter"""

    def __init__(self, port: BaseQueryPort):
        self._port = port

class TrendDataView(_ReadView):
    """趋势数据视图 — 权限：趋势信号 / 日期分布 / 热度 / 证据引用"""

    def search_trend_signals(self, keyword: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all(keyword, as_of=as_of, snapshot_id=snapshot_id)
        return [
            {"keyword": r.keyword, "platform": r.platform,
             "heat_index": r.heat_index, "record_date": r.record_date}
            for r in records
        ]

    def get_date_distribution(self, keyword: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        return self._port.get_date_distribution(keyword, as_of, snapshot_id)

    def compute_heat_index(self, keyword: str, as_of: str | None = None, snapshot_id: str | None = None) -> float | None:
        return self._port.compute_heat_index(keyword, as_of, snapshot_id)

    def build_evidence_refs(self, records: list[Any]) -> list[dict[str, str]]:
        return self._port.build_evidence_refs(records)

class ConsumerDataView(_ReadView):
    """消费者数据视图 — 权限：分类评论 / 搜索意图 / 证据引用"""

    def get_reviews_by_category(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        return [
            {"summary": r.summary, "platform": r.platform, "record_date": r.record_date}
            for r in records
        ]

    def get_search_intent(self, keyword: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all(keyword, platform="taobao", as_of=as_of, snapshot_id=snapshot_id)
        return [{"keyword": r.keyword, "summary": r.summary} for r in records]

    def get_category_signals(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, Any]:
        """按品类返回聚合信号 + 证据引用（不返回原始评论全文；source_url 缺失不伪造）"""
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        signals = [
            {"keyword": r.keyword, "summary": r.summary, "platform": r.platform,
             "heat_index": r.heat_index, "interaction": r.interaction}
            for r in records
        ]
        evidence = self._port.build_evidence_refs(records)
        return {"signals": signals, "evidence": evidence}

    def build_evidence_refs(self, records: list[Any]) -> list[dict[str, str]]:
        return self._port.build_evidence_refs(records)

class IPDataView(_ReadView):
    """IP 数据视图 — 权限：IP 提及 / 品牌 top20 / 联名案例 / 证据引用（无用户评论原文）"""

    def search_ip_mentions(self, keyword: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all(keyword, category="IP", as_of=as_of, snapshot_id=snapshot_id)
        return [
            {"keyword": r.keyword, "brand": r.brand, "heat_index": r.heat_index}
            for r in records
        ]

    def get_brand_top20(self, as_of: str | None = None, snapshot_id: str | None = None) -> list[tuple[str, float]]:
        records = self._port.search_all("", as_of=as_of, snapshot_id=snapshot_id)
        brand_heat: dict[str, float] = {}
        for r in records:
            if r.brand:
                brand_heat[r.brand] = brand_heat.get(r.brand, 0.0) + (r.heat_index or 0.0)
        return sorted(brand_heat.items(), key=lambda x: x[1], reverse=True)[:20]

    def get_hit_cases(self, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all("", category="IP", as_of=as_of, snapshot_id=snapshot_id)
        return [{"brand": r.brand, "summary": r.summary} for r in records if r.brand]

    def get_ip_signals(self, candidates: list[str] | None = None, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, Any]:
        """返回 IP 聚合信号 + 证据引用。

        只读取 IP 类型数据（category="IP"），不把普通品类热度伪装成 IP 授权结论；
        不返回原始评论全文；source_url 缺失不伪造。

        candidates 非空：只返回候选池中的 IP（按 brand 匹配）；
        candidates 为空/None：显式返回全库 Top IP（非隐含“空 keyword 不过滤”行为）。
        """
        records = self._port.search_all("", category="IP", as_of=as_of, snapshot_id=snapshot_id)
        if candidates:
            candidate_set = set(candidates)
            records = [r for r in records if r.brand in candidate_set]
        signals = [
            {"keyword": r.keyword, "brand": r.brand, "heat_index": r.heat_index,
             "summary": r.summary, "platform": r.platform, "record_date": r.record_date}
            for r in records
        ]
        evidence = self._port.build_evidence_refs(records)
        return {"signals": signals, "evidence": evidence}

    def build_evidence_refs(self, records: list[Any]) -> list[dict[str, str]]:
        return self._port.build_evidence_refs(records)

class BusinessSummaryView(_ReadView):
    """商业摘要视图 — 权限：品牌集中度 / 价格带分布 / 爆款（聚合结果，无原始评论）"""

    def get_brand_concentration(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, int]:
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        brand_count: dict[str, int] = {}
        for r in records:
            if r.brand:
                brand_count[r.brand] = brand_count.get(r.brand, 0) + 1
        return brand_count

    def get_price_band_distribution(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, int]:
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        bands: dict[str, int] = {}
        for r in records:
            if r.price_range:
                bands[r.price_range] = bands.get(r.price_range, 0) + 1
        return bands

    def get_hit_products(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        return [
            {"keyword": r.keyword, "brand": r.brand, "heat_index": r.heat_index}
            for r in records if r.heat_index is not None
        ]

class GTMMarketView(_ReadView):
    """GTM 市场视图 — 权限：品类分布 / 市场参照"""

    def get_category_distribution(self, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, int]:
        records = self._port.search_all("", as_of=as_of, snapshot_id=snapshot_id)
        cat_count: dict[str, int] = {}
        for r in records:
            cat_count[r.category] = cat_count.get(r.category, 0) + 1
        return cat_count

    def get_market_reference(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        return [
            {"keyword": r.keyword, "platform": r.platform, "heat_index": r.heat_index}
            for r in records
        ]

    def get_market_signals(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, Any]:
        """返回品类市场聚合信号 + 证据引用（不返回原始评论全文；source_url 缺失不伪造）"""
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        signals = [
            {"keyword": r.keyword, "platform": r.platform, "heat_index": r.heat_index,
             "record_date": r.record_date, "brand": r.brand}
            for r in records
        ]
        evidence = self._port.build_evidence_refs(records)
        return {"signals": signals, "evidence": evidence}

class LearningLedgerReadView(_ReadView):
    """学习台账只读视图 — 权限：决策记录 / 历史评分 / 结果信号（只读，不含写入方法）"""

    def get_decision_record(self, snapshot_id: str) -> dict[str, Any]:
        return self._port.get_summary(snapshot_id=snapshot_id)

    def get_historical_scores(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> dict[str, Any]:
        summary = self._port.get_summary(category=category, as_of=as_of, snapshot_id=snapshot_id)
        return {"category": category, "avg_heat_index": summary.get("avg_heat_index", 0.0)}

    def get_outcome_signals(self, category: str, as_of: str | None = None, snapshot_id: str | None = None) -> list[dict[str, Any]]:
        records = self._port.search_all("", category=category, as_of=as_of, snapshot_id=snapshot_id)
        return [
            {"keyword": r.keyword, "heat_index": r.heat_index, "record_date": r.record_date}
            for r in records if r.heat_index is not None
        ]

class RetroLedgerWriter:
    """复盘台账写入端口（独立，只追加复盘记录，不读取、不覆盖）

    注意：当前为内存测试实现（list），未接入任何持久化存储。仅用于验证「写入端口」
    与只读 View 的权限分离；生产环境需替换为真实持久化后端（如飞书 Base / SQLite）。
    """

    def __init__(self, ledger: list[dict[str, Any]] | None = None):
        self._ledger = ledger if ledger is not None else []

    def append_retro_entry(self, session_id: str, question: str, answer: str, timestamp: str | None = None) -> dict[str, Any]:
        entry = {
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        }
        self._ledger.append(entry)
        return entry
