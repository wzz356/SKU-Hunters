# 03 · 视觉基础（Visual Foundations）v2.0

> 门禁文档 · 定义三层设计 token 与可访问性红线。
> v2.0 变更（Stage 6 定稿）：①所有颜色值 / 圆角 / 阴影从 provisional 转为最终值；②新增图表色板、聊天气泡、成本校验、证据、强调面板、方向卡渐变等 component token；③新增 `--color-section-label` 语义 token 并修复 11px 小字对比度；④记录 ECharts Canvas 不识别 CSS 变量的修复方案（`readCssVar`）；⑤附 Stage 6 migration/QA 说明与代表性截图。

---

## 1. 设计原则

1. **不用纯红白**：MINISO 红只做品牌点缀，不铺大面积红白。
2. **品牌红 ≠ 错误红**：品牌红 `#E60012` 与错误语义 `#FF4D4F` 严格分离，不得混用。
3. **卡片白底 + 轻阴影**，内容区暖灰底，密度克制（避免卡片套卡片）。
4. **状态不只用颜色表达**：进度/状态/选中态必须有文字或图标等第二编码（色盲友好）。
5. **数据可视化优先**：洞察类信息能用图表就不用长文字。
6. **克制动效**：尊重 `prefers-reduced-motion`，只做淡入/位移，不自动播放。

---

## 2. 三层 Token 结构（最终值）

```
Raw tokens（原始色板，无语义）
   ↓
Semantic tokens（语义：action/danger/surface/text，跨组件复用）
   ↓
Component tokens（组件：button/card/nav/chart/chat 的具体取值）
```

### 2.1 Raw tokens（原始色板 · 最终值）

| Token | 值 | 备注 |
|-------|-----|------|
| `--purple-50` | `#F6F3FF` | 淡紫底 |
| `--purple-400` | `#B7A8F5` | 浅紫（仅装饰/色带/图标，不可作正文） |
| `--purple-600` | `#7A5FD0` | 主色粉紫 |
| `--purple-700` | `#6A4FC0` | 主色 hover |
| `--red-600` | `#E60012` | 品牌红（仅点缀） |
| `--gray-50` | `#F7F7F8` | 暖灰背景 |
| `--gray-200` | `#F0F0F0` | 边框/分割线 |
| `--gray-500` | `#8C8C8C` | 仅大字/装饰（**不作普通小字**） |
| `--gray-600` | `#6B6B6B` | 辅助文本（≥4.5:1） |
| `--gray-700` | `#595959` | 次级文本 |
| `--gray-900` | `#262626` | 主文本 |
| `--white` | `#FFFFFF` | 表面 |
| `--green-500` | `#52C41A` | 成功 |
| `--gold-500` | `#FAAD14` | 警告 |
| `--red-500` | `#FF4D4F` | 错误语义（**非品牌红**） |
| `--blue-500` | `#1677FF` | 信息 |

### 2.2 Semantic tokens（语义 · 最终值）

| Token | 值 |
|-------|-----|
| `--color-action-primary` | `var(--purple-600)` |
| `--color-action-primary-hover` | `var(--purple-700)` |
| `--color-action-primary-fg` | `var(--white)` |
| `--color-brand-accent` | `var(--red-600)` |
| `--color-danger` | `var(--red-500)` |
| `--color-success` | `var(--green-500)` |
| `--color-warning` | `var(--gold-500)` |
| `--color-info` | `var(--blue-500)` |
| `--color-surface` | `var(--white)` |
| `--color-surface-alt` | `var(--purple-50)` |
| `--color-bg` | `var(--gray-50)` |
| `--color-text` | `var(--gray-900)` |
| `--color-text-secondary` | `var(--gray-700)` |
| `--color-text-muted` | `var(--gray-600)` |
| `--color-border` | `var(--gray-200)` |
| `--color-border-strong` | `#D9CCFF`（强调边框，紫色描边） |
| `--color-section-label` | `var(--purple-600)`（区块标签小字，白底对比度 4.80:1） |

> `--color-section-label` 为 Stage 6 新增，专用于 11px 区块标签（如「AI 分析 · 样本可溯」「创意设计」「商品策略」），替代原先的 `--purple-400`（对比度仅 1.9:1，不达标）。

### 2.3 Component tokens（组件 · 最终值）

| Token | 值 |
|-------|-----|
| `--button-primary-bg` | `var(--color-action-primary)` |
| `--button-primary-fg` | `var(--color-action-primary-fg)` |
| `--card-selected-border` | `var(--color-action-primary)` |
| `--card-selected-bg` | `var(--color-surface-alt)` |
| `--nav-active-bg` | `var(--color-surface-alt)` |
| `--task-card-strip-active` | `var(--purple-400)` |
| `--task-card-strip-archived` | `#BBB` |

### 2.4 图表色板（最终值）

| Token | 值 | 用途 |
|-------|-----|------|
| `--chart-series-primary` | `var(--purple-600)` | 主系列（粉紫） |
| `--chart-series-secondary` | `var(--purple-400)` | 次系列（浅紫，装饰） |
| `--chart-series-accent` | `var(--red-600)` | 品牌强调系列（红） |
| `--chart-series-info` | `var(--blue-500)` | 信息/对比系列（蓝） |
| `--chart-accent-fill` | `rgba(230, 0, 18, 0.06)` | 图表品牌强调区填充 |

### 2.5 其他 component token（最终值）

**聊天气泡（用户 / AI）**：
- `--chat-user-bg: var(--purple-600)` · `--chat-user-fg: var(--white)`
- `--chat-ai-bg: var(--gray-200)` · `--chat-ai-fg: var(--gray-900)`

**成本校验（商品策略回环）**：
- `--cost-pass-bg: #EEF7EF` · `--cost-pass-fg: #3A7D44`
- `--cost-fail-bg: #FFF0F0` · `--cost-fail-fg: var(--red-600)`（商业指标不达标用品牌红强调）

**证据与来源**：
- `--evidence-bg: var(--gray-200)` · `--evidence-fg: var(--gray-700)`
- `--source-muted: var(--gray-600)`

**强调面板（品牌红点缀的轻量背景/边框）**：
- `--surface-danger: #FFF5F5` · `--border-danger: #FFCDD2`

**方向卡渐变（三个机会方向）**：
- `--grad-ip-collect: linear-gradient(135deg, #F3E6FF 0%, #E0CCFA 50%, #FAD1DC 100%)`
- `--grad-healing-nature: linear-gradient(135deg, #E0F5EC 0%, #CDE7F0 60%, #B8E6D0 100%)`
- `--grad-outdoor-clip: linear-gradient(135deg, #FDF3E0 0%, #F8D5B0 55%, #F5E6B8 100%)`
- `--grad-default: linear-gradient(135deg, #F6F3FF 0%, #D9CCFF 100%)`

---

## 3. 颜色对比度表（实测 · AA 判定）

> 判定标准：普通小字（<18px 或 <14px 粗体）需 ≥4.5:1；大字（≥18px 或 ≥14px 粗体）需 ≥3:1。

| 前景 | 背景 | 对比度 | 普通小字 AA | 结论 |
|------|------|--------|------------|------|
| `#262626`（主文本） | `#FFFFFF` | 16.6:1 | ✓ | 通过 |
| `#595959`（次文本） | `#FFFFFF` | 7.0:1 | ✓ | 通过 |
| `#6B6B6B`（辅助） | `#FFFFFF` | 5.3:1 | ✓ | 通过 |
| `#8C8C8C` | `#FFFFFF` | 3.36:1 | ✗ | **禁作普通小字**，仅 ≥18px 大字或装饰 |
| `#7A5FD0`（主色/区块标签） | `#FFFFFF` | 4.80:1 | ✓ | 通过（按钮白字、`--color-section-label` 可用） |
| `#E60012`（品牌红） | `#FFFFFF` | 4.80:1 | ✓ | 通过 |
| `#FF4D4F`（错误） | `#FFFFFF` | 3.9:1 | ✗ | 错误文字需加深或加粗/放大 |
| `#7A5FD0`（主色） | `#F6F3FF`（淡紫底） | 4.38:1 | ✗ | 主色字在淡紫底不足 4.5，需加深或加粗 |
| `#B7A8F5`（浅紫） | `#FFFFFF` | 1.9:1 | ✗ | 仅装饰，禁作文字 |

**落地约束**：
- 普通小字正文/辅助一律用 `--color-text` / `--color-text-secondary` / `--color-text-muted`（≥4.5:1）。
- 11px 区块标签一律用 `--color-section-label`（4.80:1），禁用 `--purple-400`。
- `#8C8C8C` 只出现在「大字标签、时间戳装饰、图标描边」，不作为 12–13px 正文。
- 主色文字落在淡紫底时，改用 `--purple-700` 或加粗至 14px 以上，保证 ≥4.5:1。
- **不得通过增大透明度或加阴影来规避对比度要求。**

---

## 4. 字体层级（补行高/字重）

| 层级 | 字号 | 字重 | 行高 | 用途 |
|------|------|------|------|------|
| Page Title | 20px | 600 | 28px | 页面标题 |
| Card Title | 15px | 600 | 22px | 卡片/模块标题 |
| Body | 13px | 400 | 20px | 正文 |
| Caption | 12px | 400 | 18px | 辅助说明、时间戳、来源 |

字体族：`-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif`。

---

## 5. 间距 / 圆角 / 阴影 / 触控（最终值）

**间距 scale**（8px 基准）：`4 / 8 / 12 / 16 / 24 / 32`（对应 `--space-xs/sm/md/lg/xl/2xl`）。

**圆角**：`--radius-sm:4`（输入框/小标签）· `--radius-md:8`（按钮/卡片默认）· `--radius-lg:12`（主卡片/色板）· `--radius-xl:16`（概念图）。

**阴影**（轻）：
```
--shadow-card:  0 1px 2px rgba(0,0,0,0.03), 0 2px 8px rgba(0,0,0,0.06)
--shadow-hover: 0 6px 20px rgba(122,95,208,0.15)
```

**触控目标**：所有可点击控件（按钮、卡片、角标）最小触控区域 **44×44px**（移动端），桌面端至少 32×32px。

---

## 6. 关键视觉规范

| 元素 | 规范 |
|------|------|
| App 背景 | `--color-bg`（暖灰），内容面板 `--color-surface`（白） |
| 任务卡状态色带 | 左侧 3px 竖条，进行中 `--purple-400`，归档 `#BBB`（配文字/图标第二编码） |
| 机会卡选中态 | 2px `--color-action-primary` 边框 + 淡紫底 + 勾选图标（非仅颜色） |
| 概念图 | 圆角 16、高 340px，占位态渐变底 + 图标（即梦接入后换真图） |
| 色板（TrendGallery） | WGSN 式大色块：高 ≥120px，色名叙事（非 #hex） |
| 证据角标 | 灰色圆形上标 `[1]`，hover 弹出来源 Popover |
| 过程日志 | 折叠式顶部条 |
| 图表系列色 | 品类柱状图用 `--color-brand-accent`（品牌强调），两条趋势线分别用 `--color-brand-accent` / `--color-action-primary` 明确区分，竞品散点用 `--color-action-primary`、机会区填充用 `--chart-accent-fill` |

---

## 7. 可访问性红线

1. **颜色对比度**：正文/辅助 ≥4.5:1（见第 3 节表），`#8C8C8C` 不作普通小字，11px 标签用 `--color-section-label`。
2. **状态不用颜色表达**：进行中/归档/选中等必须有文字或图标辅助。
3. **键盘可达**：所有可点击卡片支持 `tabIndex` + `Enter/Space`。
4. **动效尊重 `prefers-reduced-motion`**：reduce 下禁用 transform/opacity 动画与自动播放。
5. **图表可访问性**：每个图表必须有**文本摘要**（`aria-label` + 可见 caption）或**可访问数据表**（`<table>`）替代，不能只有图形。
6. **焦点可见**：`focus-visible` 清晰 outline。
7. **触控目标**：≥44×44px（移动端）。
8. **ECharts Canvas 取色**：ECharts 走 Canvas 渲染，不识别 CSS 变量 `var(--xxx)`，直接传入会退化为灰色。图表 option 的颜色必须经 `readCssVar()`（`shared/utils/cssTokens.js`）读取计算后的真实颜色值；feature 文件不得重新写入 hex 字面量。

---

## 8. 锁定边界（Stage 6 已全部定稿）

Stage 6 完成后，以下内容**全部锁定**，后续 Stage 7（Visual QA）不得改动：

- 粉紫主色方向 + MINISO 红仅点缀 + 暖灰 App 背景 / 白内容面板。
- 品牌红与错误红语义分离（`#E60012` ≠ `#FF4D4F`）。
- 三层 token 结构（raw/semantic/component）及全部具体色值（见第 2 节）。
- 图表色板、聊天气泡、成本校验、证据、强调面板、方向卡渐变等 component token 取值。
- 圆角（4/8/12/16）、阴影（card/hover）、间距 scale（4–32）。
- `--color-section-label` 与 11px 小字对比度规则。
- ECharts Canvas 经 `readCssVar()` 取色的约定。
- 可访问性红线（对比度、键盘、`prefers-reduced-motion`、状态不只用颜色、图表文本替代）。

---

## 9. Stage 6 migration / QA 说明

### 9.1 颜色字面量收敛

Stage 6 将 9 个 feature 文件中的 **87 处硬编码 hex 颜色字面量收敛为 0 处**，全部改由三层 token 引用（`var(--xxx)`）。收敛时按语义区分：文本色 / 主色 / 品牌红 / 表面 / 边框 / 图表系列色，避免机械替换导致语义错位。

### 9.2 ECharts Canvas token 修复

Stage 6 首次将 token 替换应用到 ECharts option 时，误把 `var(--token)` 直接传入 Canvas 绘图，导致图表退化为默认灰色。修复方案：

1. 在 `frontend/src/shared/utils/cssTokens.js` 建立统一读取函数 `readCssVar(name, fallback)`，通过 `getComputedStyle(document.documentElement).getPropertyValue(name)` 读取计算后的真实颜色值（含缓存，`clearCssVarCache()` 清缓存）。
2. `DataBoard.jsx`（品类柱状图、社媒趋势线）与 `InsightCockpit.jsx`（竞品散点、机会区填充、机会区标签）的 ECharts option 改用 `readCssVar('--xxx')`。
3. 约定：feature 文件不得重新写入 hex，统一经 `readCssVar` 取色。

### 9.3 11px 小字对比度修复

原 `--purple-400`（`#B7A8F5`，白底对比度 1.9:1）被误用作 11px 区块标签文字，不达标。修复：

- 新增语义 token `--color-section-label: var(--purple-600)`（白底 4.80:1）。
- `InsightCockpit.jsx` 的 `MODULE_TAG`、`global.css` 的 `.plan-section-tag` 改用该 token。
- `--purple-400` 继续仅用于装饰、色带、非文字图形（进度条、日志箭头、状态色带、图表次系列）。

### 9.4 代表性截图（可追踪）

Stage 6 视觉成果截图已从 `preview/stage6/` 复制到本目录 `preview/stage6/`，覆盖本次补丁直接涉及的三类核心页面（桌面 1440 + 移动 375）：

| 页面 | 桌面 | 移动 |
|------|------|------|
| 数据看板（品类柱状图 + 趋势线） | `preview/stage6/dashboard-1440.png` | `preview/stage6/dashboard-375.png` |
| 洞察驾驶舱（竞品散点 + 机会区） | `preview/stage6/insight-1440.png` | `preview/stage6/insight-375.png` |
| 企划卡（`plan-section-tag` 小字标签） | `preview/stage6/plancard-1440.png` | `preview/stage6/plancard-375.png` |

### 9.5 QA 结论

- `npm run build` 通过，feature 固定 hex 字面量仍为 0。
- 375 / 1440 抽查 DataBoard、洞察页、企划卡无溢出。
- 品类柱状图为品牌强调色、两条趋势线可明确区分、竞品散点与机会区颜色正常，图表不再退化为灰色。

---

## 10. 不做的事

- 不引入 CSS-in-JS / Tailwind / 新 UI 框架（保持 antd 5 + 原生 CSS variables）。
- 不引入玻璃拟态、深色主题、3D 装饰。
- 不改品牌 Logo 与 MINISO 红的核心语义。
