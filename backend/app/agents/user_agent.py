"""UserAgent — 真用户官：真实消费需求信号 + LLM 洞察归纳

对应剧本 1.2：用户官只看得见需求数据（搜索联想词、热搜），
看不见趋势/IP/成本数据——也不假装看见。

接地数据源（并行拉取，单源故障不拖垮整体）：
  1. 淘宝搜索联想词（TaobaoSuggestConnector.analyze_demand）
     —— 消费者真实购买意图的直接信号，痛点金矿
  2. 微博/百度热搜（按品类词+形态信号过滤）
     —— 公域讨论声量的交叉验证

分工铁律：
  - LLM 只做归纳：痛点描述、动机标签、人群画像、摘要
  - 数字一律代码算：pain_point.frequency = 引用联想词热度 / 最高热度
  - EvidenceRef 只由代码从连接器返回构建（URL/snippet），LLM 不可伪造
  - 情感占比无真实评论源 → LLM 保守估计 + caveats 显式声明估计性质

降级纪律（同 TrendAgent/CreativeAgent）：
  - 数据源全故障 / LLM 未配置 / 输出不合 schema → 回退 MockUserAgent
  - 数据零命中 → 输出 confidence=unknown 的合法 artifact（触发 C5 冲突，
    "无法判断"是剧本允许的诚实输出，不是故障）
  - 注册表切换：默认 Mock，设 USER_AGENT_PROVIDER=real（或总开关
    AGENT_PROVIDER=real）启用
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.mock_agents import MockUserAgent
from app.agents.real_common import parse_llm_json
from app.data.baidu_hot import BaiduHotConnector
from app.data.errors import ConnectorFetchError
from app.data.taobao_suggest import TaobaoSuggestConnector
from app.data.weibo_hot import WeiboHotConnector
from app.engine.strict_mode import require_mock_allowed, resolve_provider
from app.schemas import Confidence, EvidenceRef, UserSentiment

_OUTPUT_CONTRACT = """
以上为角色与职责说明。本次请以「严格 JSON」输出（不要输出任何解释文字）：

{
  "sentiment": {"positive": 0.0-1.0, "neutral": 0.0-1.0, "negative": 0.0-1.0},
  "pain_points": [
    {
      "description": "痛点描述（须能从所给联想词/热搜归纳出来）",
      "severity": "low/medium/high",
      "source_queries": ["该痛点依据的联想词原文，从所给材料中照抄"]
    }
  ],
  "motivation_tags": ["购买动机标签"],
  "persona": "核心人群画像一句话（年龄段+身份+场景）",
  "price_sensitivity": "价格敏感区间及依据",
  "summary": "用户洞察摘要（两三句）",
  "caveats": ["保留意见：样本偏差、反向信号等"]
}

要求：
1. pain_points 至多 3 条，每条必须在 source_queries 里照抄所给材料原文，归纳不出就少给
2. sentiment 三占比之和约等于 1；这是基于联想词语义的保守估计
3. summary 里必须包含 persona 的要点
"""


def _match_heat(source_queries: list[str], suggestions: list[dict[str, Any]]) -> float:
    """痛点引用词 → 命中的最高联想词热度（宽松匹配：互为子串即算命中）"""
    best = 0
    for sq in source_queries:
        sq = sq.strip()
        if not sq:
            continue
        for s in suggestions:
            if sq in s["query"] or s["query"] in sq:
                best = max(best, s["heat"])
    return best


class UserAgent(BaseAgent):
    """真用户官：LLM 做洞察归纳，代码管数字与溯源，失败回退 Mock"""

    name = "consumer_insight_agent"

    def __init__(
        self,
        taobao: TaobaoSuggestConnector | None = None,
        weibo: WeiboHotConnector | None = None,
        baidu: BaiduHotConnector | None = None,
    ):
        self.taobao = taobao or TaobaoSuggestConnector(timeout=6)
        self.weibo = weibo or WeiboHotConnector(timeout=6)
        self.baidu = baidu or BaiduHotConnector(timeout=6)

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._generate, context)
            if result is not None:
                return result
        except Exception:  # noqa: BLE001,S110 — 降级纪律：任何故障回退 Mock
            pass
        require_mock_allowed("用户官 LLM/数据故障回退 Mock")
        return await MockUserAgent().run(context)

    # ── 数据采集（线程内并行，单源故障记 failed_sources）──────

    def _collect(self, category: str) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_taobao = pool.submit(self.taobao.get_suggestions, category)
            f_weibo = pool.submit(self.weibo.get_hot_search)
            f_baidu = pool.submit(self.baidu.get_hot_search)

            suggestions: list[dict[str, Any]] = []
            hot_boards: dict[str, list[dict[str, Any]]] = {}
            failed: list[str] = []

            try:
                suggestions = f_taobao.result()
            except Exception:  # noqa: BLE001 — 连接器约定返回空，此处双保险
                failed.append("taobao")
            for name, fut in (("weibo", f_weibo), ("baidu", f_baidu)):
                try:
                    hot_boards[name] = fut.result()
                except ConnectorFetchError:
                    failed.append(name)

        signals = sorted({
            form
            for s in suggestions
            for form in TaobaoSuggestConnector.FORM_KEYWORDS
            if form in s["query"]
        })
        return {
            "suggestions": suggestions,
            "product_signals": signals,
            "hot_boards": hot_boards,
            "failed": failed,
        }

    # ── 主流程 ─────────────────────────────────────────────

    def _generate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        from app.engine.llm import complete, load_prompt

        brief = context.get("brief", {})
        category = brief.get("category", "潮玩")
        market = brief.get("market", "CN")
        feedback = (context.get("feedback") or "").strip()

        collected = self._collect(category)
        suggestions = collected["suggestions"]
        hot_boards = collected["hot_boards"]
        failed = collected["failed"]

        # 热搜按品类词 + 形态信号过滤
        filter_words = [category, *collected["product_signals"]]
        hot_hits = [
            {"source": name, **item}
            for name, board in hot_boards.items()
            for item in board
            if any(w and w in item["word"] for w in filter_words)
        ]

        # ① 全部数据源故障 → 回退 Mock（故障 ≠ 零命中）
        if failed and not suggestions and not hot_boards:
            return None

        # ② 零命中 → 合法 unknown 输出（C5 冲突由编排层记录）
        if not suggestions and not hot_hits:
            return UserSentiment(
                product_category=category,
                sentiment={"positive": 0.0, "neutral": 1.0, "negative": 0.0},
                pain_points=[],
                motivation_tags=[],
                summary=f"「{category}」在淘宝联想词与微博/百度热搜中均未命中，"
                        "消费需求信号不足，无法判断。",
                evidence_refs=[],
                confidence=Confidence.UNKNOWN,
                caveats=["联想词与热搜双源零命中",
                         "建议补充电商评论抽样或 lengthen 观察窗"],
            ).model_dump(mode="json")

        # ③ 有料 → LLM 归纳
        avg_heat = (
            round(sum(s["heat"] for s in suggestions) / len(suggestions), 1)
            if suggestions else 0
        )
        material = [f"品类：{category}　目标市场：{market}", ""]
        if suggestions:
            material.append(f"【淘宝联想词】共 {len(suggestions)} 条，"
                            f"平均热度 {avg_heat}（0-100 相对值）")
            for s in suggestions[:20]:
                material.append(f"  · {s['query']}（热度 {s['heat']}）")
            if collected["product_signals"]:
                material.append(f"  形态信号：{'、'.join(collected['product_signals'])}")
        if hot_hits:
            material.append("\n【热搜命中】")
            for h in hot_hits[:10]:
                material.append(f"  · [{h['source']}] {h['word']}（热度 {h['heat']}）")
        if failed:
            material.append(f"\n（注：{','.join(failed)} 拉取失败，材料不全）")
        if feedback:
            material.append(f"\n【评委打回意见】{feedback}——本轮必须针对性修正")

        persona_prompt = load_prompt(self.name)
        system = (persona_prompt + "\n" + _OUTPUT_CONTRACT) if persona_prompt else _OUTPUT_CONTRACT
        raw = complete(system, "\n".join(material), temperature=0.5, max_tokens=100_000)
        if not raw:
            return None
        data = parse_llm_json(raw)
        if data is None:
            return None

        # ④ 数字与溯源代码构建
        top_heat = max((s["heat"] for s in suggestions), default=0)
        pain_points = []
        for p in data.get("pain_points", [])[:3]:
            description = str(p.get("description", "")).strip()
            if not description:
                continue
            cited = [str(q) for q in p.get("source_queries", [])]
            heat = _match_heat(cited, suggestions)
            if top_heat and heat == 0:
                continue  # 归纳不出材料依据的痛点，宁缺毋滥
            frequency = round(heat / top_heat, 2) if top_heat else 0.3
            severity = str(p.get("severity", "medium"))
            pain_points.append({
                "description": description,
                "frequency": frequency,
                "severity": severity if severity in ("low", "medium", "high") else "medium",
            })

        def _clamp01(v: Any) -> float:
            try:
                return max(0.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                return 0.0

        sentiment_raw = data.get("sentiment", {})
        sentiment = {
            k: _clamp01(sentiment_raw.get(k, 0))
            for k in ("positive", "neutral", "negative")
        }
        if sum(sentiment.values()) == 0:
            sentiment = {"positive": 0.0, "neutral": 1.0, "negative": 0.0}

        summary = str(data.get("summary", "")).strip()
        if not summary:
            return None
        persona = str(data.get("persona", "")).strip().rstrip("。.")
        if persona and persona not in summary:
            summary = f"{persona}。{summary}"

        # 证据：代码从连接器返回构建（URL 不允许 LLM 写）
        evidence = []
        if suggestions:
            top5 = "、".join(s["query"] for s in suggestions[:5])
            evidence.append(EvidenceRef(
                url=f"https://s.taobao.com/search?q={category}",
                title="淘宝搜索联想词（实时拉取）",
                snippet=f"「{category}」联想词 {len(suggestions)} 条，Top：{top5}"[:200],
            ))
        for h in hot_hits[:3]:
            evidence.append(EvidenceRef(
                url=h.get("url") or "https://s.weibo.com/top/summary",
                title=f"{h['source']}热搜：{h['word'][:30]}",
                snippet=f"热度 {h['heat']}，排名 {h['rank']}"[:200],
            ))

        caveats = [str(c) for c in data.get("caveats", [])][:5]
        caveats.append("情感占比为联想词语义保守估计（未接入评论抽样源）")
        if failed:
            caveats.append(f"数据源 {','.join(failed)} 拉取失败，结论基于部分材料")

        confidence = Confidence.MEDIUM if suggestions else Confidence.LOW
        if suggestions and hot_hits:
            confidence = Confidence.HIGH

        return UserSentiment(
            product_category=category,
            sentiment=sentiment,
            pain_points=pain_points,
            motivation_tags=[str(t) for t in data.get("motivation_tags", [])][:8],
            summary=summary,
            evidence_refs=evidence,
            confidence=confidence,
            caveats=caveats,
        ).model_dump(mode="json")


def get_user_agent_class() -> type[BaseAgent]:
    """注册表三档切换：
    - 默认 / mock → MockUserAgent（离线/确定/快）
    - USER_AGENT_PROVIDER=deterministic → ConsumerInsightAgent
      （确定性聚合：不调用 LLM，信号全部来自 ConsumerDataView）
    - USER_AGENT_PROVIDER=real（或总开关 AGENT_PROVIDER=real）→ UserAgent
      （真实需求信号 + LLM 归纳，数据/LLM 故障时内部回退 Mock）
    注意：注册表在 import 时求值，env 必须在进程启动前设置。
    """
    provider = resolve_provider("用户官", "USER_AGENT_PROVIDER", ("real", "deterministic"))
    if provider == "real":
        return UserAgent
    if provider == "deterministic":
        from app.agents.consumer_agent import ConsumerInsightAgent
        return ConsumerInsightAgent
    return MockUserAgent
