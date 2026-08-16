"""跨源信号冲突检测（从旧本地趋势官迁移）

不得通过平均分隐藏冲突，也不得把"国内热、海外冷"直接解释为短期炒作。
所有冲突原样保留，交给人判断。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .trend_metrics import SourceScore

logger = logging.getLogger(__name__)

# 热度阈值：高于此值为"热"，低于此值为"冷"
HEAT_HOT_THRESHOLD = 60.0
HEAT_COLD_THRESHOLD = 30.0


@dataclass
class SignalConflict:
    """跨源冲突（内部中间结构）"""

    conflict_type: str
    sources: list[str] = field(default_factory=list)
    description: str = ""
    possible_explanations: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


class TrendConflictDetector:
    """跨源信号冲突检测器。

    检测：hot_vs_cold / rising_vs_declining / domestic_vs_overseas /
          insufficient_cross_validation
    """

    @staticmethod
    def detect(source_scores: list[SourceScore]) -> list[SignalConflict]:
        conflicts: list[SignalConflict] = []
        valid = [s for s in source_scores if s.data_quality != "unknown"]

        if not valid:
            return conflicts

        c = TrendConflictDetector._detect_hot_vs_cold(valid)
        if c:
            conflicts.append(c)
        c = TrendConflictDetector._detect_rising_vs_declining(valid)
        if c:
            conflicts.append(c)
        c = TrendConflictDetector._detect_domestic_vs_overseas(valid)
        if c:
            conflicts.append(c)
        c = TrendConflictDetector._detect_insufficient_sources(source_scores)
        if c:
            conflicts.append(c)

        if conflicts:
            logger.info(
                "检测到 %d 个跨源冲突: %s",
                len(conflicts),
                [cc.conflict_type for cc in conflicts],
            )
        return conflicts

    @staticmethod
    def _detect_hot_vs_cold(scores: list[SourceScore]) -> SignalConflict | None:
        hot = [
            s for s in scores
            if s.heat_score is not None and s.heat_score >= HEAT_HOT_THRESHOLD
        ]
        cold = [
            s for s in scores
            if s.heat_score is not None and s.heat_score < HEAT_COLD_THRESHOLD
        ]
        if hot and cold:
            hot_names = [s.source for s in hot]
            cold_names = [s.source for s in cold]
            return SignalConflict(
                conflict_type="hot_vs_cold",
                sources=[s.source for s in hot + cold],
                description=(
                    f"{'、'.join(hot_names)} 显示高热"
                    f"（{'、'.join(f'{s.heat_score:.0f}' for s in hot)}），"
                    f"但 {'、'.join(cold_names)} 显示低热"
                    f"（{'、'.join(f'{s.heat_score:.0f}' for s in cold)}）"
                ),
                possible_explanations=[
                    "不同平台的用户群体和内容生态存在差异",
                    "趋势可能处于早期阶段，尚未在所有平台扩散",
                    "需要更多数据点确认趋势的一致性",
                ],
                evidence_ids=[
                    eid for s in hot + cold for eid in s.evidence_ids
                ],
            )
        return None

    @staticmethod
    def _detect_rising_vs_declining(
        scores: list[SourceScore],
    ) -> SignalConflict | None:
        rising = [s for s in scores if s.direction == "rising"]
        declining = [s for s in scores if s.direction == "declining"]
        if rising and declining:
            return SignalConflict(
                conflict_type="rising_vs_declining",
                sources=[s.source for s in rising + declining],
                description=(
                    f"{'、'.join(s.source for s in rising)} 显示上升，"
                    f"但 {'、'.join(s.source for s in declining)} 显示下降"
                ),
                possible_explanations=[
                    "不同地区的趋势发展阶段不同",
                    "趋势可能正在从一种平台迁移到另一种平台",
                    "需要历史数据确认是否为暂时性背离",
                ],
                evidence_ids=[
                    eid for s in rising + declining for eid in s.evidence_ids
                ],
            )
        return None

    @staticmethod
    def _detect_domestic_vs_overseas(
        scores: list[SourceScore],
    ) -> SignalConflict | None:
        domestic = [
            s for s in scores
            if s.source in ("bilibili_ranking", "taobao_suggest")
        ]
        overseas = [s for s in scores if s.source == "google_trends"]

        if not domestic or not overseas:
            return None

        domestic_hot = any(
            s.heat_score is not None and s.heat_score >= HEAT_HOT_THRESHOLD
            for s in domestic
        )
        overseas_cold = any(
            s.heat_score is not None and s.heat_score < HEAT_COLD_THRESHOLD
            for s in overseas
        )
        domestic_cold = any(
            s.heat_score is not None and s.heat_score < HEAT_COLD_THRESHOLD
            for s in domestic
        )
        overseas_hot = any(
            s.heat_score is not None and s.heat_score >= HEAT_HOT_THRESHOLD
            for s in overseas
        )

        if (domestic_hot and overseas_cold) or (domestic_cold and overseas_hot):
            return SignalConflict(
                conflict_type="domestic_vs_overseas",
                sources=[s.source for s in domestic + overseas],
                description=(
                    f"国内信号（{'、'.join(s.source for s in domestic)}）"
                    f"与海外信号（{'、'.join(s.source for s in overseas)}）"
                    f"存在背离，需人工判断趋势的真实性和持续性"
                ),
                possible_explanations=[
                    "趋势可能具有地域局限性",
                    "国内外市场的消费者偏好存在差异",
                    "需要更多时间和数据验证趋势的全球性",
                ],
                evidence_ids=[
                    eid for s in domestic + overseas for eid in s.evidence_ids
                ],
            )
        return None

    @staticmethod
    def _detect_insufficient_sources(
        scores: list[SourceScore],
    ) -> SignalConflict | None:
        all_sources = {"google_trends", "bilibili_ranking", "taobao_suggest"}
        available = {s.source for s in scores if s.data_quality != "unknown"}
        missing = all_sources - available

        if len(missing) >= 2:
            return SignalConflict(
                conflict_type="insufficient_cross_validation",
                sources=list(available),
                description=(
                    f"仅 {len(available)} 个数据源可用"
                    f"（{'、'.join(available)}），"
                    f"缺少 {'、'.join(missing)}，"
                    f"无法进行充分的交叉验证"
                ),
                possible_explanations=[
                    "部分数据源暂时不可用或返回空数据",
                    "趋势结论的可靠性受限",
                ],
                evidence_ids=[],
            )
        return None
