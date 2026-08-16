"""商业官三种实现 + 三档注册表

- MockBusinessAgent（mock_agents）：默认，离线/确定/快
- BusinessEvaluationAgent（本文件）：确定性真实商业官——不调用 LLM，
  基于三官 Artifact（feature_matrix / user_sentiment / ip_assessment）与
  BusinessSummaryView（Scoped View）的聚合结果，确定性生成五维 OpportunityScore。
  评分纪律：五维分数均来自上游真实数据或 View 聚合结果，统一 clamp 0~100；
  缺少数据时保守为 0 并写入对应维度的 risk_warning；数据源不可用不得回退
  Mock，也不得把「数据不可用」变成高分。
- BusinessAgent（本文件）：真 LLM 商业官——LLM 按锚点 rubric 出五维分数与
  依据（强制引用材料），代码管加权算术（total_score / star_rating /
  evidence_refs 抽样）；LLM 未配置 / 输出不合 schema / 缺维度 / 分数越界 →
  整体回退 Mock（不部分输出，保证 scores 与 proposals 对齐）。

注册表三档（get_business_agent_class）：
  - 默认 / mock          → MockBusinessAgent
  - deterministic        → BusinessEvaluationAgent（确定性，不烧 LLM）
  - real（或总开关 AGENT_PROVIDER=real）→ BusinessAgent（LLM，故障回退 Mock）
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.mock_agents import MockBusinessAgent
from app.agents.real_common import (
    fuzzy_get,
    min_confidence,
    parse_llm_json,
)
from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.engine.ledger import format_analogs
from app.engine.strict_mode import require_mock_allowed, resolve_provider
from app.schemas import (
    Confidence,
    DimensionScore,
    EvidenceRef,
    OpportunityScore,
    RiskWarning,
    Weights,
)

# ══════════════════ 确定性实现：BusinessEvaluationAgent ══════════════════

# ── 纯函数：确定性评分公式 ──────────────────────────

def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """统一 clamp：所有维度分数限制在 [lo, hi]，默认 0~100"""
    return max(lo, min(hi, value))

def score_trend_heat(trends: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """trend_heat = 趋势峰值热度（FeatureMatrix.trends 的 heat_index 最大值）。

    无趋势信号 → 0 + warning，不把缺数据当成趋势热度。
    """
    if not trends:
        return 0.0, ["无趋势信号，trend_heat 保守为 0"]
    heat = max((t.get("heat_index") or 0.0) for t in trends)
    return clamp(float(heat)), []

def score_user_demand(
    pain_points: list[dict[str, Any]],
    motivation_tags: list[str],
    sentiment: dict[str, Any],
) -> tuple[float, list[str]]:
    """user_demand = 痛点平均频率 × 70 + 动机标签数（≤3）× 10。

    不根据文字主观臆造比例；sentiment 为 neutral 占位（无情感测量）时保守计分并加 warning。
    """
    warnings: list[str] = []
    if pain_points:
        avg_freq = sum((p.get("frequency") or 0.0) for p in pain_points) / len(pain_points)
    else:
        avg_freq = 0.0
        warnings.append("无痛点数据，user_demand 保守计分")
    tag_bonus = min(len(motivation_tags), 3) * 10
    if (sentiment.get("neutral") or 0.0) >= 0.999:
        warnings.append("情感为中性占位（无情感测量），user_demand 保守计分")
    score = clamp(avg_freq * 70 + tag_bonus)
    return score, warnings

def score_ip_fit(proposal: dict[str, Any], ip_assessment: dict[str, Any]) -> tuple[float, list[str]]:
    """ip_fit = 提案（名称/概念/IP 引用）与 ip_ranking 的确定性匹配热度。

    rejected=True 的 IP 不得产生正向适配分；未引用已评估 IP → 0 + warning。
    """
    ranking = ip_assessment.get("ip_ranking") or []
    text = f"{proposal.get('name', '')} {proposal.get('concept', '')}"
    for ref in proposal.get("source_map") or []:
        if ref.get("artifact") == "IPAssessment":
            text += f" {ref.get('claim', '')}"

    for cand in ranking:
        ip_name = cand.get("ip_name", "")
        if ip_name and ip_name in text:
            if cand.get("rejected", False):
                return 0.0, [f"IP「{ip_name}」被标记 rejected，ip_fit 为 0"]
            heat = cand.get("heat_score") or 0.0
            return clamp(float(heat)), []
    return 0.0, ["提案未引用任何已评估 IP，ip_fit 保守为 0"]

def score_competition(brand_concentration: dict[str, int]) -> tuple[float, list[str]]:
    """competition = 100 - 品牌数 × 10（品牌越多竞争越激烈，差异化空间越小）。

    可解释的确定性归一化：每个品牌贡献 10 分竞争压力，封顶 10 个品牌。
    """
    if not brand_concentration:
        return 0.0, ["无品牌集中度数据，competition 保守为 0"]
    return clamp(100.0 - len(brand_concentration) * 10.0), []

def score_history_analog(hit_products: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """history_analog = 爆款热度均值（BusinessSummaryView.get_hit_products）。

    无历史爆款参照 → 0 + warning；不把当前趋势热度冒充历史表现。
    """
    if not hit_products:
        return 0.0, ["无历史爆款参照数据，history_analog 保守为 0"]
    avg = sum((p.get("heat_index") or 0.0) for p in hit_products) / len(hit_products)
    return clamp(float(avg)), []

# ── Agent ──────────────────────────

class BusinessEvaluationAgent(BaseAgent):
    """真实商业官：确定性五维评分，不调用 LLM，不编造分数"""

    name = "business_evaluation_agent"
    description = "商业评估：基于三官 Artifact 与商业摘要的五维机会值评分"

    def __init__(self, config: dict | None = None, views: dict[str, Any] | None = None):
        super().__init__(config)
        self.views = views or {}

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        weights = Weights.model_validate(context.get("weights", {}))
        proposal_set = context.get("proposal_set", {})
        feature_matrix = context.get("feature_matrix", {})
        user_sentiment = context.get("user_sentiment", {})
        ip_assessment = context.get("ip_assessment", {})
        upstream = context.get("upstream_confidences", [])
        category = brief.get("category", "")
        weight_map = weights.model_dump()

        view = self.views.get("BusinessSummaryView")
        view_failed = False
        if view is None:
            view_failed = True
            brand_conc, comp_view_warnings = {}, ["BusinessSummaryView 不可用"]
            hit_products, hist_view_warnings = [], ["BusinessSummaryView 不可用"]
        else:
            try:
                brand_conc = view.get_brand_concentration(category)
                hit_products = view.get_hit_products(category)
                comp_view_warnings, hist_view_warnings = [], []
            except (BaseUnavailable, BaseProviderError):
                view_failed = True
                brand_conc, comp_view_warnings = {}, ["商业摘要数据源不可用"]
                hit_products, hist_view_warnings = [], ["商业摘要数据源不可用"]

        # 与 proposal 无关的固定维度
        trend_score, trend_warnings = score_trend_heat(feature_matrix.get("trends") or [])
        demand_score, demand_warnings = score_user_demand(
            user_sentiment.get("pain_points") or [],
            user_sentiment.get("motivation_tags") or [],
            user_sentiment.get("sentiment") or {},
        )
        comp_score, comp_warnings = score_competition(brand_conc)
        hist_score, hist_warnings = score_history_analog(hit_products)

        evidence_refs = self._collect_evidence(feature_matrix, user_sentiment, ip_assessment)
        base_conf = min_confidence(upstream)
        conf, caveats = self._resolve_confidence(base_conf, view_failed, brand_conc, hit_products)

        scores = []
        for proposal in proposal_set.get("proposals", []):
            ip_score, ip_warnings = score_ip_fit(proposal, ip_assessment)
            dims = [
                DimensionScore(
                    dimension="trend_heat", score=trend_score,
                    source_agent="trend_agent", basis=f"趋势峰值热度 {trend_score:.1f}",
                ),
                DimensionScore(
                    dimension="user_demand", score=demand_score,
                    source_agent="consumer_insight_agent", basis=f"痛点频率+动机标签 {demand_score:.1f}",
                ),
                DimensionScore(
                    dimension="ip_fit", score=ip_score,
                    source_agent="ip_strategy_agent", basis=f"IP 匹配热度 {ip_score:.1f}",
                ),
                DimensionScore(
                    dimension="competition", score=comp_score,
                    source_agent="business_evaluation_agent",
                    basis=f"品牌集中度 {len(brand_conc)} 个品牌归一化 {comp_score:.1f}",
                ),
                DimensionScore(
                    dimension="history_analog", score=hist_score,
                    source_agent="business_evaluation_agent", basis=f"爆款热度均值 {hist_score:.1f}",
                ),
            ]

            warnings = self._merge_warnings(
                trend_warnings, demand_warnings, ip_warnings,
                comp_warnings + comp_view_warnings, hist_warnings + hist_view_warnings,
            )
            total = round(sum(d.score * weight_map[d.dimension] for d in dims), 2)

            scores.append(
                OpportunityScore(
                    proposal_name=proposal["name"],
                    dimension_scores=dims,
                    weights_used=weights,
                    total_score=total,
                    star_rating=max(1, min(5, round(total / 20))),
                    risk_warnings=warnings,
                    upstream_confidence=base_conf,
                    evidence_refs=[EvidenceRef(**e) for e in evidence_refs],
                    caveats=caveats,
                    confidence=conf,
                ).model_dump(mode="json")
            )
        return {"opportunity_scores": scores}

    # ── View 读取（异常 → 空 + warning，不伪造） ──────────────────────────

    def _resolve_confidence(
        self,
        base: Confidence,
        view_failed: bool,
        brand_conc: dict[str, int],
        hit_products: list[dict[str, Any]],
    ) -> tuple[Confidence, list[str]]:
        """置信度收口：上游置信度为基础，商业维度证据链不完整时降级。

        - 数据源故障 → caveat + 降级；
        - 品牌集中度缺失 → caveat + 降级；
        - 历史爆款缺失 → caveat + 降级；
        - 仅有聚合数据（缺逐条来源）→ caveat + 降级。
        避免「数据不完整但置信度偏高」。
        """
        conf = base
        caveats: list[str] = []
        if view_failed:
            caveats.append("商业摘要数据源不可用，competition/history_analog 无依据")
        else:
            if not brand_conc:
                caveats.append("品牌集中度数据缺失，competition 无依据")
            if not hit_products:
                caveats.append("历史爆款数据缺失，history_analog 无依据")
            if brand_conc and hit_products:
                caveats.append("competition/history_analog 仅有聚合数据，缺少逐条来源链接")
        if base in (Confidence.HIGH, Confidence.MEDIUM):
            conf = Confidence.LOW
        return conf, caveats

    # ── 证据 / 风险汇总 ──────────────────────────

    def _collect_evidence(
        self,
        feature_matrix: dict[str, Any],
        user_sentiment: dict[str, Any],
        ip_assessment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """只聚合三官 Artifact 的真实证据引用，去重，不伪造 URL"""
        refs: list[dict[str, Any]] = []
        for artifact in (feature_matrix, user_sentiment, ip_assessment):
            for ref in artifact.get("evidence_refs") or []:
                if ref and ref not in refs:
                    refs.append(ref)
        return refs[:5]

    def _merge_warnings(self, *groups: list[str]) -> list[RiskWarning]:
        """把各维度的 warning 字符串映射为带 source_dimension 的 RiskWarning"""
        dims = ["trend_heat", "user_demand", "ip_fit", "competition", "history_analog"]
        warnings: list[RiskWarning] = []
        for dim, group in zip(dims, groups):
            for w in group:
                warnings.append(RiskWarning(risk=w, source_dimension=dim, severity="medium"))
        return warnings


# ══════════════════ LLM 实现：BusinessAgent ══════════════════

# 五维 → 给分来源（与 MockBusinessAgent._DIM_META 一致，单一事实来源）
_DIM_SOURCE: dict[str, str] = {
    "trend_heat": "trend_agent",
    "user_demand": "consumer_insight_agent",
    "ip_fit": "ip_strategy_agent",
    "competition": "business_evaluation_agent",
    "history_analog": "business_evaluation_agent",
}

_OUTPUT_CONTRACT = """
以上为角色与职责说明。本次请以「严格 JSON」输出（不要输出任何解释文字）：

{
  "scores": [
    {
      "proposal_name": "照抄「」内的方案名（不含其他任何文字）",
      "dimensions": {
        "trend_heat":      {"score": 0-100, "basis": "给分依据，必须引用所给材料原句"},
        "user_demand":     {"score": 0-100, "basis": "同上"},
        "ip_fit":          {"score": 0-100, "basis": "同上"},
        "competition":     {"score": 0-100, "basis": "同上"},
        "history_analog":  {"score": 0-100, "basis": "同上"}
      },
      "risk_warnings": [
        {"risk": "风险描述", "source_dimension": "五维之一", "severity": "low/medium/high"}
      ]
    }
  ]
}

打分锚点（rubric）：
  80-100 = 多源强信号交叉验证；60-79 = 单源可信或信号中等；
  40-59 = 信号弱或间接；0-39 = 无支撑或反向信号
要求：
1. 每个输入方案恰好一条，proposal_name 只照抄「」内的方案名
2. 每条 basis 必须引用所给材料（上游情报摘要/证据/质询记录）的原句，
   禁止编造材料没有的数据
3. score 必须是 0-100 的数字——材料不足时按锚点给 0-39 分并在 basis
   注明"无支撑"，禁止输出 null 或文字
4. 你只管打分与依据——总分由代码按权重加权计算，不要输出 total
5. risk_warnings 每方案至多 2 条，没有可给空列表
"""


def _fmt_artifact(title: str, artifact: dict[str, Any] | None) -> str:
    """上游 artifact 压成 prompt 材料（摘要 + 证据条目）"""
    if not artifact:
        return f"【{title}】缺失（记为数据缺口，对应维度按无支撑打分）"
    lines = [f"【{title}】摘要：{artifact.get('summary', '无')}"]
    for ref in artifact.get("evidence_refs", [])[:3]:
        lines.append(f"  · {ref.get('title', '')}：{ref.get('snippet', '')}")
    if artifact.get("caveats"):
        lines.append(f"  保留意见：{'；'.join(artifact['caveats'][:2])}")
    return "\n".join(lines)


class BusinessAgent(BaseAgent):
    """真商业官：LLM 评审打分，代码管算术与置信度，失败回退 Mock"""

    name = "business_evaluation_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._generate, context)
            if result is not None:
                return result
        except Exception:  # noqa: BLE001,S110 — 降级纪律：任何故障回退 Mock
            pass
        require_mock_allowed("商业官 LLM/数据故障回退 Mock")
        return await MockBusinessAgent().run(context)

    def _generate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        from app.engine.llm import complete, load_prompt

        brief = context.get("brief", {})
        weights = Weights.model_validate(context.get("weights", {}))
        weight_map = weights.model_dump()
        proposals = context.get("proposal_set", {}).get("proposals", [])
        if not proposals:
            return None
        upstream = context.get("upstream_confidences", [])
        feedback = (context.get("feedback") or "").strip()

        fm = context.get("feature_matrix")
        us = context.get("user_sentiment")
        ip = context.get("ip_assessment")

        # 材料：brief + 上游情报 + 提案 + 质询记录
        material = [
            (f"【Brief】品类：{brief.get('category', '潮玩')}　"
             f"目标市场：{brief.get('market', 'CN')}　"
             f"预算带：{brief.get('budget_range', 'mid')}"),
            f"【权重】{'/'.join(f'{k}={v}' for k, v in weight_map.items())}",
            "",
            _fmt_artifact("趋势官 FeatureMatrix", fm),
            "",
            _fmt_artifact("用户官 UserSentiment", us),
            "",
            _fmt_artifact("IP 策略官 IPAssessment", ip),
            "",
            "【待评方案】",
        ]
        for p in proposals:
            material.append(
                f"  · 方案「{p.get('name', '')}」：{p.get('concept', '')}"
                f"（形态 {p.get('product_form', '')}，价格带 {p.get('price_band', '')}）"
            )
        challenges = context.get("challenges", [])
        if challenges:
            material.append("\n【质询记录】")
            for c in challenges[:6]:
                material.append(
                    f"  · [{c.get('source_role', '')}/{c.get('stance', '')}] "
                    f"{c.get('proposal_name', '')}：{c.get('content', '')[:80]}"
                )
        # 学习官台账：history_analog 维度的真实材料（飞轮闭环）
        analogs = context.get("history_analogs") or []
        if analogs:
            material.append("\n【历史相似案例】（学习官台账，人决策是最有分量的信号）")
            material.extend(format_analogs(analogs))
        else:
            material.append("\n【历史相似案例】无历史档案——history_analog "
                            "按无支撑打分并在 basis 注明")
        if feedback:
            material.append(f"\n【评委打回意见】{feedback}——本轮必须针对性修正")

        persona_prompt = load_prompt(self.name)
        system = (persona_prompt + "\n" + _OUTPUT_CONTRACT) if persona_prompt else _OUTPUT_CONTRACT
        raw = complete(system, "\n".join(material), temperature=0.3, max_tokens=100_000)
        if not raw:
            return None
        data = parse_llm_json(raw)
        if data is None:
            return None

        # 组装：LLM 分数 + 代码算术；任一方案不合规 → 整体回退
        llm_by_name = {str(s.get("proposal_name", "")): s for s in data.get("scores", [])}
        floor_confidence = min_confidence(upstream)
        scores = []
        for p in proposals:
            name = p.get("name", "")
            s = fuzzy_get(llm_by_name, name)
            if s is None:
                return None
            dims_raw = s.get("dimensions", {})
            dims = []
            for dim_name, source in _DIM_SOURCE.items():
                d = dims_raw.get(dim_name)
                if d is None:
                    return None  # 缺维度 → 整体回退
                try:
                    score = float(d.get("score"))
                except (TypeError, ValueError):
                    return None
                if not 0 <= score <= 100:
                    return None  # 越界 → 整体回退
                basis = str(d.get("basis", "")).strip()
                dims.append({
                    "dimension": dim_name,
                    "score": score,
                    "source_agent": source,
                    "basis": basis or f"{dim_name} 依据材料不足",
                })
            total = round(sum(d["score"] * weight_map[d["dimension"]] for d in dims), 2)

            warnings = []
            for w in s.get("risk_warnings", [])[:2]:
                risk = str(w.get("risk", "")).strip()
                if not risk:
                    continue
                severity = str(w.get("severity", "medium"))
                warnings.append({
                    "risk": risk,
                    "source_dimension": str(w.get("source_dimension", "competition")),
                    "severity": severity if severity in ("low", "medium", "high") else "medium",
                })

            # 证据：从上游三份 artifact 各抽首条（代码抽样，非 LLM 写）
            evidence = []
            for artifact in (fm, us, ip):
                if artifact and artifact.get("evidence_refs"):
                    evidence.append(artifact["evidence_refs"][0])

            scores.append(OpportunityScore(
                proposal_name=name,
                dimension_scores=dims,
                weights_used=weights,
                total_score=total,
                star_rating=max(1, min(5, round(total / 20))),
                risk_warnings=warnings,
                upstream_confidence=floor_confidence,
                evidence_refs=evidence,
                confidence=floor_confidence,
                caveats=[("五维分数为 LLM 评审打分（锚点 rubric 约束），"
                          "总分为代码加权算术，可逐笔复算")],
            ).model_dump(mode="json"))

        return {"opportunity_scores": scores}


# ══════════════════ 注册表 ══════════════════

def get_business_agent_class() -> type[BaseAgent]:
    """注册表三档切换：
    - 默认 / mock → MockBusinessAgent（离线/确定/快）
    - BUSINESS_AGENT_PROVIDER=deterministic → BusinessEvaluationAgent
      （确定性评分：不调用 LLM，分数全部来自 View 聚合与上游 Artifact）
    - BUSINESS_AGENT_PROVIDER=real（或总开关 AGENT_PROVIDER=real）→ BusinessAgent
      （LLM 评审打分，LLM/数据故障时内部回退 Mock）
    注意：注册表在 import 时求值，env 必须在进程启动前设置。
    """
    provider = resolve_provider("商业官", "BUSINESS_AGENT_PROVIDER", ("real", "deterministic"))
    if provider == "real":
        return BusinessAgent
    if provider == "deterministic":
        return BusinessEvaluationAgent
    return MockBusinessAgent
