"""crawled 三态 mode —— 回归测试

目标：任何真实品类任务（mode=crawled）绝不能拿到 demo 的小风扇 fixture bundle。
- fixture = 冻结演示样例（只用于 demo/test）
- crawled = 真实采集 + LLM 分析（Stage 1-4 主链路，默认）
- live    = 飞书实时（严格模式保留）
"""

from __future__ import annotations

from app.engine.strict_mode import planning_default_mode
from app.planning import insight_resolver


def test_planning_default_mode_is_crawled():
    """非生产环境默认分析路径必须是 crawled（不是 fixture）"""
    assert planning_default_mode() == "crawled"


def test_crawled_mode_no_fixture_contamination(monkeypatch):
    """保温杯 crawled 任务：dataSource=crawled，痛点不是小风扇 fixture 文案"""
    from app.planning.fixtures import CONSUMER_VOICE as FIXTURE_CV

    # 跳过 enrichment 的 LLM 调用，聚焦路由本身
    monkeypatch.setattr(insight_resolver, "_attach_enrichment", lambda c, b, br: None)

    bundle = insight_resolver._resolve_insight_bundle("保温杯", {"mode": "crawled"})
    assert bundle["dataSource"] == "crawled"

    crawled_pains = " ".join(p.get("text", "") for p in bundle["consumerVoice"]["painPoints"])
    fixture_pains = " ".join(p.get("text", "") for p in FIXTURE_CV["painPoints"])

    # 品类一致性：爬取的痛点必须 ≠ 冻结小风扇 fixture 的痛点（不依赖具体 fixture 文案）
    assert crawled_pains != fixture_pains
    # 额外锚点：确保不是小风扇内容泄漏
    for word in ("普通风扇太丑", "风力小", "噪音大", "挂脖风扇"):
        assert word not in crawled_pains


def test_fixture_mode_still_returns_frozen_demo():
    """fixture 模式仍显式返回冻结演示数据（demo 流程不受影响）"""
    bundle = insight_resolver._resolve_insight_bundle("小风扇", {"mode": "fixture"})
    assert bundle["dataSource"] == "fixture"
