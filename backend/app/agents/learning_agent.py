"""LearningAgent — 真实学习官（复盘 / 学习档案）

职责：
- 生成 NormalizedActualSignal（归一化实际结果信号）：区分 observed/partial/unavailable/invalid；
- 生成 RetroReport（复盘报告）：缺实际数据时保守输出，不伪造销量/上市结果。

纪律：
- 不调用 LLM；
- 不把热度/搜索量/品类聚合/市场参照/opportunity_score 当成销售实际；
- sales_actuals 未接入 → status=unavailable，不填 0 冒充真实结果；
- 无 source_url 不伪造 EvidenceRef；
- 有真实且完整实际信号时才对比预测与实际，但仍只提权重建议，不自动改参。

数据权限：只读 views["LearningLedgerReadView"]；写入只经独立 RetroLedgerWriter（write_port）。
"""

from __future__ import annotations

from typing import Any

from app.agents.base_agent import BaseAgent
from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.engine.strict_mode import resolve_provider
from app.learning.actual_signal import ActualStatus, NormalizedActualSignal
from app.schemas import Confidence, DimensionGap, EvidenceRef, RetroReport

# 评估维度（与 OpportunityScore.dimension_scores 对齐）
_DIMENSIONS = ["trend_heat", "user_demand", "ip_fit", "competition", "history_analog"]

class LearningAgent(BaseAgent):
    """真实学习官"""

    name = "learning_agent"
    description = "学习官：归一化实际结果信号 + 复盘报告（缺数据保守，不伪造）"

    def __init__(self, config: dict | None = None, views: dict[str, Any] | None = None, write_port: Any | None = None):
        super().__init__(config)
        self.views = views or {}
        self.write_port = write_port

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        actual_signal = self._build_actual_signal(context)
        retro_report = self._build_retro_report(context, actual_signal)
        return {
            "normalized_actual_signal": actual_signal.model_dump(mode="json"),
            "retro_report": retro_report.model_dump(mode="json"),
            "archive_update": {"actual_signal_status": actual_signal.status.value},
        }

    # ── NormalizedActualSignal ──────────────────────────

    def _build_actual_signal(self, context: dict[str, Any]) -> NormalizedActualSignal:
        category = context.get("category", "")
        view = self.views.get("LearningLedgerReadView")
        if view is None:
            return self._unavailable_signal("LearningLedgerReadView 不可用")
        try:
            outcome_signals = view.get_outcome_signals(category)
        except (BaseUnavailable, BaseProviderError):
            return self._unavailable_signal("实际数据源不可用，无法获得真实上市结果")

        if not outcome_signals:
            return self._unavailable_signal("sales_actuals 未接入，无法获得真实上市结果")

        # 提取明确识别且通过范围校验的 sales_actuals 指标
        metrics: dict[str, float] = {}
        skipped: list[str] = []
        valid_signals = []
        for sig in outcome_signals:
            if not self._is_sales_actuals(sig):
                continue
            valid_signals.append(sig)
            for key in ("first_month_sales_attainment", "sell_through_rate",
                        "sellout_rate", "social_buzz_persistence"):
                if key not in sig:
                    continue  # 缺失指标不默认填 0
                val = sig[key]
                if isinstance(val, (int, float)) and self._in_valid_range(val):
                    metrics[key] = float(val)
                else:
                    skipped.append(key)

        caveats: list[str] = []
        if skipped:
            caveats.append(f"非法指标已跳过：{', '.join(sorted(set(skipped)))}")

        if not metrics:
            if skipped:
                return self._invalid_signal(caveats)
            return self._unavailable_signal("outcome_signals 非明确 sales_actuals，无法获得真实上市结果")

        if len(metrics) >= 4:
            status, confidence = ActualStatus.OBSERVED, Confidence.MEDIUM
        else:
            status, confidence = ActualStatus.PARTIAL, Confidence.LOW

        # period / source：从有效实际记录提取真实来源，缺失时用 learning_ledger
        period = self._extract_period(valid_signals)
        source = self._extract_source(valid_signals)

        return NormalizedActualSignal(
            status=status,
            metrics=metrics,
            period=period,
            source=source,
            snapshot_id=context.get("snapshot_id", ""),
            evidence_refs=self._extract_evidence(outcome_signals),
            confidence=confidence,
            caveats=caveats,
        )

    def _unavailable_signal(self, msg: str) -> NormalizedActualSignal:
        return NormalizedActualSignal(
            status=ActualStatus.UNAVAILABLE, metrics={},
            confidence=Confidence.UNKNOWN, evidence_refs=[], caveats=[msg],
        )

    def _invalid_signal(self, caveats: list[str]) -> NormalizedActualSignal:
        return NormalizedActualSignal(
            status=ActualStatus.INVALID, metrics={},
            confidence=Confidence.UNKNOWN, evidence_refs=[], caveats=caveats,
        )

    def _is_sales_actuals(self, sig: dict[str, Any]) -> bool:
        return any(
            k in sig for k in ("first_month_sales_attainment", "sell_through_rate",
                               "sellout_rate", "social_buzz_persistence")
        )

    @staticmethod
    def _in_valid_range(val: float) -> bool:
        return 0.0 <= val <= 1.0

    def _extract_period(self, signals: list[dict[str, Any]]) -> str:
        """从有效实际记录提取 period/record_date，缺失返回空串"""
        for sig in signals:
            if sig.get("period"):
                return str(sig["period"])
            if sig.get("record_date"):
                return str(sig["record_date"])
        return ""

    def _extract_source(self, signals: list[dict[str, Any]]) -> str:
        """用记录真实提供的 source；缺失时明确用 learning_ledger"""
        for sig in signals:
            if sig.get("source"):
                return str(sig["source"])
        return "learning_ledger"

    def _extract_evidence(self, outcome_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """只从真实 source_url 构建证据，不伪造 URL"""
        refs: list[dict[str, Any]] = []
        for sig in outcome_signals:
            url = sig.get("source_url")
            if url:
                ref = {"url": url, "title": sig.get("keyword", ""), "snippet": str(sig.get("record_date", ""))}
                if ref not in refs:
                    refs.append(ref)
        return refs[:5]

    # ── RetroReport ──────────────────────────

    def _build_retro_report(self, context: dict[str, Any], actual_signal: NormalizedActualSignal) -> RetroReport:
        proposal_name = context.get("proposal", {}).get("name", "")
        session_id = context.get("session_id", "")
        decision_record_ref = f"{session_id}:{proposal_name}"
        preds = self._dimension_predictions(context.get("opportunity_score", {}))

        if actual_signal.status in (ActualStatus.UNAVAILABLE, ActualStatus.INVALID):
            return RetroReport(
                proposal_name=proposal_name,
                decision_record_ref=decision_record_ref,
                outcome_metrics={},
                dimension_gaps=[
                    DimensionGap(dimension=d, predicted=preds.get(d, 0.0),
                                 actual_signal="unavailable", accuracy="unknown")
                    for d in _DIMENSIONS
                ],
                attribution="缺少真实上市后实际数据，无法进行预测结果归因",
                weight_advice=None,
                advice_basis_periods=0,
                confidence=Confidence.UNKNOWN,
                evidence_refs=[],
                caveats=actual_signal.caveats or ["sales_actuals 未接入，无法获得真实上市结果"],
            )

        # observed/partial：有真实实际指标才对比预测与实际
        attainment = actual_signal.metrics.get("first_month_sales_attainment")
        gaps = [
            DimensionGap(
                dimension=d,
                predicted=preds.get(d, 0.0),
                actual_signal=self._describe_metric(d, actual_signal.metrics),
                accuracy=self._accuracy_for(preds.get(d, 0.0), attainment),
            )
            for d in _DIMENSIONS
        ]
        return RetroReport(
            proposal_name=proposal_name,
            decision_record_ref=decision_record_ref,
            outcome_metrics=actual_signal.metrics,
            dimension_gaps=gaps,
            attribution=(
                "基于真实上市后实际指标与预测分对比："
                + "；".join(f"{g.dimension}={g.accuracy}" for g in gaps)
                + "。归因仅反映预测偏差，不涉及 LLM 推断。"
            ),
            weight_advice=None,   # 只提建议，不自动改参；单次不调权重
            advice_basis_periods=0,
            confidence=actual_signal.confidence,
            evidence_refs=[EvidenceRef(**e) for e in actual_signal.evidence_refs],
            caveats=actual_signal.caveats,
        )

    def _describe_metric(self, dimension: str, metrics: dict[str, float]) -> str:
        if "first_month_sales_attainment" in metrics:
            return f"首月销量达成率 {metrics['first_month_sales_attainment']:.2f}"
        return "有实际指标但该维度无对应度量"

    def _accuracy_for(self, predicted: float, attainment: float | None) -> str:
        if attainment is None:
            return "unknown"
        if predicted >= 70:
            return "accurate" if attainment >= 0.7 else "overestimated"
        if predicted <= 40:
            return "underestimated" if attainment >= 0.7 else "accurate"
        return "accurate"

    def _dimension_predictions(self, opportunity_score: dict[str, Any]) -> dict[str, float]:
        preds: dict[str, float] = {}
        for ds in opportunity_score.get("dimension_scores") or []:
            preds[ds.get("dimension")] = ds.get("score", 0.0)
        return preds

class MockLearningAgent(LearningAgent):
    """Mock 学习官：不访问数据源，直接输出 unavailable（保留兼容行为）"""

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        actual = self._unavailable_signal("sales_actuals 未接入，无法获得真实上市结果")
        retro = self._unavailable_retro(context, actual)
        return {
            "normalized_actual_signal": actual.model_dump(mode="json"),
            "retro_report": retro.model_dump(mode="json"),
            "archive_update": {"actual_signal_status": "unavailable"},
        }

    def _unavailable_retro(self, context: dict[str, Any], actual_signal: NormalizedActualSignal) -> RetroReport:
        return self._build_retro_report(context, actual_signal)

def get_learning_agent_class() -> type[BaseAgent]:
    """注册表切换：默认 MockLearningAgent；设 LEARNING_AGENT_PROVIDER=real 时返回真实实现"""
    provider = resolve_provider("学习官", "LEARNING_AGENT_PROVIDER")
    if provider == "real":
        return LearningAgent
    return MockLearningAgent
