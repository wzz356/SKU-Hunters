"""GTM 官三档实现：Mock（默认）/ GoToMarketAgent（deterministic）/ GTMAgent（real LLM）

对应剧本 3.2：上市国家排序、分批计划、定价、本地化要点（112 国口径）。

三档注册表（与 user/ip/business 官同语义）：
  - 默认 / GTM_AGENT_PROVIDER=mock        → MockGTMAgent（离线快跑）
  - GTM_AGENT_PROVIDER=deterministic      → GoToMarketAgent（确定性、不烧 LLM）
  - GTM_AGENT_PROVIDER=real（或总开关 AGENT_PROVIDER=real）→ GTMAgent（真 LLM）

GoToMarketAgent 纪律（不调用 LLM、不编造）：
  - country 原样使用 brief.market，不扩展、不翻译、不推断；
  - price_band 原样来自 proposal，不换算汇率、不改数字；
  - 无真实排期数据时 batch=1 仅表「候选首批」，timing 固定「待核验」；
  - 缺市场/节日/法规/渠道数据时不生成虚假上市计划，转 deferred + caveat；
  - 数据权限：只读 self.views["GTMMarketView"]，不访问 BaseDataAdapter、其他 View。

GTMAgent 接地数据源（按目标市场切换）：
  - 海外市场 → TikTok Creative Center 话题榜（get_trending_hashtags，
    112 国市场口径；国内网络受限属预期故障）
  - 国内市场（CN）→ 微博/百度热搜按品类词过滤

GTMAgent 分工铁律：
  - LLM 出策略：国家排序/批次/时点/本地化要点/暂缓市场
  - 价格带以提案 price_band 为锚（代码传入，LLM 做当地货币表达）
  - EvidenceRef 只由代码从连接器返回构建

GTMAgent 降级纪律（与其他真 Agent 有一个刻意差异）：
  - 数据源故障 **不回退 Mock**——LLM 仍可基于提案与 Brief 出策略，
    标 confidence=low + caveats 声明（GTM 节点不走证据铁律，合法输出；
    这样 Phase 2 占位官在真模式下始终有真产出）
  - 仅 LLM 未配置/输出不合 schema 才回退 MockGTMAgent
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.mock_agents import MockGTMAgent
from app.agents.real_common import fuzzy_get, parse_llm_json
from app.data.baidu_hot import BaiduHotConnector
from app.data.base_adapter import BaseProviderError, BaseUnavailable
from app.data.errors import ConnectorFetchError
from app.data.tiktok_trends import TiktokTrendsConnector
from app.data.weibo_hot import WeiboHotConnector
from app.engine.decision_engine import min_confidence
from app.engine.strict_mode import require_mock_allowed, resolve_provider
from app.schemas import Confidence, CountryPlan, EvidenceRef, GTMPlan

_OUTPUT_CONTRACT = """
以上为角色与职责说明。本次请以「严格 JSON」输出（不要输出任何解释文字）：

{
  "plans": [
    {
      "proposal_name": "照抄「」内的方案名（不含其他任何文字）",
      "country_plans": [
        {
          "country": "国家/地区码，如 TH/JP/US",
          "batch": 1,
          "price_band": "当地货币价格带（以所给提案价格带为锚换算）",
          "timing": "上市时点，如 首批2周内",
          "rationale": "依据的区域适配证据（引用所给市场材料，或说明为经验判断）"
        }
      ],
      "localization_notes": ["本地化要点，如 日本需礼盒装"],
      "deferred_markets": ["建议暂缓的市场及原因"],
      "dependencies": "批次间依赖说明"
    }
  ]
}

要求：
1. 每个输入方案恰好一条，proposal_name 只照抄「」内的方案名
2. country_plans 1-3 个国家，按批次排序，batch 从 1 开始
3. rationale 优先引用所给市场材料；材料缺失时写清"经验判断"而不是编数据
"""


class GTMAgent(BaseAgent):
    """真全球化官：LLM 出上市策略，代码管证据与置信度，LLM 失败回退 Mock"""

    name = "go_to_market_agent"

    def __init__(
        self,
        tiktok: TiktokTrendsConnector | None = None,
        weibo: WeiboHotConnector | None = None,
        baidu: BaiduHotConnector | None = None,
    ):
        self.tiktok = tiktok or TiktokTrendsConnector(timeout=8)
        self.weibo = weibo or WeiboHotConnector(timeout=6)
        self.baidu = baidu or BaiduHotConnector(timeout=6)

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._generate, context)
            if result is not None:
                return result
        except Exception:  # noqa: BLE001,S110 — 降级纪律：LLM 故障回退 Mock
            pass
        require_mock_allowed("GTM官 LLM/数据故障回退 Mock")
        return await MockGTMAgent().run(context)

    # ── 市场声量采集（故障返回 failed 标记，不抛）─────────────

    def _collect(self, market: str, filter_words: list[str]) -> dict[str, Any]:
        hits: list[dict[str, Any]] = []
        if market == "CN":
            for name, connector in (("weibo", self.weibo), ("baidu", self.baidu)):
                try:
                    hits += [
                        {"source": name, **item}
                        for item in connector.get_hot_search()
                        if any(w and w in item["word"] for w in filter_words)
                    ]
                except ConnectorFetchError:
                    pass  # 单源故障：继续用另一源
            source_label = "微博/百度热搜"
        else:
            try:
                hits = [
                    {"source": "tiktok", **item}
                    for item in self.tiktok.get_trending_hashtags(country_code=market)
                    if any(w and w.lower() in item["word"].lower() for w in filter_words)
                ]
            except ConnectorFetchError:
                pass  # 国内访问 TikTok 受限属预期故障
            source_label = f"TikTok 话题榜（{market}）"
        return {"hits": hits, "source_label": source_label}

    # ── 主流程 ─────────────────────────────────────────────

    def _generate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        from app.engine.llm import complete, load_prompt

        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")
        market = brief.get("market", "CN")
        proposals = context.get("proposal_set", {}).get("proposals", [])
        if not proposals:
            return None

        filter_words = [category]
        collected = self._collect(market, filter_words)
        hits, source_label = collected["hits"], collected["source_label"]
        data_available = bool(hits)

        # 材料：brief + 提案 + 市场声量
        material = [
            (f"【Brief】品类：{category}　目标市场：{market}　"
             f"预算带：{brief.get('budget_range', 'mid')}"),
            "",
            "【待规划方案】",
        ]
        for p in proposals:
            material.append(
                f"  · 方案「{p.get('name', '')}」：{p.get('concept', '')}"
                f"（形态 {p.get('product_form', '')}，"
                f"目标人群 {p.get('target_segment', '')}，"
                f"价格带锚点 {p.get('price_band', '')}）"
            )
        material.append(f"\n【市场声量材料】来源：{source_label}")
        if hits:
            for h in hits[:8]:
                material.append(f"  · {h['word']}（热度 {h['heat']}）")
        else:
            material.append("  （品类词未命中或数据源不可用——按经验判断出策略，"
                            "并在 rationale 中注明）")
        challenges = context.get("challenges", [])
        if challenges:
            material.append("\n【质询记录】")
            for c in challenges[:4]:
                material.append(f"  · {c.get('proposal_name', '')}："
                                f"{c.get('content', '')[:60]}")

        persona_prompt = load_prompt(self.name)
        system = (persona_prompt + "\n" + _OUTPUT_CONTRACT) if persona_prompt else _OUTPUT_CONTRACT
        raw = complete(system, "\n".join(material), temperature=0.3, max_tokens=100_000)
        if not raw:
            return None
        data = parse_llm_json(raw)
        if data is None:
            return None

        # 组装 + schema 强校验；证据代码构建
        evidence = [
            EvidenceRef(
                url=h.get("url") or "https://s.weibo.com/top/summary",
                title=f"{h['source']}：{h['word'][:30]}",
                snippet=f"目标市场声量命中，热度 {h['heat']}"[:200],
            )
            for h in hits[:3]
        ]
        confidence = Confidence.MEDIUM if data_available else Confidence.LOW
        caveats = [] if data_available else [
            f"{source_label} 品类词未命中或不可用，策略为经验判断（confidence=low）"
        ]

        llm_by_name = {str(p.get("proposal_name", "")): p for p in data.get("plans", [])}
        plans = []
        for p in proposals:
            name = p.get("name", "")
            plan = fuzzy_get(llm_by_name, name)
            if plan is None:
                return None  # 缺方案 → 整体回退
            country_plans = []
            for cp in plan.get("country_plans", [])[:3]:
                try:
                    batch = int(cp.get("batch", 1))
                except (TypeError, ValueError):
                    batch = 1
                country_plans.append({
                    "country": str(cp.get("country", market)),
                    "batch": max(1, batch),
                    "price_band": str(cp.get("price_band", "")).strip()
                    or str(p.get("price_band", "")),
                    "timing": str(cp.get("timing", "首批2周内")),
                    "rationale": str(cp.get("rationale", "")).strip() or "经验判断",
                })
            if not country_plans:
                return None
            plans.append(GTMPlan(
                proposal_name=name,
                country_plans=country_plans,
                localization_notes=[str(x) for x in plan.get("localization_notes", [])][:5],
                deferred_markets=[str(x) for x in plan.get("deferred_markets", [])][:5],
                dependencies=str(plan.get("dependencies", "")),
                evidence_refs=evidence,
                confidence=confidence,
                caveats=caveats,
            ).model_dump(mode="json"))

        return {"gtm_plans": plans}


class GoToMarketAgent(BaseAgent):
    """真实 GTM：保守、确定性、证据约束的上市计划"""

    name = "go_to_market_agent"
    description = "GTM 全球化：基于 brief 市场与上游结果的保守上市计划"

    def __init__(self, config: dict | None = None, views: dict[str, Any] | None = None):
        super().__init__(config)
        self.views = views or {}

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        brief = context.get("brief", {})
        proposal_set = context.get("proposal_set", {})
        opportunity_scores = context.get("opportunity_scores") or []
        ip_assessment = context.get("ip_assessment", {})
        category = brief.get("category", "")
        market = brief.get("market", "") or ""

        view = self.views.get("GTMMarketView")
        signals, market_evidence, market_failed = self._get_market(view, category)

        score_map = {s.get("proposal_name"): s for s in opportunity_scores}

        plans = []
        for proposal in proposal_set.get("proposals", []):
            score = score_map.get(proposal.get("name"))
            plans.append(
                self._build_plan(
                    proposal, score, ip_assessment,
                    market, signals, market_evidence, market_failed,
                )
            )
        return {"gtm_plans": plans}

    # ── 市场信号读取（异常 → 空 + failed，不伪造） ──────────────────────────

    def _get_market(self, view: Any, category: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        if view is None:
            return [], [], True
        try:
            result = view.get_market_signals(category)
        except (BaseUnavailable, BaseProviderError):
            return [], [], True
        return (
            result.get("signals") or [],
            result.get("evidence") or [],
            False,
        )

    # ── 单方案 GTMPlan 构造 ──────────────────────────

    def _build_plan(
        self,
        proposal: dict[str, Any],
        score: dict[str, Any] | None,
        ip_assessment: dict[str, Any],
        market: str,
        signals: list[dict[str, Any]],
        market_evidence: list[dict[str, Any]],
        market_failed: bool,
    ) -> dict[str, Any]:
        name = proposal.get("name", "")
        licensing_risk = ip_assessment.get("licensing_risk", "")

        # 证据引用：只来自上游 Artifact / opportunity_score / GTMMarketView 真实引用
        evidence_refs = self._collect_evidence(score, ip_assessment, market_evidence)

        # caveats（覆盖数据缺口）
        caveats: list[str] = []
        if not market:
            caveats.append("缺少目标市场（brief.market 为空）")
        if market_failed:
            caveats.append("市场数据源不可用，无法形成市场依据")
        elif not signals:
            caveats.append("目标品类无市场参照数据")
        caveats.append("渠道/供应链数据未接入")
        if not market_evidence:
            caveats.append("仅有品类聚合数据，缺少逐条来源")
        else:
            caveats.append("缺少区域/节日/法规数据")
        caveats.append("目标市场由 brief 指定，尚未完成区域适配验证")
        if licensing_risk == "待核验":
            caveats.append("IP 授权状态待核验")

        # dependencies
        dependencies = "需核验：目标市场节日/法规/渠道/供应链信息"
        if licensing_risk == "待核验":
            dependencies += "；IP 授权状态"
        if score is None:
            dependencies += "；该方案缺少 opportunity_score"

        # 上游最低置信度（不放大）
        upstream_confs = [ip_assessment.get("confidence", "unknown")]
        if score is not None:
            upstream_confs.append(score.get("confidence", "unknown"))
        upstream_conf = min_confidence(upstream_confs)

        # 是否具备生成上市计划的条件
        can_plan = (
            bool(market)
            and not market_failed
            and bool(signals)
            and score is not None
        )

        # 置信度
        if not can_plan:
            conf = Confidence.UNKNOWN
        else:
            # 仅有品类聚合数据、无逐条来源 → 最多 low；上游 unknown 不升高
            conf = min_confidence([upstream_conf, Confidence.LOW])

        if can_plan:
            country_plans = [
                CountryPlan(
                    country=market,               # 原样 brief.market
                    batch=1,                      # 候选首批，非确认
                    price_band=proposal.get("price_band", ""),  # 原样 proposal
                    timing="待核验",              # 无真实排期数据
                    rationale="品类存在市场参照（聚合信号），区域适配待核验",
                )
            ]
            deferred_markets: list[str] = []
        else:
            country_plans = []
            deferred_markets = [market] if market else []

        localization_notes = ["本地化内容待核验（缺少区域语言/文化/法规数据）"]

        return GTMPlan(
            proposal_name=name,
            country_plans=country_plans,
            localization_notes=localization_notes,
            deferred_markets=deferred_markets,
            dependencies=dependencies,
            evidence_refs=[EvidenceRef(**e) for e in evidence_refs],
            confidence=conf,
            caveats=caveats,
        ).model_dump(mode="json")

    def _collect_evidence(
        self,
        score: dict[str, Any] | None,
        ip_assessment: dict[str, Any],
        market_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """只聚合真实 EvidenceRef，去重，不伪造 URL"""
        refs: list[dict[str, Any]] = []
        sources: list[list[dict[str, Any]]] = [
            (score or {}).get("evidence_refs") or [],
            ip_assessment.get("evidence_refs") or [],
            market_evidence or [],
        ]
        for group in sources:
            for ref in group:
                if ref and ref not in refs:
                    refs.append(ref)
        return refs[:5]


def get_gtm_agent_class() -> type[BaseAgent]:
    """三档注册表：默认 MockGTMAgent（离线/确定/快）；
    GTM_AGENT_PROVIDER=deterministic → GoToMarketAgent（确定性聚合）；
    GTM_AGENT_PROVIDER=real（或总开关 AGENT_PROVIDER=real）→ GTMAgent，
    LLM 故障时内部回退 Mock（数据源故障不回退，降置信度继续出策略）。
    """
    provider = resolve_provider("GTM官", "GTM_AGENT_PROVIDER", ("real", "deterministic"))
    if provider == "real":
        return GTMAgent
    if provider == "deterministic":
        return GoToMarketAgent
    return MockGTMAgent
