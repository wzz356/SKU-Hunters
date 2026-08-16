# SKU-Hunters 前端重构 + 前后端连接修复计划

## Context

项目当前状态：前端接了部分后端真数据，但呈现混乱、机会卡与企划约束脱节、选定机会卡后企划卡/即梦出图链路断裂。需要全量修复数据链路并按 `design/` 文件夹的设计标准重构前端。

---

## 一、问题诊断（已逐行核实代码）

### 根因 1：机会卡完全无视企划约束（"选了迪士尼还是三丽鸥"）
- `backend/app/planning/pipeline.py:199` `_opportunities_from_bundle()` 从不读 `brief["ip_strategy"]`，IP 联名卡永远取 `ipPool[0]`（= 三丽鸥）。
- 无社媒证据的品类（如雨伞）`get_opportunities()` 直接回退 `fixtures.OPPORTUNITIES`——小风扇/库洛米三张卡原样出现在任何品类任务里。
- 前端 `api.js:21-28` 的"原地覆盖 module 常量"反模式：后端数据 mutate 到 `import` 进来的常量对象上，**React 完全不感知、不重渲染**——页面永远显示首屏冻结的小风扇数据。这是"后面机会卡还是 sanliou"的前端侧根因。

### 根因 2：企划卡生成 404，即梦链路断裂
- `pipeline.py:325` `generate_plan_card()` 只认 fixture 三个 id（`ip-collect`/`healing-nature`/`outdoor-clip`）。真实任务的机会卡 id 是 `ip-licensing`/`pain-solution`/`scene-emotion` → `PLAN_TEMPLATES.get()` 返回 None → 404 → 前端 `generatePlanCard()` catch 后静默返回 null → 落回本地小风扇模板。
- 即梦只在 `mode="live"` 调用（`pipeline.py:335`），而前端 `createPlan` 从不传 mode → 即使路径通也永远不出图。
- 后端 `.env` 已配置 `VOLC_ACCESS_KEY_ID/SECRET` 和 `LLM_API_KEY`——即梦和 LLM 实际可用，只是链路没接通。

### 根因 3：前后端契约键名不一致（竞品图空白等）
- `social_evidence.py:148` 输出 `image_url`（snake），前端 `InsightCockpit.jsx:158` 读 `imageUrl` → 竞品图板永远是灰块（真实数据里 9 个竞品都有图 URL）。
- `social_evidence.py:196` trendGallery colors `hex: ""` → 色板空白。
- `social_evidence.py:158` gapZone `x/y: []` → ECharts markArea 异常。
- `pipeline.py:155` heatCurve 快照文件缺失时注入 `None` → 前端 `TREND_RADAR.heatCurve.weeks` 直接抛错。
- `pipeline.py:218` `pb.get("price")` 键不存在 → 机会卡价格带永远 "49-99 元"。

### 根因 4：TaskFlow 用错数据
- `TaskFlow.jsx:59,71-80` 标题和第 0 步约束永远渲染 `DEMO_BRIEF`，不用当前任务的 `plan.brief`。
- `loadInsightsForPlan(id)` fire-and-forget，无 loading/错误态。

### 根因 5：无设计系统
- antd 默认外观直出；紫 `#7a5fd0`/红 `#e60012`/粉紫渐变混用无章法；全部内联样式；卡片套卡片密度过高。
- `design/00_设计目标与参考标准/参考图登记表.md` 已有明确标准未落地：WGSN 大色块、竞品四象限矩阵、证据角标、企划案 WHY→WHAT→HOW→BUSINESS 结构。

### 功能缺口
- 企划卡缺 `design/03_最终企划案` 要求的：Moodboard、功能规格表、SKU 分级、商业化路径图。
- `Home.jsx` STATUS_MAP 需核对后端真实状态机：企划链路落盘状态只有 `brief_locked → insights_ready → opportunities_ready → plan_card_ready → archived` 五种（`running` 仅出现在 aily-create 响应里，非落盘状态）——只映射真实存在的状态，不臆造。

---

## 二、重构方案

### Phase 1：后端契约与管线修复（4 个文件）

**契约总原则（批注 #2）：前端消费契约统一定为 camelCase。** loader 与 fixtures 全部对齐 camelCase；Pydantic schema 走 `_snake_keys` 校验不受影响。键名一致性用契约测试锁住（此前 `schemas/__init__.py` 命名遮蔽曾导致 27 个测试挂掉，属同类坑）。

**`backend/app/insights/loaders/social_evidence.py`**
- `to_competitive_map`：输出 `imageUrl`/`sellingPoint`（camelCase）；gapZone 无坐标时给品类合理默认值（如 x=[30,60], y=[7,10]）。
- `to_trend_gallery`：内置"常见流行色名 → hex"映射表（奶油黄/薄荷绿/樱花粉…），无匹配时用确定性调色板兜底，不再输出空 hex。
- `to_insight_base`：ipPool 的 `fit` 字段保留，供机会卡 IP 匹配用。

**`backend/app/planning/fixtures.py`**
- 竞品 products 字段同步改 camelCase（`image_url`→`imageUrl`、`selling_point`→`sellingPoint`，当前 fixtures 是 snake，只改 loader 会再次错位）。
- 三张冻结企划卡补齐 moodboard/specs/sku_tiers/commercial_path 字段。

**`backend/app/planning/pipeline.py`**
- `_opportunities_from_bundle(category, bundle, brief)`：IP 联名卡优先匹配 `brief["ip_strategy"]`（在 ipPool 中找选中 IP，找不到也用 brief 里的名字生成卡）；修复 price_band 取值 bug。
- `get_opportunities`：生成的机会卡列表存到 `plan["opportunities"]`（供 plan-card 阶段取用）；无证据品类按品类名动态生成机会卡，不再回退小风扇 fixture。
- `generate_plan_card`：fixture 模板命中走原路径；未命中走新 `_build_dynamic_plan_card(plan, opportunity)`——用机会卡 + brief + 洞察 bundle 模板化拼装企划卡（名称/概念/设计语言/功能点/定价/节奏/验证），**无论 mode 都尝试调即梦出图**（`jimeng.generate_concept_image`，AK/SK 未配置或调用失败自动降级占位图，fail-soft 参考 `feishu/bitable_sync.py` 写法），成本校验照跑。
  - **批注 #3（最高风险点）**：`_build_dynamic_plan_card` 先做"下限版本"——字段齐全、过 `PlanCard` 契约、覆盖 moodboard/specs/sku_tiers/commercial_path 四新字段、出图+成本校验通过，再逐步丰满；用契约测试锁住。
- `get_insights`：heatCurve 为 None 时回退 `fixtures.TREND_RADAR["heatCurve"]`，保证契约完整。

**`backend/app/schemas/planning.py`**
- `PlanCard` 增加可选字段：`moodboard`（色卡+材质+图案）、`specs`（功能规格表 list[{module, value}]）、`sku_tiers`（基础款/IP款/限定款）、`commercial_path`（商业化路径阶段 list[{stage, action}]）。

### Phase 2：前端数据层重写（消灭 mutate 反模式）

**`src/api.js`**：全部改为纯 fetch 函数（返回 Promise<data>），删除 `override`/`bootstrapRemoteFixtures`/`loadInsightsForPlan` 的原地覆盖逻辑。保留后端不在线时返回 null 的兜底约定。

**`src/mock/fanData.js`**：保留，仅作后端离线时的兜底数据源（组件 import 常量直接渲染，不再被改写）。

**`src/pages/TaskFlow.jsx`**（核心重写）：
- 进入任务：`getPlan(id)` → setState 存 brief/status；`loadInsights` → setState 存 insights；机会卡、企划卡同理各自 state。
- 每步数据通过 props 传给子组件；加载中 Spin、失败 Empty+重试。
- 标题与第 0 步渲染当前任务真实 brief。
- **批注 #5**：所有读 mock 的组件（InsightCockpit/OpportunityCards/PlanCard/DataBoard/InsightBase/TrendGallery）必须全量迁移到 props 驱动，漏一个就白屏——迁移清单逐个核对。

### Phase 3：前端视觉重构（按 design/ 标准）

**设计 tokens（`src/styles.css` 重写 + `main.jsx` ConfigProvider theme）— 批注 #1：不用纯红白**
- 主色 = 粉紫 `#7A5FD0`，浅紫 `#B7A8F5`，淡紫底 `#F6F3FF`；背景暖灰 `#F7F7F8`，辅助暖灰阶。
- MINISO 红 `#E60012` 仅作**点缀/强调**（状态色带、机会空白标记、关键数字），不大面积铺红白。
- 卡片白底圆角 12、轻阴影；统一字体层级（页标题 20/卡片标题 15/正文 13/辅助 12）；渐变仅保留在概念图占位。

**`App.jsx`**：品牌化侧栏（顶部 logo 块、导航分组：企划流程 / 洞察数据），内容区白底、页面最大宽度约束。

**逐页重构**：
- `Home.jsx`：任务卡片网格（状态色带 + 进度步数）；状态映射只覆盖真实落盘的五种状态（见"功能缺口"条）。
- `NewPlan.jsx`：表单视觉重排（分组卡片：基本信息/商业约束/IP与目标），逻辑不变。
- `InsightCockpit.jsx`：五看模块重排——趋势雷达（信号卡左+折线右+热词云）、用户之声（痛点条形+场景环图+原声 quote-card+总结条）、竞品矩阵（四象限散点+价格带+**真图竞品墙**）、名创资产/流行元素摘要卡。ProcessLog 保留但改为可折叠的一次性顶部条，避免三个模块各自动画占位造成的视觉跳动。
- `OpportunityCards.jsx`：方向卡重排（大卡 + 依据链证据角标 Popover，参考秘塔答案引用样式）；brief 选中的 IP 对应卡片加"契合 IP 策略"标记。
- `PlanCard.jsx`：按企划案六模块重排——①头部（主题/约束条）②概念图（即梦真图，左）+ Moodboard（色卡/材质/图案，右）③设计语言+关键词+功能规格表 ④定价+SKU 分级+成本校验 ⑤上新节奏 Timeline + 商业化路径步骤条 ⑥改稿沟通（保留现有交互，视觉收敛）。
- `DataBoard.jsx`/`InsightBase.jsx`/`TrendGallery.jsx`：统一卡片语言；TrendGallery 色板改 WGSN 式大色块（高 120px+色名叙事）。

### 不做的事
- 不动评审委员会旧链路（`routes.py`、`agents/`）。
- 不引入新依赖（保持 React 18 + antd 5 + echarts）。
- 不改飞书/Aily 集成。

---

## 三、验证方式（批注 #5：分阶段验收，每阶段独立 commit 方便回滚）

**阶段门槛：Phase 1+2 先跑通「保温杯全链路」并变绿，才进入 Phase 3 视觉。**

1. 后端：`cd backend && python -m pytest` 保持现有测试通过；新增/更新契约测试覆盖：动态企划卡路径（`_build_dynamic_plan_card` 下限版本）、camelCase 键名一致性（loader 与 fixtures 对齐）。
2. 起后端 `uvicorn app.main:app --reload`（backend/ 目录）+ 前端 `npm run dev`。
3. 端到端走查：
   - 新建企划：品类=保温杯、IP 策略=迪士尼 → 机会卡①必须是迪士尼联名款（验证约束生效）；
   - 洞察驾驶舱显示保温杯真实数据，竞品 9 张真图可见（验证 camelCase 契约修复）；
   - 选定方向 → 企划卡生成成功（无 404），概念图调即梦（后端日志出现 `CVSync2AsyncSubmitTask` 即为真跑）；
   - 改稿沟通走 LLM 真实回答；归档后任务中心状态正确。
4. 断网兜底：关掉后端，前端用本地 mock 完整走通 demo 任务，无白屏。
