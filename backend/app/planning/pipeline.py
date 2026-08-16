"""AI 新品企划工作室 — 企划生成管线（兼容入口）

⚠️ 本模块已重构为「兼容入口」，仅做符号 re-export，向后兼容旧调用方
（api/planning.py、tests、feishu 等仍 `from app.planning import pipeline`）。

业务逻辑已按职责拆分到同目录的 6 个模块：
    service.py              业务流程编排（洞察→机会→企划卡→改稿→归档）
    repository.py           任务存储（内存 + 原子文件持久化，并发安全）
    insight_resolver.py     五看洞察解析（真实社媒证据优先，LLM 生成兜底）
    opportunity_engine.py   机会生成引擎（3 张方向卡，纯函数）
    plan_card_builder.py    企划卡组装（LLM 动态生成）
    cost_rules.py           成本校验规则（毛利率红线）

业务链路（对应全景设计文档 v2.0）：
    ① 企划约束 → ② 五看洞察（趋势/用户/竞品 + 名创内部 + 流行元素板）
    → ③ 机会生成 → ④ 创意设计 → ⑤ 商品策略 → ⑥ 新品企划卡

数据策略：真实社媒采集数据优先；无采集数据品类走真实 LLM 生成，
LLM 不可用时报错（503），无 fixture 假数据回退。
"""

from __future__ import annotations

# 引擎/服务模块对象（保留模块引用，供测试 monkeypatch 与兼容旧调用）
from app.engine import llm  # noqa: F401

# 成本校验规则
from app.planning.cost_rules import (  # noqa: F401
    MIN_GROSS_MARGIN,
    _parse_price,
    cost_check,
)

# 洞察解析（包含远端 8ed47ed 的具体异常捕获实现）
from app.planning.insight_resolver import (  # noqa: F401
    _load_heat_curve,
    _resolve_insight_bundle,
)

# 机会发现引擎（市场机会池）
from app.planning.opportunity_discovery import (  # noqa: F401
    build_opportunity_pool,
)

# 机会生成引擎（机会池 → 商品机会卡）
from app.planning.opportunity_engine import (  # noqa: F401
    _derive_price_band,
    _fallback_opportunities,
    _opportunities_from_bundle,
    _opportunities_process_log,
    expand_pool_to_cards,
)

# 企划卡组装
from app.planning.plan_card_builder import (  # noqa: F401
    _build_dynamic_plan_card,
    _concept_prompt_dynamic,
    _derive_price_from_band,
    _find_opportunity,
)

# 存储层（含键名工具、状态持久化）
from app.planning.repository import (  # noqa: F401
    _PLANS,
    _STATE_DIR,
    _STATE_FILE,
    _camel_to_snake,
    _load_state,
    _now,
    _save_state,
    _snake_keys,
    create_plan,
    delete_plan,
    get_plan,
    list_plans,
)

# 业务编排
from app.planning.service import (  # noqa: F401
    StateTransitionError,
    archive_plan,
    generate_insights,
    generate_opportunities,
    generate_plan_card,
    get_insights,
    get_opportunities,
    review_plan,
    revise_plan,
    seed_demo,
)
from app.services import jimeng  # noqa: F401
