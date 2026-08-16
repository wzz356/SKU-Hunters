"""CreativeAgent — 真创意官：LLM 基于三方情报生成互异方案

对应剧本 2.2：创意官只见三方 Artifact（摘要+证据），不见原始数据；
LLM 负责创意本身，source_map 由代码从真实 Artifact 构建——溯源不允许自由发挥。

降级纪律（同 TrendAgent）：
- LLM 未配置 / 调用失败 / 输出不合 schema → 回退 MockCreativeAgent，会议不阻塞
- 注册表切换：默认 Mock（离线/确定/快），设 CREATIVE_AGENT_PROVIDER=real 启用
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.creative_contract import ContractError, validate_proposals
from app.agents.mock_agents import MockCreativeAgent
from app.engine.ledger import format_analogs
from app.engine.strict_mode import require_mock_allowed, resolve_provider
from app.schemas import ProposalSet, SourceRef

# 预算带 → 建议价格带（名创优品实际价位段）
_BUDGET_BAND = {
    "low": "¥9.9-29",
    "mid": "¥29-69",
    "high": "¥69-149",
}

_SYSTEM_PROMPT = """你是名创优品的商品创意官，正在商品评审委员会上提出新品方案。

铁律：
1. 恰好输出 3 个方案，三方案在「形态/场景/价位」上至少两维互异
2. 每个方案必须能溯源到所给情报——不允许编造情报里没有的趋势、人群或 IP
3. 用户提供的候选 IP/方向池必须优先使用；池子为空才从 IP 官情报里选
4. 价格带必须落在 Brief 预算区间内
5. 只输出 JSON，不要输出任何解释文字

输出格式（严格 JSON）：
{
  "proposals": [
    {
      "name": "方案名（含品类词）",
      "concept": "一句话概念：什么 IP/设计 + 什么形态 + 解决什么场景痛点",
      "product_form": "商品形态，如 摆件/挂件/收纳/盲盒/香薰",
      "target_segment": "目标人群，具体到年龄+身份+场景",
      "price_band": "价格带，如 ¥39-59",
      "differentiation": "与另外两个方案的差异点"
    }
  ],
  "ideation_note": "方案陈述与保留意见（一两句）"
}"""


def _fmt_artifact(title: str, artifact: dict[str, Any] | None) -> str:
    """把一份 Artifact 压成 prompt 用的一段文字：摘要 + 证据条目"""
    if not artifact:
        return f"【{title}】缺失（记为数据缺口，不要编造）"
    lines = [f"【{title}】摘要：{artifact.get('summary', '无')}"]
    for ref in artifact.get("evidence_refs", [])[:5]:
        lines.append(f"  · {ref.get('title', '')}：{ref.get('snippet', '')}")
    return "\n".join(lines)


def _source_map(
    feature_matrix: dict[str, Any] | None,
    user_sentiment: dict[str, Any] | None,
    ip_assessment: dict[str, Any] | None,
) -> list[SourceRef]:
    """从真实 Artifact 构建溯源映射（硬校验 2：三方各至少一条）"""
    refs: list[SourceRef] = []
    if feature_matrix:
        refs.append(SourceRef(
            artifact="FeatureMatrix",
            claim=(feature_matrix.get("summary") or "趋势情报")[:80],
            supports="形态与趋势依据",
        ))
    if user_sentiment:
        refs.append(SourceRef(
            artifact="UserSentiment",
            claim=(user_sentiment.get("summary") or "用户情报")[:80],
            supports="人群与场景",
        ))
    if ip_assessment:
        top = (ip_assessment.get("ip_ranking") or [{}])[0]
        refs.append(SourceRef(
            artifact="IPAssessment",
            claim=f"首选 IP：{top.get('ip_name', '无')}"
                  f"（热度 {top.get('heat_score', 0)}，窗口期 {top.get('window_estimate', '-')}）",
            supports="IP 选择",
        ))
    return refs


_MAX_RETRIES = 3


class _NoLLM(Exception):
    """LLM 未配置或调用失败（触发 fail-soft 降级到 Mock）"""


class CreativeAgent(BaseAgent):
    """真创意官：LLM 出创意，代码管溯源与校验；契约失败重试，重试仍失败抛 ContractError"""

    name = "product_ideation_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        last_error: ContractError | None = None
        for _ in range(_MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._generate, context)
            except _NoLLM:
                break  # 无 Key / LLM 故障 → 降级 Mock（fail-soft 保留）
            except ContractError as e:
                last_error = e
                continue  # 输出不合契约 → 重新生成重试
            except Exception:  # noqa: BLE001 — 其他故障降级 Mock
                break
        if last_error is not None:
            raise last_error  # 重试仍失败 → 明确 ContractError
        # 降级 Mock：仅非严格模式可达；严格模式在此阻断（LLM 失败即抛错）
        require_mock_allowed("创意官 LLM 故障回退 Mock")
        mock_result = await MockCreativeAgent().run(context)
        validate_proposals(
            mock_result.get("proposals", []),
            context.get("brief", {}),
            context.get("feature_matrix"),
            context.get("user_sentiment"),
            context.get("ip_assessment"),
        )
        return mock_result

    def _generate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        from app.engine.llm import complete

        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")
        market = brief.get("market", "CN")
        budget = brief.get("budget_range", "mid")
        pool = brief.get("candidate_pool") or []
        feedback = (context.get("feedback") or "").strip()

        fm = context.get("feature_matrix")
        us = context.get("user_sentiment")
        ip = context.get("ip_assessment")

        user_prompt = f"""【Brief】
品类：{category}　目标市场：{market}　预算带：{budget}（建议价格带 {_BUDGET_BAND.get(budget, _BUDGET_BAND['mid'])}）
候选 IP/方向池：{"、".join(pool) if pool else "（空，从 IP 官情报中选择）"}

【三方情报】
{_fmt_artifact('趋势官 FeatureMatrix', fm)}

{_fmt_artifact('用户官 UserSentiment', us)}

{_fmt_artifact('IP 策略官 IPAssessment', ip)}
"""
        if feedback:
            user_prompt += f"\n【评委打回意见】上一轮方案被打回，意见：{feedback}——本轮必须针对性修正\n"

        # 学习官台账：历史案例做负例（被否/低分方案避免重复提案）
        analogs = context.get("history_analogs") or []
        if analogs:
            user_prompt += (
                "\n【历史教训】学习官台账中的同品类过往案例——"
                "被否或低分的方案不要换皮重提，通过的可借鉴其形态/场景选择：\n"
                + "\n".join(format_analogs(analogs)) + "\n"
            )

        raw = complete(_SYSTEM_PROMPT, user_prompt, temperature=0.8, max_tokens=100_000)
        if not raw:
            raise _NoLLM()

        data = self._parse_json(raw)
        if data is None:
            raise ContractError("LLM 输出无法解析为 JSON")

        refs = _source_map(fm, us, ip)
        proposals = []
        for p in data.get("proposals", []):
            proposals.append({
                "name": str(p.get("name", "")).strip(),
                "concept": str(p.get("concept", "")).strip(),
                "product_form": str(p.get("product_form", "")).strip(),
                "target_segment": str(p.get("target_segment", "")).strip(),
                "price_band": str(p.get("price_band", "")).strip(),
                "differentiation": str(p.get("differentiation", "")).strip(),
                "source_map": [r.model_dump() for r in refs],
                "evidence_refs": [],
                "confidence": "medium",
            })
        if len(proposals) < 3 or any(not p["name"] or not p["concept"] for p in proposals):
            raise ContractError("方案数量不足 3 个或字段为空")

        # 四项契约校验：source_map 覆盖 / 方案互异 / 价格带预算 / product_form 依据
        validate_proposals(proposals, brief, fm, us, ip)

        return ProposalSet.model_validate({
            "proposals": proposals[:5],
            "ideation_note": str(data.get("ideation_note", "")),
        }).model_dump(mode="json")

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        """容错解析：剥代码围栏、截取首个 JSON 对象"""
        text = re.sub(r"```(?:json)?|```", "", raw).strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None


def get_creative_agent_class() -> type[BaseAgent]:
    """注册表切换：默认 MockCreativeAgent（离线/确定/快）；
    设 CREATIVE_AGENT_PROVIDER=real 时返回真 CreativeAgent（LLM 故障时内部回退 Mock）。
    """
    provider = resolve_provider("创意官", "CREATIVE_AGENT_PROVIDER")
    if provider == "real":
        return CreativeAgent
    return MockCreativeAgent
