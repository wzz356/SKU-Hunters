"""企划工作室 v2 核心数据结构 — 六步企划管线输入输出契约

对应全景设计文档 v2.0 的业务链路：
    ① PlanBrief（约束）→ ② InsightBundle（五看洞察）→ ③ Opportunity[]（3 张方向卡）
    → ④⑤⑥ PlanCard（创意设计 + 商品策略 + 企划卡组装）

全部模型为 pydantic BaseModel，前端只需认 JSON Schema；
素材替换只改 fixtures.py，管线代码不动。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ══════════════════  ① 企划约束  ══════════════════

class PlanBrief(BaseModel):
    """企划约束输入 — 对应名创「年度品类规划 → 企划案」的约束下达"""

    theme: str = Field(..., description="企划主题，如 2027夏季户外生活系列")
    category: str = Field(..., description="品类，如 小风扇")
    market: str = Field(default="中国大陆", description="目标市场")
    audience: str = Field(default="", description="目标人群")
    price_range: list[float] = Field(default=[39, 99], description="价格带 [下限, 上限]（元）")
    cost_limit: float = Field(default=25, description="成本上限（元），商品策略校验回环用")
    ip_strategy: list[str] = Field(default_factory=list, description="IP 策略，如 ['三丽鸥']")
    launch_window: str = Field(default="", description="上新窗口")
    goals: list[str] = Field(default_factory=list, description="商业目标")
    mode: str = Field(default="fixture", description="数据模式：fixture（默认冻结数据）| live（真实 LLM + 即梦）")


# ══════════════════  ② 五看洞察  ══════════════════

# ── 趋势洞察 ──

class TrendSignal(BaseModel):
    """单条趋势信号"""
    name: str
    metric: str
    period: str
    domains: list[str] = Field(default_factory=list)
    opportunity: str = ""


class HeatCurveSeries(BaseModel):
    """热度曲线单条序列"""
    name: str
    data: list[float]


class HeatCurve(BaseModel):
    """多序列热度曲线"""
    weeks: list[str]
    series: list[HeatCurveSeries]


class TrendRadar(BaseModel):
    """趋势机会雷达 — 趋势洞察 Agent 产物"""
    process_log: list[str] = Field(default_factory=list, description="渐进过程日志")
    signals: list[TrendSignal] = Field(default_factory=list)
    heat_curve: HeatCurve | None = None
    hot_words: list[str] = Field(default_factory=list)


# ── 用户洞察 ──

class PainPoint(BaseModel):
    """用户痛点"""
    text: str
    count: int = 0


class SceneDist(BaseModel):
    """使用场景分布"""
    name: str
    value: int = 0


class UserQuote(BaseModel):
    """用户原句引用"""
    text: str
    source: str = ""


class DecisionUserProfile(BaseModel):
    """用户决策画像 — 服务新品决策，不做人口属性（年龄/性别/职业易幻觉）

    回答「谁在什么场景下做什么任务、为什么买、看什么下单」，
    直接服务企划，而非营销报告。
    """
    user_segment: str = ""                            # 用户群，如 城市通勤人群
    usage_scenario: list[str] = Field(default_factory=list)   # 核心场景
    user_task: list[str] = Field(default_factory=list)        # 使用任务
    purchase_motivation: list[str] = Field(default_factory=list)  # 购买动机
    decision_factors: list[str] = Field(default_factory=list)   # 决策因素


class VoiceEvidenceSource(BaseModel):
    """用户原声证据 — 平台/关键词/数量，代码从采集数据构建，不编造"""
    platform: str = ""                               # 平台（从原声 source / evidence_refs 提取）
    keywords: list[str] = Field(default_factory=list)
    count: int | None = None                         # 数量（采集侧有真实计数才填）


class PainPointChain(BaseModel):
    """痛点归因链：用户原声 → 需求归因 → 产品机会（闭环，可回溯）

    supports_opportunity_ids 引用 opportunityPool 的 id（稳定，不靠文本匹配）。
    """
    priority: int = 0                                # 优先级（越高越值得先解决）
    pain_point: str = ""
    consumer_voice: list[str] = Field(default_factory=list)  # 真实原声
    demand_interpretation: str = ""                  # 需求归因
    supports_opportunity_ids: list[str] = Field(default_factory=list)  # 引用机会池 id
    evidence_source: VoiceEvidenceSource | None = None


class ConsumerVoice(BaseModel):
    """消费者声音 — 用户洞察 Agent 产物"""
    process_log: list[str] = Field(default_factory=list)
    pain_points: list[PainPoint] = Field(default_factory=list)
    scenes: list[SceneDist] = Field(default_factory=list)
    quotes: list[UserQuote] = Field(default_factory=list)
    summary: str = ""
    user_profile: DecisionUserProfile | None = None          # 决策画像（Consumer Voice Agent 二次推理）
    pain_point_chains: list[PainPointChain] = Field(default_factory=list)  # 痛点归因链


# ── 竞品分析 ──

class CompetitorProduct(BaseModel):
    """竞品数据点"""
    name: str
    price: float
    image_url: str = ""        # 竞品商品图（OpenClaw 采集，可对账）
    source: str = ""           # 图片/信息来源（预留，未来接电商/小红书采集；现在空）
    selling_point: str = ""    # 核心卖点/特点
    design: float = Field(ge=0, le=10, description="设计感评分 0-10")


class GapZone(BaseModel):
    """机会空白区"""
    x: list[float] = Field(description="价格区间 [下, 上]")
    y: list[float] = Field(description="设计感区间 [下, 上]")
    label: str = ""


class PriceBand(BaseModel):
    """价格带分布"""
    band: str
    pct: float
    price: str = ""    # 价格区间（采集侧有则填，如 "29-79元"）；缺失 ≠ 0
    note: str = ""     # 定性说明（走量主力/引流款等）


class SellingPoint(BaseModel):
    """卖点关键词 — count 缺失为 None（不知道次数），0 才表示确定 0 次"""
    word: str
    count: int | None = None


class CompetitorNeedScore(BaseModel):
    """竞品 × 需求维度 满足度评分（评分必须绑 reason，不允许裸数字）"""
    competitor: str = Field(description="竞品名（引用真实 products）")
    need: str = Field(description="需求维度")
    score: int = Field(ge=0, le=5)
    reason: list[str] = Field(default_factory=list, description="为什么这个分（真实卖点/用户反馈）")


class OpportunityGap(BaseModel):
    """机会空位 — 机会池的解释层，不重新发现机会

    回答「用户需求 → 当前竞品不足 → 已有机会池方向」，
    supports_opportunity_ids 强绑 opportunityPool 的 id。
    """
    user_need: str = ""
    competitor_gap: str = ""                             # 当前竞品不足/覆盖空白
    opportunity: str = ""                                # 我方机会（对应已有机会池方向）
    supports_opportunity_ids: list[str] = Field(default_factory=list)  # 强绑机会池 id
    why: list[str] = Field(default_factory=list)         # 为什么（趋势/痛点/竞品覆盖证据）


class CompetitiveMap(BaseModel):
    """竞品矩阵 — 竞品分析 Agent 产物"""
    process_log: list[str] = Field(default_factory=list)
    products: list[CompetitorProduct] = Field(default_factory=list)
    gap_zone: GapZone | None = None
    price_bands: list[PriceBand] = Field(default_factory=list)
    selling_points: list[SellingPoint] = Field(default_factory=list)
    need_dimensions: list[str] = Field(default_factory=list)               # 需求维度（来自 decisionFactors）
    need_satisfaction: list[CompetitorNeedScore] = Field(default_factory=list)  # 竞品×需求满足矩阵
    opportunity_gaps: list[OpportunityGap] = Field(default_factory=list)   # 机会空位（验证机会池）


# ── 名创内部 ──

class HitProduct(BaseModel):
    """历史爆品特征"""
    name: str
    index: float = Field(ge=0, le=100, description="爆品指数 0-100")
    factors: list[str] = Field(default_factory=list)
    note: str = ""


class IPPoolItem(BaseModel):
    """IP 资源池条目"""
    name: str
    status: str = ""       # 合作中 | 洽谈中
    heat: str = ""         # ↑ 上升 | → 稳定
    fit: list[str] = Field(default_factory=list)


class InsightBase(BaseModel):
    """名创内部 Insight Base — 策展数据（非 Agent 实时搜）"""
    hit_products: list[HitProduct] = Field(default_factory=list)
    ip_pool: list[IPPoolItem] = Field(default_factory=list)
    design_language: list[str] = Field(default_factory=list)


# ── 流行元素板 ──

class TrendColor(BaseModel):
    """跨品类流行色"""
    name: str
    hex: str = ""
    source: str = ""


class TrendPattern(BaseModel):
    """跨品类流行花纹/图案"""
    name: str
    source: str = ""
    note: str = ""


class TrendShape(BaseModel):
    """跨品类流行形态"""
    name: str
    source: str = ""
    note: str = ""


class TrendExpression(BaseModel):
    """表情语言趋势"""
    name: str
    emoji: str = ""
    note: str = ""


class TrendGallery(BaseModel):
    """流行元素板 — 策展数据（非 Agent 实时搜）"""
    colors: list[TrendColor] = Field(default_factory=list)
    patterns: list[TrendPattern] = Field(default_factory=list)
    shapes: list[TrendShape] = Field(default_factory=list)
    expressions: list[TrendExpression] = Field(default_factory=list)


# ── 洞察增强（Enrichment Layer：五段式驾驶舱数据源）──

class TrendMetric(BaseModel):
    """趋势总览核心指标 — 数字一律代码构建（真实采集计数），LLM 不生成数字"""
    label: str
    value: str
    direction: str = "flat"        # up | down | flat
    note: str = ""


class TopicItem(BaseModel):
    """话题条目 — count 采集侧有真实计数才填，无则 None（前端如实显示）"""
    name: str
    count: int | None = None


class TopicCluster(BaseModel):
    """话题按需求类型聚类（功能/场景/情绪 等，类型由 LLM 判断命名）"""
    type: str
    topics: list[TopicItem] = Field(default_factory=list)


class SubCategoryTrend(BaseModel):
    """子品类/赛道趋势 — records/growth_pct 采集侧无样本量则 None，不编造"""
    name: str
    records: int | None = None     # 样本量（条），采集侧无则 None
    growth_pct: float | None = None  # 同比增速，采集侧无则 None
    momentum: str = "stable"       # surge | rising | stable | emerging
    note: str = ""


class SeasonPhase(BaseModel):
    """上市节奏阶段"""
    phase: str
    months: str
    action: str


class SeasonPlan(BaseModel):
    """季节窗口 · 上市节奏"""
    cycle: list[SeasonPhase] = Field(default_factory=list)
    launch_suggestion: str = ""


class TrendSummary(BaseModel):
    """品类趋势总览 — verdict/keywords 为 LLM 判断，metrics 为代码构建计数"""
    verdict: str = ""
    metrics: list[TrendMetric] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class EnrichmentResult(BaseModel):
    """洞察增强产物 — Insight Enrichment Agent 输出（五段式驾驶舱唯一数据源）

    与 InsightBundle.opportunity_pool 平级：机会池由 Opportunity Discovery 单独产出，
    enrichment 不含机会池，前端统一从 bundle.opportunityPool 消费，禁止二次生成。
    """
    market_judgment: str = ""                       # 顶部 AI 市场判断（一句话战略判断）
    trend_summary: TrendSummary = Field(default_factory=TrendSummary)
    topic_clusters: list[TopicCluster] = Field(default_factory=list)
    sub_category_trends: list[SubCategoryTrend] = Field(default_factory=list)
    season_plan: SeasonPlan = Field(default_factory=SeasonPlan)


# ── 市场机会池（Insight → Decision 的中间产物）──

# 机会来源类型（回答「市场为什么存在这个机会」，而非产品形态分类）
OpportunityType = Literal[
    "design_value",          # 设计价值：颜值/设计语言升级带来的溢价空间
    "scenario_growth",       # 场景增长：新场景/场景扩容带来的增量
    "pain_point_solution",   # 痛点解决：未被满足的高频痛点
    "emotional_consumption", # 情绪消费：情绪价值/社交货币驱动
    "technology_upgrade",    # 技术升级：新技术下放带来的体验跃迁
]


class EvidenceSource(BaseModel):
    """机会判断依据来源 — 回答「为什么推荐该方向」，可回溯到洞察模块"""
    source: str = Field(description="依据类型：trend / consumer / competitor / internal")
    fact: str = Field(description="事实摘要，如 复古风扇讨论同比+132%")


class PoolReasoning(BaseModel):
    """机会推理链：信号 → 解读 → 机会"""
    signal: str = ""
    interpretation: str = ""
    opportunity: str = ""


class OpportunityPoolItem(BaseModel):
    """市场机会池条目 — 洞察驾驶舱 Block5 与机会生成消费同一数据源"""
    id: str = Field(..., description="唯一标识，kebab-case")
    title: str = Field(description="机会方向名，如 复古桌面风扇")
    rank: int = Field(ge=1, description="AI 推荐优先级，1 为最高")
    confidence: int = Field(ge=0, le=100, description="置信度 0-100")
    opportunity_type: OpportunityType
    summary: str = ""
    evidence_source: list[EvidenceSource] = Field(default_factory=list)
    reasoning: list[PoolReasoning] = Field(default_factory=list)


class AssetFit(BaseModel):
    """机会方向 → 商品化适配（IP/设计语言/颜色/材质/包装）

    ip 必须引用 insightBase.ipPool 里的真实名创资产，无则空（不 LLM 自造名创资产）；
    ip_reason 回答「为什么这个机会方向和这个 IP 匹配」，而非「IP 热门/知名度高」。
    """
    opportunity_id: str = Field(description="引用机会池 id")
    ip: str = ""                          # 适配 IP（引用真实 ipPool，无则空）
    ip_reason: str = ""                   # 为什么这个机会方向和这个 IP 匹配
    target_consumer: str = ""             # 目标消费者
    design_language: str = ""             # 设计语言
    color: str = ""                       # 颜色建议
    material: str = ""                    # 材质建议
    packaging: str = ""                   # 包装方向


# ── 洞察汇总 ──

class InsightBundle(BaseModel):
    """五看洞察汇总 — 前端洞察驾驶舱渲染的完整数据

    opportunity_pool 是五看洞察的平级产物（非某一 insight 子模块的字段）：
    趋势/用户/竞品信号共同收敛出的候选机会池，机会生成阶段必须消费它，不二次生成。
    """
    trend_radar: TrendRadar = Field(default_factory=TrendRadar)
    consumer_voice: ConsumerVoice = Field(default_factory=ConsumerVoice)
    competitive_map: CompetitiveMap = Field(default_factory=CompetitiveMap)
    insight_base: InsightBase = Field(default_factory=InsightBase)
    trend_gallery: TrendGallery = Field(default_factory=TrendGallery)
    opportunity_pool: list[OpportunityPoolItem] = Field(default_factory=list)
    enrichment: EnrichmentResult | None = None  # 洞察增强（五段式驾驶舱）；无则前端回退基础视图
    asset_fit: list[AssetFit] = Field(default_factory=list)  # 机会方向 → 商品化适配（Asset Fit Agent）


# ══════════════════  ③ 机会生成  ══════════════════

class EvidenceLink(BaseModel):
    """方向卡依据标签 — 可回溯到洞察模块"""
    source: str = Field(validation_alias="from", description="来源模块：趋势洞察 / 用户洞察 / 竞品分析 / 名创内部 / 流行元素")
    text: str = Field(description="依据摘要")


class Opportunity(BaseModel):
    """单张方向卡 — 由机会池条目展开（市场机会 → 商品机会推理补全）"""
    id: str = Field(..., description="唯一标识，与机会池条目 id 一致")
    emoji: str = ""
    title: str = ""
    direction: str = ""          # 方向标签，如 IP收藏风
    pitch: str = ""              # 一句话卖点
    price_band: str = ""         # 建议价格带，如 59-79 元
    keywords: list[str] = Field(default_factory=list)
    evidence: list[EvidenceLink] = Field(default_factory=list, description="四方依据链")
    # ── 商品机会补全字段（expand_pool_to_cards 推理产出，可选以保证旧数据兼容）──
    opportunity_type: OpportunityType | None = Field(default=None, description="机会来源类型")
    rank: int = Field(default=0, description="机会池排名")
    confidence: int = Field(default=0, description="机会池置信度 0-100")
    target_user: str = ""        # 给谁做
    scenario: str = ""           # 在什么场景使用
    product_strategy: str = ""   # 产品应采取什么策略
    # ── 商品决策卡补全（交叉引用：痛点/竞品空白/资产适配，保持机会池 id 贯穿）──
    pain_point: str = ""         # 用户痛点（引用 consumerVoice.painPointChains）
    competitor_gap: str = ""     # 竞品空白（引用 competitiveMap.opportunityGaps）
    asset_fit: AssetFit | None = None  # IP/设计适配（引用 asset_fit）


# ══════════════════  ④⑤⑥ 新品企划卡  ══════════════════

class PricingInfo(BaseModel):
    """定价信息"""
    price: str = ""              # 如 "59 元"
    reason: str = ""             # 定价理由


class ScheduleItem(BaseModel):
    """上新节奏节点"""
    time: str = ""               # 如 "2027.02"
    action: str = ""


class CostCheck(BaseModel):
    """成本校验结果"""
    passed: bool = False
    price: float | None = None
    cost_limit: float | None = None
    margin: float | None = None
    reason: str = ""


class PlanCard(BaseModel):
    """新品企划卡 — 六步管线最终输出

    包含创意设计（概念/视觉/功能）+ 商品策略（定价/节奏/验证）+ 成本校验。
    以结构化模板组装，非 LLM 自由发挥。
    """
    name: str = ""
    concept_image: str = ""      # 即梦文生图 URL 或本地路径
    concept: str = ""            # 一句话概念
    design_language: str = ""    # 设计语言描述
    keywords: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    fusion: str = ""             # 跨品类融合说明
    pricing: PricingInfo = Field(default_factory=PricingInfo)
    schedule: list[ScheduleItem] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)  # 上市验证指标
    process_log: list[str] = Field(default_factory=list)  # 创意/商品策略思考过程（导师专项：呈现推理过程）
    cost_check: CostCheck | None = None
    opportunity_id: str = ""
    source: str = "fixture"      # fixture | live
    source_plan_id: str = ""     # 复用来源：基于哪张归档企划卡做的企划（plan_id），空为原创


# ══════════════════  新品企划案（Product Proposal，面向评委的六模块呈现）  ══════════════════

class ProposalBackground(BaseModel):
    """① 企划背景：为什么做"""
    market_opportunity: str = ""  # 市场机会
    user_need: str = ""           # 用户需求
    trend_evidence: str = ""      # 趋势证据


class ProposalPositioning(BaseModel):
    """② 商品定位：给谁做"""
    target_user: str = ""
    scenario: str = ""
    price_range: str = ""
    slogan: str = ""              # 一句话定位


class ProposalDesign(BaseModel):
    """③ 产品设计：怎么设计（color/material/designLanguage 来自 AssetFit，不 LLM 随机审美）"""
    concept: str = ""
    design_language: str = ""
    color: str = ""
    material: str = ""
    pattern: str = ""             # LLM 从 designLanguage+color+material 生成，不凭空
    moodboard_prompt: str = ""    # 情绪板 prompt（文本，不额外生图）
    image_url: str = ""           # 概念渲染图（即梦）


class ProposalSpec(BaseModel):
    """④ 功能规格：module → solution"""
    module: str = ""
    solution: str = ""


class ProposalBusiness(BaseModel):
    """⑤ 商业企划：怎么卖（成本/毛利必须来自 cost_check，无真实成本则标注）"""
    cost_target: str = ""         # 成本目标，来自 cost_check；无则「待供应链核算」
    retail_price: str = ""
    sku_strategy: str = ""
    launch_plan: str = ""


class ProposalGrowth(BaseModel):
    """⑥ 增长路径：stage → action"""
    stage: str = ""
    action: str = ""


class ProductProposal(BaseModel):
    """新品企划案 — 面向评委的完整商品方案（消费机会卡 + 资产适配，非新发现流程）"""
    name: str = ""
    opportunity_id: str = ""
    background: ProposalBackground = Field(default_factory=ProposalBackground)
    positioning: ProposalPositioning = Field(default_factory=ProposalPositioning)
    design: ProposalDesign = Field(default_factory=ProposalDesign)
    specification: list[ProposalSpec] = Field(default_factory=list)
    business: ProposalBusiness = Field(default_factory=ProposalBusiness)
    growth_path: list[ProposalGrowth] = Field(default_factory=list)


# ══════════════════  数据看板  ══════════════════

class CategoryRank(BaseModel):
    """品类热度排行"""
    name: str
    heat: float = Field(default=0, ge=0, le=100)


class HotProductRank(BaseModel):
    """热销商品榜"""
    rank: int
    name: str
    price: float
    point: str = ""
    sales: float = 0


class VoiceTrend(BaseModel):
    """社媒声量趋势"""
    weeks: list[str] = Field(default_factory=list)
    xhs: list[float] = Field(default_factory=list)      # 小红书
    douyin: list[float] = Field(default_factory=list)    # 抖音


class DataBoard(BaseModel):
    """数据看板 — 大盘全貌"""
    category_rank: list[CategoryRank] = Field(default_factory=list)
    hot_products: list[HotProductRank] = Field(default_factory=list)
    voice_trend: VoiceTrend | None = None


# ══════════════════  任务列表  ══════════════════

class PlanSummary(BaseModel):
    """企划任务列表项（前端任务中心卡片用）"""
    plan_id: str
    theme: str = ""
    category: str = ""
    audience: str = ""
    status: str = ""             # brief_locked → … → archived
    created_at: str = ""
