"""数据访问网关 — AGENT_DATA_ACCESS 的运行时强制

Agent 只能通过本网关获取白名单内的四类数据能力：
1. 运行时 connector（走 CONNECTOR_REGISTRY）
2. Base Scoped View（走 VIEW_REGISTRY，只读能力对象）
3. 只读数据源（readonly_sources，声明但未实现 → fail-closed）
4. 独立写入端口（走 WRITE_PORT_REGISTRY，如复盘台账 RetroLedgerWriter）

这是「信息隔离」的代码级约束（而非仅 prompt 声明），graph.py 的 Agent 创建路径
（_instantiate_agent）经此注入。BaseDataAdapter 只能由本网关持有，绝不直接注入 Agent。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.config import AGENT_DATA_ACCESS


class DataAccessViolation(Exception):
    """尝试访问白名单外或未实现的数据源"""

def _google_trends():
    from app.data.google_trends import GoogleTrendsConnector
    return GoogleTrendsConnector()

def _bilibili():
    from app.data.bilibili_hot import BilibiliConnector
    return BilibiliConnector()

def _taobao():
    from app.data.taobao_suggest import TaobaoSuggestConnector
    return TaobaoSuggestConnector()

def _weibo():
    from app.data.weibo_hot import WeiboHotConnector
    return WeiboHotConnector()

def _baidu():
    from app.data.baidu_hot import BaiduHotConnector
    return BaiduHotConnector()

# 只注册仓库中真实存在的 connector。AGENT_DATA_ACCESS 的 connectors/readonly_sources
# 中声明但未实现的数据源（social_snapshot / ip_database / artifact_store 等）不在此
# 注册表 → fail-closed。
CONNECTOR_REGISTRY: dict[str, Callable[[], Any]] = {
    "google_trends": _google_trends,
    "bilibili_ranking": _bilibili,
    "taobao_suggest": _taobao,
    "weibo_hot": _weibo,
    "baidu_hot": _baidu,
}

# Base 数据适配层单例（懒加载）。只由本网关持有，Agent 拿到的永远是 Scoped View，
# 而非原始 BaseDataAdapter。延迟初始化：import 阶段不读配置、不失败。
_base_adapter: Any = None

def _get_base_adapter() -> Any:
    global _base_adapter
    if _base_adapter is None:
        from app.data.base_adapter import BaseDataAdapter
        _base_adapter = BaseDataAdapter()
    return _base_adapter

# ── Scoped View 注册表：视图名 → 工厂（入参为共享 adapter）────────────
VIEW_REGISTRY: dict[str, Callable[[Any], Any]] = {
    "TrendDataView": lambda a: _make_view("TrendDataView", a),
    "ConsumerDataView": lambda a: _make_view("ConsumerDataView", a),
    "IPDataView": lambda a: _make_view("IPDataView", a),
    "BusinessSummaryView": lambda a: _make_view("BusinessSummaryView", a),
    "GTMMarketView": lambda a: _make_view("GTMMarketView", a),
    "LearningLedgerReadView": lambda a: _make_view("LearningLedgerReadView", a),
}

def _make_view(view_name: str, adapter: Any) -> Any:
    from app.data import scoped_views as sv
    from app.data.base_adapter import RestrictedQueryPort
    cls = getattr(sv, view_name)
    # 只注入受限查询端口，不注入完整 BaseDataAdapter（应用层能力隔离）
    return cls(RestrictedQueryPort(adapter))

# ── 写入端口注册表：端口名 → 工厂 ──────────────────────────────
WRITE_PORT_REGISTRY: dict[str, Callable[[], Any]] = {
    "RetroLedgerWriter": lambda: _make_writer("RetroLedgerWriter"),
}

def _make_writer(port_name: str) -> Any:
    from app.data import scoped_views as sv
    cls = getattr(sv, port_name)
    return cls()

def _agent_scope(agent_key: str) -> dict[str, list[str]]:
    """返回 agent 的四类权限声明；未知 key 返回空作用域（fail-closed）"""
    return AGENT_DATA_ACCESS.get(agent_key, {})

def resolve_connector(agent_key: str, connector_name: str) -> Any:
    """解析单个运行时 connector：白名单外或未实现 → DataAccessViolation（fail-closed）"""
    allowed = set(_agent_scope(agent_key).get("connectors", []))
    if connector_name not in allowed:
        raise DataAccessViolation(
            f"数据源 '{connector_name}' 不在 '{agent_key}' 的运行时 connector 白名单内"
        )
    factory = CONNECTOR_REGISTRY.get(connector_name)
    if factory is None:
        raise DataAccessViolation(
            f"数据源 '{connector_name}' 已声明但未实现（fail-closed，拒绝访问）"
        )
    return factory()

def resolve_connectors(agent_key: str) -> dict[str, Any]:
    """返回 agent 白名单内、且已实现的运行时 connector 实例映射（跳过未实现项）"""
    resolved: dict[str, Any] = {}
    for name in _agent_scope(agent_key).get("connectors", []):
        factory = CONNECTOR_REGISTRY.get(name)
        if factory is not None:
            resolved[name] = factory()
    return resolved

def resolve_views(agent_key: str) -> dict[str, Any]:
    """返回 agent 白名单内的 Base Scoped View 实例映射（经共享 adapter 构造）

    - 只返回 VIEW_REGISTRY 中已注册的视图，未注册 → 跳过（fail-closed）。
    - 创意官（product_ideation_agent）的 views 为空 → 不持有任何数据视图。
    - Agent 拿到的 View 不暴露 raw adapter（隔离在 View 内部）。
    """
    adapter = _get_base_adapter()
    resolved: dict[str, Any] = {}
    for name in _agent_scope(agent_key).get("views", []):
        factory = VIEW_REGISTRY.get(name)
        if factory is not None:
            resolved[name] = factory(adapter)
    return resolved

def resolve_write_port(agent_key: str) -> Any | None:
    """返回 agent 白名单内的写入端口实例（如 RetroLedgerWriter）

    - 无 write_ports 或未注册 → None（无写入能力）。
    - 写入端口与只读 View 分离：读取走 resolve_views，写入走本函数。
    """
    ports = _agent_scope(agent_key).get("write_ports", [])
    if not ports:
        return None
    # 一个 agent 当前最多一个写入端口（learning_agent → RetroLedgerWriter）
    factory = WRITE_PORT_REGISTRY.get(ports[0])
    if factory is None:
        return None
    return factory()
