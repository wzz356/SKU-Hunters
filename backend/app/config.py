"""全局配置 — 权重模板 / 数据白名单 / 质检回退表

三个 D1 冻结项的代码化：
1. WEIGHT_TEMPLATES：三个预设权重模板（把参数问题翻译成业务语言）
2. AGENT_DATA_ACCESS：信息隔离白名单（依赖注入实现，不靠 prompt 约束）
3. REVIEW_FALLBACK_TABLE：ReviewAgent 打回时的 target_node 映射
"""

from __future__ import annotations

from .schemas.brief import Weights

# ── 1. 权重模板 ──────────────────────────────────────────────
# 依据：默认套来自行业先验（趋势衰减最快故最高）；
# 模板间差异对应战略意图（走量看需求、形象看趋势、利润看差异化）

WEIGHT_TEMPLATES: dict[str, Weights] = {
    "default": Weights(
        trend_heat=0.35, user_demand=0.25, ip_fit=0.20,
        competition=0.10, history_analog=0.10,
    ),
    "volume": Weights(  # 走量款：需求强度优先，趋势次之
        trend_heat=0.25, user_demand=0.35, ip_fit=0.15,
        competition=0.15, history_analog=0.10,
    ),
    "image": Weights(  # 形象款：趋势热度优先，抢占话题窗口
        trend_heat=0.45, user_demand=0.20, ip_fit=0.20,
        competition=0.05, history_analog=0.10,
    ),
    "profit": Weights(  # 利润款：差异化空间（竞争反向）优先
        trend_heat=0.25, user_demand=0.20, ip_fit=0.20,
        competition=0.20, history_analog=0.15,
    ),
}


# ── 2. 信息隔离白名单（剧本铁律一）────────────────────────────
# 每个 Agent 构造时只注入白名单内的 connector——
# 物理上无法访问其他数据源，而不是「被告知不要访问」。
# 注意：product_ideation 没有任何原始数据源，只有 artifact_store，
# 这是「创意官只见结论不见数据」的实现。

AGENT_DATA_ACCESS: dict[str, dict[str, list[str]]] = {
    # 四类权限显式区分（剧本铁律一的代码化）：
    #   connectors        —— 运行时 connector（走 CONNECTOR_REGISTRY，可实例化）
    #   readonly_sources  —— 已声明但未实现的只读数据源（fail-closed，暂不归类）
    #   views             —— Base Scoped View（走 VIEW_REGISTRY，只读能力对象）
    #   write_ports       —— 独立写入端口（走 WRITE_PORT_REGISTRY，如复盘台账）
    "trend_agent": {
        "connectors": [
            "google_trends",       # 海外搜索趋势（需海外网络）
            "bilibili_ranking",    # B站分区排行
        ],
        "readonly_sources": [
            "social_snapshot",     # 小红书/TikTok 预采集快照（未实现）
        ],
        "views": ["TrendDataView"],
        "write_ports": [],
    },
    "consumer_insight_agent": {
        "connectors": [
            "taobao_suggest",      # 淘宝联想词（需求侧）
        ],
        "readonly_sources": [
            "ecommerce_reviews",   # 电商评论数据集（未实现）
            "ugc_comments",        # UGC 评论情绪（未实现）
        ],
        "views": ["ConsumerDataView"],
        "write_ports": [],
    },
    "ip_strategy_agent": {
        "connectors": [],
        "readonly_sources": [
            "ip_database",         # IP 热度/授权信息库（未实现）
            "licensing_db",        # 授权案例库（未实现）
            "hit_case_library",    # 历史联名案例（RAG，未实现）
        ],
        "views": ["IPDataView"],
        "write_ports": [],
    },
    "product_ideation_agent": {
        "connectors": [],
        "readonly_sources": [
            "artifact_store",      # 仅三方 Artifact + 知识库，无原始数据（未实现）
            "hit_case_library",
        ],
        "views": [],               # 创意官不注入任何数据视图（只见结论不见数据）
        "write_ports": [],
    },
    "business_evaluation_agent": {
        "connectors": [],
        "readonly_sources": [
            "cost_db",             # 成本数据（未实现）
            "competitor_db",       # 竞品数据（未实现）
            "sales_reference",     # 历史销售参照（未实现）
        ],
        "views": ["BusinessSummaryView"],
        "write_ports": [],
    },
    "go_to_market_agent": {
        "connectors": [],
        "readonly_sources": [
            "market_db",           # 区域市场数据（未实现）
            "holiday_calendar",    # 节假日日历（未实现）
        ],
        "views": ["GTMMarketView"],
        "write_ports": [],
    },
    "learning_agent": {
        "connectors": [],
        "readonly_sources": [
            "ledger",              # 多维表格决策台账（未实现，只读经 LearningLedgerReadView）
            "sales_actuals",       # 上市后实际数据（未实现）
        ],
        "views": ["LearningLedgerReadView"],
        "write_ports": ["RetroLedgerWriter"],  # 复盘台账写入端口（独立，只追加）
    },
}


# ── 3. 质检回退表（target_node 映射）──────────────────────────
# ReviewAgent 打回时的跳转目标；最小失效重跑原则：
# 从最早受影响节点起重跑，上游不受影响部分复用 checkpoint。

REVIEW_FALLBACK_TABLE: dict[str, str] = {
    # 证据类
    "missing_evidence": "{producer}",        # 无证据 → 打回产出该结论的 Agent
    "cross_scope_reference": "{producer}",   # 跨权限引用 → 打回产出方 + 系统日志
    # 冲突类
    "conflict_unmarked": "{producer}",       # 数据冲突未显式标注 → 打回产出方
    "quote_deviation": "product_ideation_agent",  # 引用偏差 → 打回创意官
    # 结构类
    "missing_field": "{producer}",           # 关键字段缺失 → 打回产出方
    "source_map_incomplete": "product_ideation_agent",  # 溯源未覆盖三方 → 创意官
    "budget_violation": "product_ideation_agent",       # 超预算 → 创意官
    "proposal_not_distinct": "product_ideation_agent",  # 方案互异性不足 → 创意官
    # 报告类
    "report_new_fact": "report_agent",       # 报告引入 Artifact 外新事实 → 报告官
    "report_expression": "report_agent",     # 表达问题 → 报告官
    # 决策类
    "decision_format": "decision_engine",    # 建议书结构错误 → 决策引擎
}


# ── 4. 决策映射规则（写死，LLM 不得自由发挥）───────────────────

def map_recommendation(total_score: float, has_major_caveat: bool) -> str:
    """总评 → 决策建议 的规则映射（剧本 4.1）"""
    if total_score >= 80 and not has_major_caveat:
        return "approve"
    if total_score >= 60:
        return "hold"
    return "reject"
