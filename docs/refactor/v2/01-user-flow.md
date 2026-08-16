# 01 · 用户流程（User Flow）v1.1

> 门禁文档 · 前端视觉重构前必须对齐「用户在系统里如何完成任务」。
> v1.1 变更：①区分 AS-IS / TO-BE；②流程推进从「advance + GET 两请求」改为「原子业务动作」；③补齐边界态与 state/action/recovery 表。

---

## 1. 角色与目标

**唯一角色**：商品经理（名创优品品类企划岗）。

**核心目标**：在 AI 辅助下，从「一个模糊的品类想法」推进到「一份可执行的新品企划案」，过程中每个决策都有数据依据（四方证据链）。

**次要目标**：浏览名创内部资产与跨品类趋势，为后续企划积累输入。

---

## 2. 两大流程域

| 域 | 页面 | 性质 |
|----|------|------|
| **企划流程** | 任务中心 → 新建企划 → 任务流程（约束/洞察/机会/企划卡） | 线性推进、有状态机 |
| **洞察数据** | 数据看板 · 名创内部 · 流行元素板 | 策展数据浏览、无状态 |

---

## 3. 状态机（TO-BE · 原子动作）

### 3.1 落盘状态（后端枚举，5 种，不臆造）

```
brief_locked → insights_ready → opportunities_ready → plan_card_ready → archived
```

| 状态 | 含义 | 前端 step | 可触发的原子动作 |
|------|------|-----------|------------------|
| brief_locked | 约束已冻结 | 0 | generate-insights |
| insights_ready | 洞察已生成并落盘 | 1 | generate-opportunities |
| opportunities_ready | 机会方向已生成并落盘 | 2 | generate-plan-card |
| plan_card_ready | 企划卡已生成并落盘 | 3 | archive |
| archived | 已归档（只读） | —（回看态） | 仅复盘追问（只读） |

> `running` / `generating` **仅作为前端瞬时 UI 态**，**不进入后端状态枚举**。后端落盘状态永远是上表 5 种之一。

### 3.2 状态推进 = 原子业务动作（TO-BE）

**禁止**「`advancePlan(insights_ready)` + `getInsights`」两请求组合推进——它会产生「状态已推进、但洞察生成失败」的半完成态。

**改为后端原子动作**（生成 + 落盘 + 推进状态一次完成，成功才返回新状态）：

| 原子动作 | HTTP | 入参 | 成功返回 | 失败返回 |
|----------|------|------|---------|---------|
| generate-insights | `POST /plans/{id}/actions/generate-insights` | — | `{ status: "insights_ready", insights }` | 4xx/5xx，状态**不变** |
| generate-opportunities | `POST /plans/{id}/actions/generate-opportunities` | — | `{ status: "opportunities_ready", opportunities }` | 同上 |
| generate-plan-card | `POST /plans/{id}/actions/generate-plan-card` | `{ opportunity_id }` | `{ status: "plan_card_ready", plan_card }` | 同上 |
| archive | `POST /plans/{id}/actions/archive` | — | `{ status: "archived", archived_at }` | 同上 |

**只读 GET（刷新恢复用，不推进状态）**：

| 只读接口 | 用途 |
|----------|------|
| `GET /plans/{id}` | 恢复 brief / status / plan_card |
| `GET /plans/{id}/insights` | 读取已落盘洞察（status ≥ insights_ready 时） |
| `GET /plans/{id}/opportunities` | 读取已落盘机会（status ≥ opportunities_ready 时） |

### 3.3 顺序修正（v1.1）

- **企划卡生成顺序**：`generate-plan-card` 在 `opportunities_ready` 之后触发，**成功后**状态才变 `plan_card_ready`。原 v1.0 描述「plan_card_ready 后才生成企划卡」语义颠倒，已修正。
- **归档只读**：`archived` 状态下企划卡只读。「复盘追问」（只读回顾，可问历史）与「改稿」（修改正式企划案，仅 `plan_card_ready` 状态可用）**分开定义**——归档后**不能改稿**，只能复盘追问。

---

## 4. 主流程（TO-BE 流程图）

```
[任务中心] → 点击「新建企划」
   ▼
[新建企划] 填约束 → POST /plans → 得到 plan_id（status=brief_locked）
   ▼
[TaskFlow · step 0]  查看约束
   │ 点击「开始洞察分析」→ POST actions/generate-insights
   │   ├─ 前端瞬时态 generating（Spin/进度）
   │   └─ 成功 → status=insights_ready + 返回 insights → 进 step 1
   ▼
[TaskFlow · step 1]  查看五看洞察
   │ 点击「生成机会方向」→ POST actions/generate-opportunities
   │   └─ 成功 → status=opportunities_ready + 返回 opportunities → 进 step 2
   ▼
[TaskFlow · step 2]  选 1 张方向卡
   │ 点击「进入企划生成」→ POST actions/generate-plan-card(opportunity_id)
   │   └─ 成功 → status=plan_card_ready + 返回 plan_card → 进 step 3
   ▼
[TaskFlow · step 3]  查看企划卡（六模块）
   │ ├─ 「改稿」POST /revise（仅本状态可用，可多轮）
   │ └─ 「归档」POST actions/archive → status=archived → 回任务中心
   ▼
[任务中心]  任务进入「已归档」分组
```

---

## 5. AS-IS vs TO-BE 差异（明确记录）

| 维度 | AS-IS（当前代码） | TO-BE（目标） |
|------|------------------|--------------|
| 推进机制 | `advancePlan(to)` + `getInsights` 两请求 | `POST actions/generate-*` 单原子动作 |
| 半完成态 | 存在（状态已推进、数据未生成） | 不存在（成功才推进状态） |
| GET 副作用 | GET 只读（已修复） | GET 只读（保持） |
| 归档改稿 | 归档后可改稿 | 归档只读，改稿仅限 plan_card_ready |
| 企划卡生成 | `POST /plan-card` | `POST /actions/generate-plan-card` |
| 后端状态枚举 | 5 种（running 仅 aily 响应） | 5 种（generating 不落盘） |

> AS-IS → TO-BE 的 API 改造（advance 端点 → actions 端点）属于 Stage 5 功能实现阶段，**本轮仅记录设计**。

---

## 6. 边界态与异常路径（补齐）

### 6.1 导航与表单

| 场景 | 行为 |
|------|------|
| 新建页返回 / 离开未保存 | 表单有未提交改动时，弹「离开确认」对话框（离开/继续编辑） |
| 新建页取消 | 返回任务中心，不创建任务 |
| 流程内「返回换方向」 | step 3 回 step 2，不重置已生成的机会卡（只读已有数据） |

### 6.2 提交与幂等

| 场景 | 行为 |
|------|------|
| 重复点击「开始洞察」 | 按钮 loading 期间禁用（disabled + loading），防重复提交 |
| 重复提交 generate-* | 后端幂等：同状态重复动作返回 409 或幂等返回已有结果 |
| 409 状态冲突 | 提示「当前状态不支持此操作」，刷新恢复正确步骤 |

### 6.3 资源与错误

| 场景 | 行为 |
|------|------|
| 404 任务不存在 | 404 页（全局），带「返回任务中心」 |
| 网络超时 / 离线 | 错误态 + 重试按钮；不静默回退 mock |
| 刷新恢复未完成任务 | `GET /plans/{id}` 按 status 恢复 step，数据懒加载 |
| 深层路由刷新失败 | SPA fallback 返回 index.html，前端 Router 接管 |

### 6.4 生成与降级

| 场景 | 行为 |
|------|------|
| 即梦出图失败 | 企划卡概念图降级占位图（fail-soft），其余字段照常生成；提供「重试出图」 |
| 出图重试 | 可单独重试出图，不影响已生成的企划卡字段 |
| 归档前确认 | 弹「确认归档」对话框（归档后不可改稿） |

### 6.5 演示降级（严格限定）

- **只有 `/tasks/demo` 任务允许使用本地 fixture 降级**，且必须挂「演示数据（后端离线）」标识。
- **真实任务接口失败只能显示错误 + 重试，禁止替换成演示内容。**

---

## 7. State / Action / Recovery 表（完整）

| 状态 | 可用 Action | 前端 UI 态 | 失败/异常 | 刷新恢复 |
|------|------------|-----------|----------|---------|
| brief_locked | generate-insights | idle | — | step 0 |
| brief_locked → 生成中 | （generating 瞬时态，非落盘） | loading/generating | 网络错误→错误+重试 | 仍 step 0（状态未变） |
| insights_ready | generate-opportunities / 查看洞察 | success | — | step 1 |
| insights_ready → 生成中 | （generating） | loading | 同上 | 仍 step 1 |
| opportunities_ready | generate-plan-card / 选方向 | success | — | step 2 |
| opportunities_ready → 生成中 | （generating） | loading | 出图失败→占位+重试 | 仍 step 2 |
| plan_card_ready | archive / revise（改稿） | success | 409 若未生成 | step 3 |
| archived | 复盘追问（只读） | success | — | 回看态 |

**恢复规则**：刷新后 `step` 由 `plan.status` 映射（brief_locked→0 / insights_ready→1 / opportunities_ready→2 / plan_card_ready→3 / archived→回看）；各步数据通过只读 GET 懒加载；「generating」瞬时态刷新后消失，回到对应落盘状态。

---

## 8. 洞察数据域（策展浏览 · 无状态）

三个独立页，侧边栏直达，纯只读，各自 loading/error/empty/retry，不共享状态：

```
侧边栏「洞察数据」分组
├── 数据看板 DataBoard    → 品类大盘（热度/声量/热销/价格带）
├── 名创内部 InsightBase  → 历史爆品 / IP 库 / 设计语言
└── 流行元素板 TrendGallery → 配色/花纹/形态/表情化
```

---

## 9. 流程完整性红线（门禁）

1. **每个决策可溯源**：机会卡每张方向卡挂「四方依据链」，证据角标可点开看来源。
2. **一页一个主 CTA**：每步只突出一个主行动按钮。
3. **状态推进原子化**：生成成功才推进落盘状态；generating 只是前端瞬时态。
4. **归档只读**：归档不可改稿，只能复盘追问。
5. **演示降级限定**：仅 `/tasks/demo` 可 fixture 降级，真实任务失败只报错。
