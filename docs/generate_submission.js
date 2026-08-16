const path = require('path');
const h = require(path.join(process.env.SKILL_PATH, 'docx', 'scripts', 'docx-helper'))({
  fonts: { heading: 'SimHei', body: 'Microsoft YaHei' },
  colors: { primary: '1A3A5C', accent: '2B7A78', text: '2C2C2C', light: 'F0F4F8' },
  page: { size: 'A4', width: 11906, height: 16838, margins: { top: 1440, bottom: 1440, left: 1440, right: 1440 } },
  spacing: { body: { line: 360, after: 120 } },
  indent: { firstLine: 480 },
});
const C = h.colors;
const refs = h.refTracker();

function sectionTitle(text) {
  return h.h2(text, { spaceBefore: 400, spaceAfter: 200, color: C.primary });
}
function subTitle(text) {
  return h.h3(text, { spaceBefore: 300, spaceAfter: 150, color: C.accent });
}
function bodyText(text) {
  return h.p(text, { size: 22, color: C.text });
}
function bulletText(text) {
  return h.bullet(text, { size: 22, color: C.text });
}

function coverSection() {
  return [
    h.spacer(2000),
    h.p('AI 先锋未来人才大赛', { size: 28, color: 'AABBCC', align: 'center', spacing: { after: 600 } }),
    h.p('名创优品', { size: 20, color: '8899AA', align: 'center', spacing: { after: 400 } }),
    h.spacer(600),
    h.p('SKU Hunters', { size: 56, bold: true, color: 'FFFFFF', align: 'center', spacing: { after: 200 } }),
    h.p('AI Product Committee', { size: 32, color: 'CCDDEE', align: 'center', spacing: { after: 200 } }),
    h.p('AI 商品开发智能决策引擎', { size: 28, color: 'AABBCC', align: 'center', spacing: { after: 1200 } }),
    h.divider({ color: '2B7A78', width: 200 }),
    h.spacer(600),
    h.p('把爆款从"灵光一现"变成"数据可推演的确定选择"', { size: 20, color: '99AABB', align: 'center', italic: true, spacing: { after: 1200 } }),
    h.spacer(800),
    h.p('2026 年 8 月', { size: 22, color: '8899AA', align: 'center' }),
  ];
}

function tocSection() {
  return [
    h.h1('目  录', { align: 'center', color: C.primary, spacing: { after: 400 } }),
    h.toc(),
  ];
}

function chapter1() {
  return [
    sectionTitle('一、参赛方案信息卡'),
    bodyText(''),
    h.table({
      widths: [2000, 8000],
      header: ['项目', '填写内容'],
      rows: [
        ['队名', 'SKU Hunters'],
        ['命题', '名创优品 — AI 驱动的产品开发智能决策引擎'],
        ['一句话摘要', '构建 AI 商品委员会（AI Product Committee），以多 Agent 协同决策模拟商品委员会立项会，将爆款开发从经验驱动升级为数据驱动'],
        ['成员介绍与分工', '详见第四章 团队分工与协作规范'],
        ['使用的飞书 AI 能力', '企业豆包（Agent 推理引擎）、飞书 Aily（工作流编排）、多维表格智能体（商品数据看板）、飞书知识库（RAG 知识底座）、妙记（会议纪要）'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    bodyText('* 本方案已完整上传至 GitHub 开源仓库，遵循 CONTRIBUTING.md 协作规范。'),
  ];
}

function chapter2() {
  return [
    sectionTitle('二、方案成果展示'),
    subTitle('2.1 命题场景描述与痛点分析'),
    bodyText('名创优品作为全球领先的 IP 趣味好物平台，覆盖 112 个国家和地区，全球门店超 8000 家，年上新超 1 万款 SKU。其"711 战略"（每 7 天上 100 款新品）对商品开发效率提出了极高要求，但爆品命中率始终是行业级难题。'),
    bodyText('经过深入调研，我们识别出三大核心痛点：'),
    h.table({
      widths: [1800, 3200, 2000, 2000],
      header: ['痛点', '具体表现', '传统解法', '瓶颈所在'],
      rows: [
        ['趋势难捕捉', 'Z 世代审美、IP 联名热点、海外社媒情绪瞬息万变，传统调研周期长', '人工跨平台搜集报告', '信息滞后，无法实时捕捉'],
        ['选品难决策', '上万 SKU 中哪 100 款值得打版，缺乏结构化决策依据', '依赖商品经理个人经验', '主观性强，不可复制'],
        ['验证反馈慢', '上市后才知爆不爆，错失黄金调整窗口', '上市后复盘总结', '反馈周期长，无法即时反哺'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    bodyText('核心矛盾在于：名创优品拥有全球最丰富的零售数据资产，但数据到决策之间缺少一条自动化的智能管道。商品经理面对海量趋势信号，缺乏有效的结构化分析工具，导致大量时间花在信息搜集而非决策判断上。'),
    subTitle('2.2 方案优势与创新点'),
    bodyText('本方案的核心差异化在于：不是让 AI 帮你干活，而是让 AI 替委员会先开一次会。'),
    bodyText(''),
    subTitle('Before — 传统商品开发模式'),
    bulletText('市场研究员手动搜集趋势 → 制作 PPT 汇报'),
    bulletText('商品策划凭经验撰写方案 → 提交委员会评审'),
    bulletText('委员会每周开会讨论 → 口头决策，缺乏结构化记录'),
    bulletText('上市后靠人工复盘 → 经验流失，难以沉淀'),
    bodyText(''),
    subTitle('After — AI Product Committee 模式'),
    bulletText('趋势官 7x24 自动监控全球社媒 → 产出带证据链的趋势报告'),
    bulletText('创意官综合多方洞察 → 自动生成 3-5 个商品方案，附带溯源'),
    bulletText('商业官 + 全球化官并行评审 → 输出五维机会值评分'),
    bulletText('Decision Engine 综合输出立项建议书 → 商品经理做最终决策'),
    bulletText('学习官持续采集上市数据 → 反哺模型，加速飞轮转动'),
    bodyText(''),
    subTitle('核心创新点'),
    bulletText('机制创新：首次将商品开发流程抽象为 AI 商品委员会协同决策机制，模拟市场、用户、IP、商品、运营等多个岗位共同参与商品立项'),
    bulletText('范式升级：从经验判断向 AI 辅助决策转变，AI 不替代人，而是帮人开好会'),
    bulletText('闭环学习：引入上市后反馈学习机制，形成趋势洞察→商品开发→上市验证→数据反哺的持续优化闭环'),
    bulletText('全球化适配：6 个 Agent 天然支持多区域并行分析，方案从第一天起就是全球化的'),
  ];
}function chapter3() {
  return [
    sectionTitle('三、具体方案说明 — AI Product Committee'),
    subTitle('3.1 整体架构：四层架构'),
    bodyText('本方案构建"数据底座 → AI 商品委员会 → 决策引擎 → 反馈学习"四层架构，形成从趋势洞察到反馈反哺的完整智能闭环。'),
    h.table({
      widths: [1800, 2800, 3200, 1200],
      header: ['层级', '定位', '核心组件', '解决痛点'],
      rows: [
        ['数据底座', '统一接入内外部多源数据', '飞书知识库、历史商品数据、社媒趋势数据、消费者洞察数据', '信息割裂'],
        ['AI 商品委员会', '7 个拟人化 Agent 各司其职', '趋势官、用户官、IP官、创意官、商业官、全球化官', '决策滞后'],
        ['决策引擎', '综合各 Agent 意见输出决策', 'Decision Engine', '决策无依据'],
        ['反馈学习', '采集上市数据持续优化', '学习官（Learning Agent）', '反馈不闭环'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    subTitle('3.2 七位 AI 委员设计'),
    bodyText('每个 Agent 对应名创优品真实业务角色，均有明确的输入、输出和协作关系，确保不是为了多 Agent 而多 Agent。'),
    h.table({
      widths: [1600, 1800, 3200, 2400],
      header: ['AI 委员', '企业对应角色', '核心输出', '解决的问题'],
      rows: [
        ['趋势官', '市场研究总监', '全球趋势报告、趋势热度指数', '趋势难捕捉'],
        ['用户官', '用户研究负责人', '用户画像、痛点清单、购买动机', '不了解消费者'],
        ['IP 官', 'IP 合作经理', 'IP 热度榜、联名推荐、生命周期预测', 'IP 选择困难'],
        ['创意官', '商品策划经理', '3-5 个商品方案（带溯源）', '创意效率低'],
        ['商业官', '财务&商品委员会', '五维机会值评分、推荐等级', '选品难决策'],
        ['全球化官', '海外运营负责人', '上市国家、定价、本地化策略', '全球策略难定'],
        ['学习官', '数据分析负责人', '复盘报告、模型优化、经验沉淀', '反馈不闭环'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    subTitle('3.3 五维机会值评分模型'),
    bodyText('放弃预测爆款这一无法用公开数据验证的目标，改用多维综合评分（Opportunity Score），输出可解释的推荐理由。'),
    h.table({
      widths: [2200, 1200, 5600],
      header: ['评分维度', '权重', '说明'],
      rows: [
        ['趋势热度', '35%', '关键词上升速度、社交讨论量增长'],
        ['用户需求强度', '25%', '评论情绪、痛点密度、搜索意图'],
        ['IP 适配度', '20%', 'IP 热度 x 品类匹配度 x 区域偏好'],
        ['竞争程度', '10%', '同类商品数量、差异化空间'],
        ['历史相似案例', '10%', '相似定位商品的公开表现'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    subTitle('3.4 决策流程：模拟一次立项会'),
    bodyText('本方案不是 AI 推荐一个商品，而是模拟企业真实商品委员会会议的全过程，可解释、可追溯。'),
    h.numbered([
      '第一幕 洞察陈述：趋势官、用户官、IP官并行分析，独立输出洞察，附带证据引用',
      '第二幕 方案提出：创意官综合三方洞察，生成 3-5 个差异化商品方向',
      '第三幕 双轨评审：商业官评估商业机会值，全球化官制定上市策略，互不等待',
      '第四幕 决策输出：Decision Engine 综合评审意见，输出商品立项建议书',
      '第五幕 上市后复盘：学习官采集销量、评价、社媒反馈，反哺模型与知识库',
    ], { ref: 'process' }),
    h.spacer(200),
    subTitle('3.5 证据引用契约（EvidenceRef）'),
    bodyText('所有 Agent 结论必须绑定 EvidenceRef（来源链接、标题、摘要），确保每个结论可追溯、可验证，这是方案区别于黑盒 AI 的关键设计。'),
  ];
}function chapter4() {
  return [
    sectionTitle('四、团队分工与协作规范'),
    subTitle('4.1 三人分工明细'),
    bodyText('基于 AI 商品委员会的四层架构和 DAGents-InsightFlow 的技术积累，将 3 人分工如下：'),
    h.table({
      widths: [1600, 1200, 2400, 1800, 2000],
      header: ['角色', '成员', '核心职责', '负责模块', '交付物'],
      rows: [
        ['组长/架构师', '任星玥', '整体架构设计、Decision Engine 实现、学习官 Agent、工程整合与评审、飞书 AI 集成', 'engine/、agents/learning_agent.py、API 路由、CI/CD、飞书集成', '决策引擎、立项建议书生成器、飞书 Aily 工作流'],
        ['组员A/后端架构', '待定', 'Schema 设计、Analysis Agents 实现（趋势官、用户官、IP官、商业官、全球化官）、数据管道', 'schemas/、agents/趋势/用户/IP/商业/全球化、data/connectors', 'EvidenceRef 契约、四类 Artifact Schema、Agent 代码'],
        ['组员B/后端测试', '待定', 'ReportAgent 实现、ReviewAgent 质量审查、测试体系搭建、文档与演示', 'agents/report_agent.py、agents/review_agent.py、tests/、docs/', '报告生成器、审查流水线、测试覆盖、演示视频'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    subTitle('4.2 协作模式'),
    bodyText('团队采用并行开发 + 周同步的敏捷模式，具体流程如下：'),
    h.numbered([
      'Step 1（全员）：共同确定 EvidenceRef 和四类 Artifact 的字段契约，锁定接口规范',
      'Step 2（并行）：组员A 开发 Schema + Analysis Agents；组员B 用 Mock 数据先写 ReportAgent/ReviewAgent 测试',
      'Step 3（集成）：组长整合各模块，对接 Decision Engine 和飞书 AI 能力',
      'Step 4（迭代）：全员参与测试与调试，完善边缘案例',
      'Step 5（交付）：组长撰写最终方案文档，组员B 剪辑演示视频',
    ], { ref: 'collab' }),
    h.spacer(200),
    subTitle('4.3 GitHub 协作规范'),
    bodyText('仓库地址：https://github.com/sku-hunters/AI-Product-Committee'),
    bodyText(''),
    subTitle('分支策略'),
    h.table({
      widths: [2000, 3000, 4000],
      header: ['分支类型', '命名格式', '示例'],
      rows: [
        ['主分支', 'main', 'main（保护分支，需 PR 审核）'],
        ['开发分支', 'develop', 'develop（日常集成分支）'],
        ['功能分支', 'feat/描述', 'feat/trend-agent'],
        ['修复分支', 'fix/描述', 'fix/evidence-ref-validation'],
        ['文档分支', 'docs/描述', 'docs/api-usage'],
        ['测试分支', 'test/描述', 'test/review-agent'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(100),
    bodyText('Commit 格式：<type>(<scope>): <subject>，如 feat(trend-agent): add TikTok data connector'),
    bodyText('PR 要求：至少 1 人 Review，组长对架构变更拥有最终决定权'),
    bodyText(''),
    subTitle('文件结构'),
    bodyText('SKU-Hunters/ 根目录结构如下：'),
    bulletText('.github/workflows/ — CI/CD 配置（自动测试 + 代码检查）'),
    bulletText('backend/app/agents/ — 7 个 Agent 实现，每个 Agent 一个文件'),
    bulletText('backend/app/schemas/ — Pydantic 数据模型（EvidenceRef 契约）'),
    bulletText('backend/app/engine/ — Decision Engine 核心'),
    bulletText('backend/app/api/ — FastAPI 路由'),
    bulletText('backend/tests/ — 测试用例（与 app/ 结构镜像）'),
    bulletText('docs/ — 架构文档、API 文档、开发指南'),
    bulletText('frontend/ — 前端 Dashboard（可选）'),
    bulletText('CONTRIBUTING.md — 团队协作规范全文'),
    bulletText('README.md — 项目概览与快速开始'),
    h.spacer(200),
    subTitle('4.4 开发节奏'),
    h.table({
      widths: [1600, 3400, 4000],
      header: ['时间', '事项', '产出'],
      rows: [
        ['第 1-2 天', '锁定 EvidenceRef 契约 + 搭建 GitHub 架构', 'Schema 定义、Agent 基类、CI/CD'],
        ['第 3-5 天', 'Analysis Agents 开发 + ReportAgent 测试', 'Agent 代码、测试用例'],
        ['第 6-7 天', 'Decision Engine 集成 + 飞书 AI 对接', '决策引擎、飞书 Aily 工作流'],
        ['第 8-9 天', '全链路联调 + 边缘案例测试', '完整 Demo 运行'],
        ['第 10-12 天', '方案文档撰写 + 演示视频录制', '参赛方案文档、3-5 分钟 Demo'],
        ['第 13-14 天', '打磨优化 + 提交', '最终提交'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
  ];
}function chapter5() {
  return [
    sectionTitle('五、飞书 AI 能力应用'),
    bodyText('本方案深度融入飞书 AI 生态，将飞书从协作工具升级为智能决策平台。以下是各飞书 AI 能力在方案中的具体角色：'),
    h.table({
      widths: [2000, 2800, 4200],
      header: ['飞书 AI 能力', '在方案中的角色', '使用方式'],
      rows: [
        ['企业豆包', '7 个 Agent 的核心推理引擎', '通过飞书开放 API 调用豆包，每个 Agent 配置专属角色提示词，实现趋势分析、创意生成、商业评估等'],
        ['飞书 Aily', '商品委员会工作流可视化编排', '拖拽式搭建洞察→创意→评审→决策工作流，无需编写复杂编排代码，商品经理可直接调整参数'],
        ['多维表格智能体', '商品立项数据看板', '创建商品立项多维表格，智能体进群协作，支持自然语言查询商品状态、机会值评分等'],
        ['飞书知识库', 'RAG 知识底座', '存储历史爆品案例、IP 信息、市场报告，Agent 通过向量检索获取背景知识'],
        ['妙记', '团队协作记录', '周会语音转文字 + AI 摘要，沉淀需求评审纪要'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    subTitle('深度应用亮点'),
    bulletText('飞书 Aily 让 AI 商品委员会从代码走向业务：商品经理无需懂代码，即可在可视化工作流中调整各 Agent 的参数、权重和流程'),
    bulletText('多维表格智能体实现数据活起来：商品从立项到上市的全生命周期状态在表格中流转，智能体自动同步进度并触发评审通知'),
    bulletText('企业豆包作为统一推理引擎，保证 7 个 Agent 的推理能力一致且可管理，同时通过飞书开放的权限体系保障企业数据安全'),
  ];
}

function chapter6() {
  return [
    sectionTitle('六、方案价值'),
    subTitle('6.1 业务价值'),
    h.table({
      widths: [1800, 2600, 2600, 2000],
      header: ['价值维度', 'Before（传统模式）', 'After（本方案）', '量化收益'],
      rows: [
        ['趋势洞察效率', '人工跨平台搜集，3-5 天产出趋势报告', '趋势官 7x24 自动监控，实时产出趋势简报', '时间从 3-5 天缩短至分钟级，效率提升 10 倍以上'],
        ['选品决策质量', '依赖个人经验，主观性强', '五维机会值评分 + 证据链溯源，可解释可验证', '降低误判风险，爆品命中率有望提升'],
        ['方案评审周期', '每周开会评审，人工整理材料', 'Decision Engine 自动生成立项建议书', '评审准备时间减少 80%'],
        ['经验沉淀', '复盘靠人工，经验易流失', '学习官自动沉淀经验至知识库', '团队经验资产持续累积'],
        ['全球化适配', '各国市场分别调研', '全球化官并行分析多区域，输出差异化策略', '多市场并行分析，效率提升显著'],
      ],
      headerColor: C.primary,
      altColor: C.light,
      borders: true,
    }),
    h.spacer(200),
    subTitle('6.2 可落地性与可推广性'),
    bulletText('对名创优品：基于飞书 AI + 公开数据即可起步，后续接入内部 SKU、库存、销售数据后能力进一步增强，不改变现有商品委员会组织架构，即插即用'),
    bulletText('跨行业推广：四层架构（数据底座→多 Agent→决策引擎→反馈学习）具有普适性，可复制到快消、IP 消费品、新消费品牌的产品创新场景'),
    bulletText('技术可验证：采用 MVP 路径，先以 1 个品类（潮玩）+ 3 个核心 Agent 验证可行性，再扩展至全品类、7 个 Agent'),
    h.spacer(200),
    subTitle('6.3 Demo 展示规划'),
    bulletText('场景：模拟东南亚市场新一轮 IP 潮玩产品立项'),
    bulletText('流程：趋势官洞察 → 创意官生成方案 → 商业官/全球化官双轨评审 → Decision Engine 输出立项建议书'),
    bulletText('技术栈：FastAPI 后端 + 企业豆包推理 + 飞书 Aily 工作流 + 多维表格看板'),
  ];
}

h.build({
  sections: [
    { noPageNumber: true, children: coverSection() },
    { ...h.headerFooter('SKU Hunters — AI Product Committee'), children: tocSection() },
    { ...h.headerFooter('SKU Hunters — AI Product Committee'), children: [...chapter1(), ...chapter2(), ...chapter3(), ...chapter4(), ...chapter5(), ...chapter6()] },
  ],
}, [
  { type: 'coverColor', colors: ['1A3A5C', '2B7A78'], direction: 'vertical' },
  { type: 'stripe', evenFill: 'F0F4F8', headerFill: '1A3A5C' },
]);