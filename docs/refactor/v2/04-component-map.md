# 04 · 组件映射（Component Map）v1.1

> 门禁文档 · 定义目标目录结构、组件职责与 props 契约、分包方案。
> v1.1 变更：①API 拆分 client/plans/insights/dashboard；②plans 增加 hooks/usePlanWorkspace；③容器/展示职责收紧；④StateCard 单一 status 枚举；⑤SourceTag/EvidenceRef 契约扩充；⑥lazy 路径修正 + 二级懒加载收缩；⑦补屏幕树/状态所有权/ARIA/测试责任与迁移回滚策略。

---

## 1. 目标目录结构

```
frontend/src/
├─ main.jsx                     # 入口：ConfigProvider + BrowserRouter + AppShell
├─ app/
│  ├─ AppShell.jsx              # 布局：Sider(品牌+分组导航) + Content(Outlet)
│  ├─ router.jsx                # 路由表（React.lazy 路由级分包）
│  └─ theme.js                  # antd ConfigProvider theme（映射 semantic token）
├─ api/
│  ├─ client.js                 # 纯 fetch 封装（BASE、request、错误归一化）
│  ├─ plans.js                  # 企划链路 API（create/list/get/generate-*/revise/archive）
│  ├─ insights.js               # 洞察只读 API（getInsights/getOpportunities）
│  └─ dashboard.js              # 策展数据 API（getDataBoard/getInsightBase/getTrendGallery）
├─ features/
│  ├─ plans/
│  │  ├─ pages/                 # TaskCenter / NewPlan / TaskFlow
│  │  ├─ components/            # TaskCard / PageHeader / RevisionPanel
│  │  └─ hooks/usePlanWorkspace.js   # 状态编排 hook（核心）
│  ├─ insights/                 # InsightCockpit（含 ECharts，懒加载）
│  ├─ opportunities/            # OpportunityCards（普通导入）
│  ├─ plan-card/                # PlanCard（普通导入）
│  └─ dashboard/                # DataBoard / InsightBase / TrendGallery
├─ shared/
│  ├─ components/               # StateCard / SourceTag / EvidenceRef / ProcessLog / ResponsiveChart / NotFound
│  ├─ styles/                   # tokens.css + global.css
│  └─ utils/                    # normalizeBrief 等
└─ fixtures/
   └─ fanData.js                # 离线兜底（仅 demo 用）
```

---

## 2. API 层拆分

| 文件 | 职责 | 导出 |
|------|------|------|
| `client.js` | `BASE`、`request(url, opts)` 纯 fetch，非 2xx throw 结构化错误（`{status, code, message}`） | `request` |
| `plans.js` | 企划链路原子动作与 CRUD | `createPlan`、`listPlans`、`getPlan`、`generateInsights`、`generateOpportunities`、`generatePlanCard`、`revisePlan`、`archivePlan` |
| `insights.js` | 洞察/机会只读（刷新恢复用） | `getInsights`、`getOpportunities` |
| `dashboard.js` | 策展数据页 | `getDataBoard`、`getInsightBase`、`getTrendGallery` |

> 命名对齐 TO-BE 原子动作：`generateInsights` → `POST /plans/{id}/actions/generate-insights`（AS-IS 的 `advancePlan + getInsights` 组合在 Stage 5 改造时废除）。

---

## 3. hooks / usePlanWorkspace（状态编排核心）

`features/plans/hooks/usePlanWorkspace.js` 集中管理 TaskFlow 的全部状态与副作用，页面组件薄壳化。

```js
// 状态所有权：单一 hook 持有，页面组件只读
const workspace = usePlanWorkspace(planId);
// 返回：
{
  plan,            // getPlan 结果（brief/status/plan_card）
  insights,        // 已落盘洞察（只读）
  opportunities,   // 已落盘机会（只读）
  status,          // 后端落盘状态（5 种）
  uiState,         // 'idle' | 'generating' | 'error'（前端瞬时态，不落盘）
  source,          // 数据运行来源：live/snapshot/fixture/demo
  error,           // 结构化错误
  actions: {
    generateInsights,       // POST actions/generate-insights
    generateOpportunities,  // POST actions/generate-opportunities
    generatePlanCard,       // POST actions/generate-plan-card(opportunity_id)
    revise,                 // POST /revise
    archive,                // POST actions/archive
    reload,                 // 刷新恢复：GET 只读接口
  }
}
```

**职责边界**：
- **容器（hook / 页面编排层）**：持有状态、发请求、处理错误与重试、推进 step。
- **展示组件**：只接收 props（数据）与事件回调（onXxx），不 import fixtures、不发请求。

---

## 4. 组件 → 职责 → props 契约

### 4.1 app 层

| 组件 | 职责 | 依赖 |
|------|------|------|
| `AppShell.jsx` | Sider 品牌块 + 分组导航 + Content `<Outlet/>` | `useLocation` 算 selectedKey |
| `router.jsx` | 路由表（React.lazy） | — |
| `theme.js` | antd theme token（映射 semantic token） | — |

### 4.2 features/plans

| 组件 | 职责 | props |
|------|------|-------|
| `pages/TaskCenter.jsx` | 任务列表（进行中/归档） | 内部 `listPlans()`；复用 `TaskCard` |
| `pages/NewPlan.jsx` | 企划约束表单 | 内部 `createPlan()` |
| `pages/TaskFlow.jsx` | 4 步流程编排（薄壳） | 用 `usePlanWorkspace(id)`，把数据/回调传给子 feature |
| `components/TaskCard.jsx` | 单任务卡 | `task`、`onClick` |
| `components/PageHeader.jsx` | 页面标题区 + 主 CTA 槽 | `title`、`subtitle`、`extra` |
| `components/RevisionPanel.jsx` | 改稿沟通面板（多轮对话） | `logs[]`、`onRevise(message)`、`disabled` |
| `hooks/usePlanWorkspace.js` | 状态编排 | 见第 3 节 |

### 4.3 features/insights

| 组件 | 职责 | props |
|------|------|-------|
| `InsightCockpit.jsx` | 五看洞察五模块 | `insights`（bundle） |

### 4.4 features/opportunities

| 组件 | 职责 | props |
|------|------|-------|
| `OpportunityCards.jsx` | 3 张方向卡 + 证据角标 + 契合 IP 标记 | `opportunities[]`、`selected`、`onSelect(id)`、`processLog[]` |

### 4.5 features/plan-card

| 组件 | 职责 | props |
|------|------|-------|
| `PlanCard.jsx` | 企划案六模块 | `planCard`、`opportunity`、`brief`、`onGenerate(opportunityId)`、`onRevise(message)`、`onArchive()`、`uiState` |

> **关键修正**：`PlanCard` **不再接收 `planId` 自己发请求**，改为接收 `onGenerate/onRevise/onArchive` 事件回调，由容器（hook）执行请求。

### 4.6 features/dashboard

| 组件 | 职责 | props |
|------|------|-------|
| `DataBoard.jsx` | 品类大盘 | 内部 `getDataBoard()` |
| `InsightBase.jsx` | 历史爆品 / IP 库 / 设计语言 | 内部 `getInsightBase()` |
| `TrendGallery.jsx` | 配色/花纹/形态/表情化 | 内部 `getTrendGallery()` |

### 4.7 shared/components（通用）

| 组件 | 职责 | props |
|------|------|-------|
| `StateCard.jsx` | 统一状态封装 | `status`（见下）、`onRetry`、`emptyText`、`children` |
| `SourceTag.jsx` | 数据来源标识 | `runSource`（运行来源）、`evidenceType`（证据类型，可选） |
| `EvidenceRef.jsx` | 证据角标 + 来源 Popover | 见第 5.3 节契约 |
| `ProcessLog.jsx` | 折叠式过程日志条 | `log[]`、`title` |
| `ResponsiveChart.jsx` | ECharts 响应式封装 | `option`、`height`、`ariaLabel`、`summary` |
| `NotFound.jsx` | 404 页 | — |

---

## 5. 关键契约

### 5.1 StateCard —— 单一 status 枚举（非多布尔）

```js
// 禁止 loading/error/empty 三个布尔并存（会产生冲突态）
status: 'idle' | 'loading' | 'success' | 'empty' | 'error'
```

| status | 渲染 |
|--------|------|
| idle | 占位（不渲染数据区） |
| loading | Spin |
| success | children（数据内容） |
| empty | Empty + emptyText |
| error | Alert + onRetry 重试按钮 |

### 5.2 SourceTag —— 区分两类来源

```js
// ① 数据运行来源（怎么产生的数据）
runSource: 'live' | 'snapshot' | 'fixture' | 'demo'
// ② 证据类型（数据来自哪类系统）
evidenceType: 'local_kb' | 'warehouse' | 'rule' | 'external'
```

- `runSource`：live（实时 LLM/即梦）· snapshot（冻结快照）· fixture（冻结 fixture）· demo（演示兜底）。
- `evidenceType`：local_kb（名创内部知识库）· warehouse（电商数据仓库）· rule（规则推导）· external（外部社媒/趋势）。
- 二者可叠加（如「snapshot + external」）。

### 5.3 EvidenceRef —— 扩充契约

```js
{
  id: string,           // 证据唯一标识
  type: string,         // 证据类型（local_kb/warehouse/rule/external）
  title: string,        // 证据标题
  domain: string,       // 来源域（如「小红书」「抖音」「名创内部库」）
  url: string,          // 来源链接
  retrievedAt: string,  // 抓取时间（ISO）
  version: string,      // 数据版本
  reviewedAt: string,   // 人工复核时间
}
```

---

## 6. 数据流契约

```
usePlanWorkspace（容器 hook：状态 + 请求 + 错误处理）
   │ 持有 { plan, insights, opportunities, status, uiState, source, error }
   ├─→ InsightCockpit   (props: insights)
   ├─→ OpportunityCards (props: opportunities, selected, onSelect, processLog)
   └─→ PlanCard         (props: planCard, opportunity, brief, onGenerate, onRevise, onArchive)
```

**红线**：
- 展示组件只读 props + 触发事件回调，不 import fixtures、不发请求。
- 请求收敛在 `usePlanWorkspace`（企划链路）或 dashboard 页面组件（策展数据）。
- `api/*.js` 纯函数，失败 throw，调用方用 `StateCard` 处理状态。

---

## 7. 屏幕树 / 状态所有权 / 焦点 / ARIA

| 关注点 | 约定 |
|--------|------|
| 屏幕树 | 每页根节点 `<main>`，页面标题 `h1`，模块标题 `h2/h3`，符合语义层级 |
| 状态所有权 | 企划链路状态归 `usePlanWorkspace`；dashboard 三页各自独立 useState，不共享 |
| 焦点管理 | 步骤切换后焦点移到新步骤标题（`ref.focus()`）；弹窗打开焦点进弹窗，关闭回触发元素 |
| ARIA / live region | 生成中状态用 `aria-busy="true"`；生成结果/错误用 `role="status"` / `role="alert"` 播报；图表用 `aria-label` + 可见 caption |
| 键盘 | 可点击卡片 `tabIndex=0` + `Enter/Space`；证据角标可 Tab 聚焦并 `Enter` 弹出 |

---

## 8. current token → target semantic token 映射

| 当前代码内联值 | 目标 semantic token |
|---------------|---------------------|
| `#7a5fd0`（主色/选中/进度） | `--color-action-primary` |
| `#b7a8f5`（色带/浅紫装饰） | `--purple-400`（仅装饰） |
| `#e60012`（红点缀） | `--color-brand-accent` |
| `#faf8ff`（quote-card 底） | `--color-surface-alt` |
| `#f5f5f5`（Content 底） | `--color-bg`（暖灰 `#F7F7F8`） |
| `#fff`（卡片底） | `--color-surface` |
| `#262626`（主文本） | `--color-text` |
| `#595959` / `#666`（次文本） | `--color-text-secondary` |
| `#888` / `#999`（辅助/时间戳） | `--color-text-muted`（`#6B6B6B`，禁 `#8C8C8C`） |
| `#5a4a6a`（色板文字） | 大字装饰色，可保留或 `--color-text-secondary` |

---

## 9. React.lazy 分包（收缩版）

**路由级 lazy（保留）** —— `app/router.jsx`：

```js
// app/router.jsx 位于 src/app/，features 在 src/features/，故用 ../features/...
const TaskCenter   = lazy(() => import('../features/plans/pages/TaskCenter'));
const NewPlan      = lazy(() => import('../features/plans/pages/NewPlan'));
const TaskFlow     = lazy(() => import('../features/plans/pages/TaskFlow'));
const DataBoard    = lazy(() => import('../features/dashboard/DataBoard'));
const InsightBase  = lazy(() => import('../features/dashboard/InsightBase'));
const TrendGallery = lazy(() => import('../features/dashboard/TrendGallery'));
```

**流程内二级懒加载（仅重模块）** —— `features/plans/pages/TaskFlow.jsx`：

```js
// TaskFlow 在 features/plans/pages/，insights 在 features/insights/，故用 ../../insights/...
const InsightCockpit = lazy(() => import('../../insights/InsightCockpit'));  // 含 ECharts，懒加载
// 以下普通导入（非懒加载）
import OpportunityCards from '../../opportunities/OpportunityCards';
import PlanCard from '../../plan-card/PlanCard';
```

| 模块 | 分包策略 | 理由 |
|------|---------|------|
| `InsightCockpit` | 懒加载 | 含 ECharts，实测重模块 |
| `DataBoard` | 路由级已够 | 不再内部二级懒加载 |
| `OpportunityCards` | 普通导入 | 轻量 |
| `PlanCard` | 普通导入 | 先普通导入，除非构建分析证明明显偏大 |

**实测报告（实施后必须输出，不写「预计」）**：

```
入口包大小      : ___ kB
ECharts chunk   : ___ kB
TaskFlow chunk  : ___ kB
gzip 后总大小   : ___ kB
```

---

## 10. 代表性垂直切片（TaskFlow 洞察步骤）

以「TaskFlow 从 step 0 → step 1」为代表性切片，验证整条链路的契约：

```
TaskFlow(step0) 点击「开始洞察分析」
  → usePlanWorkspace.actions.generateInsights()
  → api/plans.js → POST /actions/generate-insights
  → 后端生成 + 落盘 + 状态→insights_ready + 返回 {status, insights}
  → hook 更新 { status, insights, uiState }
  → 渲染 InsightCockpit(insights)  +  SourceTag(runSource)
  → 图表 ResponsiveChart 响应式 resize + aria-label
  → 失败：StateCard(status='error') + onRetry
```

此切片覆盖：容器 hook、API 层、展示组件 props 契约、状态枚举、来源标识、图表可访问性、错误恢复——作为首个落地与验收单元。

---

## 11. 测试责任

| 层 | 测试责任 | 工具 |
|----|---------|------|
| `api/` | 请求封装：错误归一化、非 2xx throw、camelCase 契约 | 单测（mock fetch） |
| `hooks/usePlanWorkspace` | 状态流转：idle→generating→success/error、恢复、幂等 | 单测（renderHook） |
| `shared/components` | StateCard 五态、SourceTag 映射、EvidenceRef 契约、ResponsiveChart 摘要 | 组件测试 |
| `features/*` | 每个 feature 的展示组件 props 渲染 + 空态/长文本 | 组件测试 |
| 垂直切片 | TaskFlow 洞察步骤端到端（生成→渲染→失败→重试） | 集成测试 |

---

## 12. 兼容 / 迁移 / 回滚策略

- **兼容**：AS-IS 的 `api.js`（`advancePlan + getInsights`）在 Stage 5 先保留，新增 `api/plans.js` 的原子动作函数，双轨并存至前端切完再删旧。
- **迁移**：按第 10 节垂直切片先行，跑通后再逐 feature 迁移（dashboard → insights → opportunities → plan-card → plans），每迁一个跑 `npm run build` + 冒烟。
- **回滚**：每个 feature 迁移独立 commit；若某 feature 白屏，`git revert` 该 commit 即可，不影响其他 feature。
- **红线**：迁移期间不删除 `mock/fanData.js`（改名 `fixtures/fanData.js`），保留 demo 兜底。

---

## 13. 迁移清单（当前 → 目标）

| 当前文件 | 目标文件 | 动作 |
|---------|---------|------|
| `main.jsx` | `main.jsx` | 引入 AppShell + router + theme |
| `App.jsx` | `app/AppShell.jsx` + `app/router.jsx` | 拆布局/路由 |
| `api.js` | `api/{client,plans,insights,dashboard}.js` | 拆分 |
| `pages/TaskFlow.jsx` | `features/plans/pages/TaskFlow.jsx` + `hooks/usePlanWorkspace.js` | 拆编排 hook |
| `pages/Home.jsx` | `features/plans/pages/TaskCenter.jsx` | 迁移 |
| `pages/NewPlan.jsx` | `features/plans/pages/NewPlan.jsx` | 迁移 |
| `pages/DataBoard/InsightBase/TrendGallery.jsx` | `features/dashboard/*` | 迁移 |
| `components/InsightCockpit.jsx` | `features/insights/InsightCockpit.jsx` | 迁移 |
| `components/OpportunityCards.jsx` | `features/opportunities/OpportunityCards.jsx` | 迁移 |
| `components/PlanCard.jsx` | `features/plan-card/PlanCard.jsx` | 迁移 + 改事件回调契约 |
| `components/ProcessLog.jsx` | `shared/components/ProcessLog.jsx` | 迁移 |
| `mock/fanData.js` | `fixtures/fanData.js` | 迁移 |
| `styles.css` | `shared/styles/{tokens,global}.css` | 重写 |
| —（新增） | `shared/components/{StateCard,SourceTag,EvidenceRef,ResponsiveChart,NotFound}.jsx` | 新建 |
| —（新增） | `features/plans/components/{TaskCard,PageHeader,RevisionPanel}.jsx` | 新建 |
