"""趋势官确定性计算（从旧本地趋势官迁移）

所有数字由 Python 计算，不让 LLM 生成。评分公式集中在此模块，
每个计算结果必须能从 raw_metrics 与 FORMULA_VERSION 复算。

本模块为趋势官内部数据模型，不触碰 GitHub 冻结的产出 Schema：
  - SourceSignal / SourceScore 是内部中间结构；
  - 迁移后的最终产出仍为 GitHub 仓库的 FeatureMatrix。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

FORMULA_VERSION = "0.2.0"

Lifecycle = Literal[
    "emerging", "rising", "peak", "mature", "declining", "unknown"
]
ConfidenceLevel = Literal["high", "medium", "low", "unknown"]


@dataclass
class SourceSignal:
    """标准化数据源信号（内部中间结构）"""

    source: str                       # google_trends / bilibili_ranking / taobao_suggest
    keyword: str
    region: str = "global"
    observed_at: str = ""
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    normalized_metrics: dict[str, Any] = field(default_factory=dict)
    data_quality: str = "high"        # high / low / unknown
    evidence_id: str = ""


@dataclass
class SourceScore:
    """单来源确定性评分（内部中间结构）"""

    source: str
    level: float | None = None
    growth: float | None = None
    breadth: float | None = None
    heat_score: float | None = None
    direction: str = "unknown"        # rising / stable / declining / unknown
    data_quality: str = "unknown"     # high / low / unknown
    evidence_ids: list[str] = field(default_factory=list)


class TrendMetrics:
    """趋势指标计算器 — 所有数值计算的确定性入口。

    输入 SourceSignal，输出 SourceScore；并据此计算综合热度、生命周期、置信度。
    """

    # ── 综合计算 ──────────────────────────────────────────────

    @staticmethod
    def compute_source_score(signal: SourceSignal) -> SourceScore:
        if signal.source == "google_trends":
            return TrendMetrics._score_google_trends(signal)
        if signal.source == "bilibili_ranking":
            return TrendMetrics._score_bilibili(signal)
        if signal.source == "taobao_suggest":
            return TrendMetrics._score_taobao(signal)
        return SourceScore(
            source=signal.source,
            data_quality="unknown",
            evidence_ids=[signal.evidence_id] if signal.evidence_id else [],
        )

    @staticmethod
    def compute_heat_index(source_scores: list[SourceScore]) -> float | None:
        """综合各来源评分计算 heat_index。

        只使用 data_quality 非 unknown 且 heat_score 非 None 的来源；
        淘宝信号不进入正式 heat_index。
        """
        valid = [
            s for s in source_scores
            if s.heat_score is not None
            and s.data_quality != "unknown"
            and s.source != "taobao_suggest"
        ]
        if not valid:
            return None
        return round(sum(s.heat_score for s in valid) / len(valid), 1)

    @staticmethod
    def compute_engagement_rate(play: int, like: int, danmaku: int) -> float:
        """B站互动率：由 Python 计算，不让 LLM 算"""
        if play <= 0:
            return 0.0
        return round((like + danmaku) / play, 4)

    @staticmethod
    def judge_lifecycle(source_scores: list[SourceScore]) -> Lifecycle:
        """生命周期基础判断（规则严格按旧趋势官业务文档）。

        - rising: 水平与增速均为正，且至少一个其他平台有支持信号
        - emerging: 只有 Google 显示上升但无其他平台支持
        - peak / mature / declining: 依 Google level 与 direction 判定
        - unknown: 无历史、低基数、来源不足或数据冲突无法判定
        无 Google Trends 或 Google direction 未知时，不得仅凭一次 B站排名
        判断 rising，一律返回 unknown。
        """
        valid = [s for s in source_scores if s.data_quality != "unknown"]
        if not valid:
            return "unknown"

        google = next((s for s in valid if s.source == "google_trends"), None)
        bilibili = next(
            (s for s in valid if s.source == "bilibili_ranking"), None
        )

        if google is None or google.direction == "unknown":
            return "unknown"

        if google.direction == "rising":
            if (
                bilibili is not None
                and bilibili.heat_score is not None
                and bilibili.heat_score >= 30
            ):
                return "rising"
            return "emerging"

        if google.direction == "declining":
            return "declining"

        if google.direction == "stable":
            level = google.level or 0
            if level >= 70:
                return "peak"
            if level >= 40:
                return "mature"
            return "unknown"

        return "unknown"

    @staticmethod
    def assess_confidence(
        source_scores: list[SourceScore],
        heat_index: float | None,
        lifecycle: str,
    ) -> ConfidenceLevel:
        """评估置信度：high/medium/low/unknown。unknown 保持 unknown，不掩盖。"""
        valid = [s for s in source_scores if s.data_quality != "unknown"]
        if not valid:
            return "unknown"

        high_quality = [s for s in valid if s.data_quality == "high"]

        if (
            len(high_quality) >= 2
            and heat_index is not None
            and lifecycle != "unknown"
        ):
            return "high"
        if len(high_quality) >= 1 or heat_index is not None:
            return "medium"
        if valid and all(s.data_quality == "low" for s in valid):
            return "low"
        return "unknown"

    # ── 各来源评分 ──────────────────────────────────────────

    @staticmethod
    def _score_google_trends(signal: SourceSignal) -> SourceScore:
        raw = signal.raw_metrics
        level = raw.get("level")
        growth = raw.get("growth")
        breadth = raw.get("breadth")
        heat_index = raw.get("heat_index")

        # 低基数检查：前期均值过低时增长容易失真
        data_quality = signal.data_quality
        if level is not None and level < 5:
            data_quality = "low"

        lifecycle_raw = raw.get("lifecycle", "unknown")
        direction_map = {
            "rising": "rising",
            "peak": "stable",
            "declining": "declining",
        }
        direction = direction_map.get(lifecycle_raw, "unknown")

        return SourceScore(
            source="google_trends",
            level=level,
            growth=growth,
            breadth=breadth,
            heat_score=heat_index if heat_index is not None else None,
            direction=direction,
            data_quality=data_quality,
            evidence_ids=[signal.evidence_id] if signal.evidence_id else [],
        )

    @staticmethod
    def _score_bilibili(signal: SourceSignal) -> SourceScore:
        raw = signal.raw_metrics
        total_views = raw.get("total_views", 0) or 0
        total_results = raw.get("total_results", 0) or 0
        # scanned_videos 可能为 None（无法获知真实扫描总数），
        # 此时 breadth 无法计算，返回 None 而不是用匹配数代替分母
        scanned = raw.get("scanned_videos") or 0

        level = min(100, total_views / 100000)  # 1000万播放 = 100分

        # 扫描总数未知时返回 None，不得产生恒 100% 的伪 breadth
        breadth = (
            round(total_results / scanned * 100, 1) if scanned > 0 else None
        )

        if total_results > 0:
            heat_score = min(100, (level * 0.6 + (breadth or 0) * 0.4))
        else:
            heat_score = None

        # B站是截面数据，direction 无法从单次采集判断，不伪装 rising
        data_quality = signal.data_quality
        if total_results == 0:
            data_quality = "low"

        # 聚合证据 + 视频级证据（BV 号），保证引用不断链
        evidence_ids = [signal.evidence_id] if signal.evidence_id else []
        evidence_ids += [
            f"bilibili:{v['bvid']}"
            for v in raw.get("top_videos", []) or []
            if v.get("bvid")
        ]

        return SourceScore(
            source="bilibili_ranking",
            level=round(level, 1) if level else None,
            growth=None,  # 截面数据无法计算增长
            breadth=breadth,
            heat_score=round(heat_score, 1) if heat_score is not None else None,
            direction="unknown",  # 无历史快照时不得判断方向
            data_quality=data_quality,
            evidence_ids=evidence_ids,
        )

    @staticmethod
    def _score_taobao(signal: SourceSignal) -> SourceScore:
        """淘宝联想词评分：标记为 provisional_demand_signal，
        不进入趋势官正式 heat_index，仅用于 handoff 转交。"""
        raw = signal.raw_metrics
        breadth = raw.get("demand_breadth", 0)
        avg_heat = raw.get("avg_heat", 0)

        return SourceScore(
            source="taobao_suggest",
            level=round(avg_heat, 1) if avg_heat else None,
            growth=None,
            breadth=float(breadth) if breadth else None,
            heat_score=None,  # 淘宝不进入正式热度评分
            direction="unknown",
            data_quality=signal.data_quality,
            evidence_ids=[signal.evidence_id] if signal.evidence_id else [],
        )
