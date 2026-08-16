"""洞察增强 Agent — 回归测试

覆盖三件事：
1. 黄金样例（小风扇五段式，从旧前端 fixture 迁出）仍可被 EnrichmentResult 校验 ——
   证明 Agent 输出 schema 向后兼容调好的五段式结构，不因去 fixture 而丢能力。
2. 数字纪律：metrics/subCategoryTrends 由代码构建真实计数，采集侧无样本量时
   records/growthPct 如实留 None，不编造。
3. 势头推导（_derive_momentum）品类无关，不硬编码品类词。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.planning.insight_enrichment import (
    _build_metrics,
    _build_subcategory_trends,
    _derive_momentum,
)
from app.planning.repository import _snake_keys
from app.schemas.planning import EnrichmentResult

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "fan_enrichment_golden.json"


def test_golden_fan_enrichment_still_validates():
    """黄金样例（含 records/growthPct 的富数字版）仍能过 EnrichmentResult 契约"""
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    result = EnrichmentResult.model_validate(_snake_keys(data))
    assert result.trend_summary.verdict
    assert len(result.topic_clusters) == 3
    assert len(result.sub_category_trends) == 7
    assert result.season_plan.launch_suggestion
    # 富数字版：records/growthPct 保留（采集侧有据的品类才填）
    assert result.sub_category_trends[0].records == 32
    assert result.sub_category_trends[0].growth_pct == 132.0


def test_derive_momentum_category_agnostic():
    assert _derive_momentum("爆发式增长") == "surge"
    assert _derive_momentum("增速跑赢大盘") == "rising"
    assert _derive_momentum("从氛围型→功效型") == "emerging"  # → 表示品类转型升级
    assert _derive_momentum("") == "stable"
    assert _derive_momentum(None) == "stable"
    # 正增长百分比：涨幅≥100% 判 surge，否则 rising
    assert _derive_momentum("同比 +41.6% 至 +128.6%") == "surge"
    assert _derive_momentum("转化率 +41%，退货率 -8pp") == "rising"


def test_build_metrics_counts_real():
    bundle = {
        "trendRadar": {"signals": [{"name": "x"}] * 7},
        "consumerVoice": {"painPoints": [{"text": "p"}] * 4},
        "competitiveMap": {"products": [{"name": "c"}] * 6},
    }
    metrics = _build_metrics(bundle)
    assert metrics[0]["value"] == "7 条"
    assert metrics[1]["value"] == "4 条"
    assert metrics[2]["value"] == "6 个"
    assert all(m["direction"] == "flat" for m in metrics)


def test_build_subcategory_no_fabricated_numbers():
    """采集侧无样本量/同比 → records/growthPct 留 None，只保留真实信号名 + 溯源 + 势头"""
    bundle = {"trendRadar": {"signals": [
        {"name": "助眠/睡眠经济", "metric": "从氛围型→功效型", "source": "新华报业", "period": "近30-90天"},
        {"name": "线香/固体香薰增长", "metric": "增速跑赢大盘", "source": "华丽志", "period": ""},
    ]}}
    trends = _build_subcategory_trends(bundle)
    assert len(trends) == 2
    assert all(t["records"] is None for t in trends)
    assert all(t["growthPct"] is None for t in trends)
    assert trends[0]["momentum"] == "emerging"
    assert trends[1]["momentum"] == "rising"
    assert trends[0]["note"] == "新华报业"
