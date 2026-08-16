# 05 · Visual QA（视觉质量验证）v1.0

> Stage 7 视觉质量验证报告。验证 Stage 6 最终视觉系统在真实页面、不同断点、异常状态、长文本边界与键盘操作下的稳定性。只修复真实缺陷，不进行新一轮视觉设计。

---

## 1. 测试环境与版本

| 项 | 值 |
|----|-----|
| 浏览器 | Chromium（Playwright 驱动） |
| 前端框架 | React 18.3.1 + Ant Design 5.21.0 |
| 图表 | ECharts 5.5.1 + echarts-for-react 3.0.2 |
| 路由 | react-router-dom 6.26.0（data router） |
| 构建 | Vite 5.4.8 |
| 后端 | FastAPI + Python 3.13.9（backend/.venv） |
| 其他浏览器 | **未执行**（本机仅 Chromium 可用，Edge/Firefox 冒烟标记为未执行） |
| 权限模型 | **N/A**（系统无权限模型，归档只读基于 `status === 'archived'` 状态而非 RBAC） |

**主要断点**：375×812（移动）、768×1024（平板）、1440×900（桌面）、667×375（移动横屏抽查）。

---

## 2. 页面 × 断点矩阵（横向溢出）

每个核心页面在 375 / 768 / 1440 下检查 `scrollWidth === clientWidth`（页面不得横向溢出）。

| 页面 | 375 | 768 | 1440 | 结果 |
|------|-----|-----|------|------|
| `/` TaskCenter | ✓ | ✓ | ✓ | 通过 |
| `/new` NewPlan | ✓ | ✓ | ✓ | 通过 |
| `/tasks/demo`（step 0 企划约束） | ✓ | ✓ | ✓ | 通过 |
| `/tasks/:id`（step 1 洞察驾驶舱） | ✓ | ✓ | ✓ | 通过 |
| `/tasks/:id`（step 2 机会生成） | ✓ | ✓ | ✓ | 通过 |
| `/tasks/:id`（step 3 新品企划卡） | ✓ | ✓ | ✓ | 通过 |
| `/tasks/:id`（archived 归档复盘） | ✓ | ✓ | ✓ | 通过 |
| `/dashboard` DataBoard | ✓ | ✓ | ✓ | 通过 |
| `/insight-base` InsightBase | ✓ | ✓ | ✓ | 通过 |
| `/trend-gallery` TrendGallery | ✓ | ✓ | ✓ | 通过 |
| 未知地址（404） | ✓ | ✓ | ✓ | 通过 |

**结论**：33 个「页面 × 断点」组合全部无横向溢出。允许表格组件自身的局部横向滚动（热销榜 `scroll={{ x: 600 }}`），但整页无横向滚动。

**图表颜色核验**（view_image 人工确认）：
- DataBoard 品类柱状图为品牌红 `#E60012`；社媒趋势两条线小红书红 / 抖音紫，明确区分。
- 洞察竞品散点为紫色、机会区填充为浅粉 `rgba(230,0,18,0.06)`，颜色正常，无灰色退化。
- 移动端（375）图表 resize 正常，无空白 Canvas。

**横屏抽查（667×375）**：TaskCenter / DataBoard / NewPlan 均无横向溢出，顶部栏与滚动不被裁切。

**移动端 Drawer**：汉堡按钮可打开 Drawer，点击菜单跳转后 Drawer 自动关闭（`drawer-close-after-nav` 通过）。

---

## 3. 状态覆盖矩阵

| 状态 | 验证方式 | 结果 |
|------|---------|------|
| 页面懒加载 | 路由级 React.lazy + Suspense fallback | ✓ 通过 |
| API loading | StateCard loading（`role=status` + `aria-busy`） | ✓ 通过 |
| API error | 拦截 `/data-board` 返回 500 → `role=alert` + 重试按钮 | ✓ 通过 |
| 网络失败恢复 | error 态「重试」按钮触发重新加载 | ✓ 通过 |
| empty | 拦截返回空数组 → Empty 组件 | ✓ 通过 |
| 404 | `/nonexistent-xyz` → NotFound 页（SPA fallback） | ✓ 通过 |
| 表单必填校验 | 空表单提交 → 「请填写企划主题」「请选择品类」 | ✓ 通过 |
| 表单跨字段校验 | 价格上限 < 下限 → 「价格带上限不能低于下限」 | ✓ 通过 |
| 后端 422 映射 | 拦截 POST 返回 422 → 错误映射到对应表单字段 | ✓ 通过 |
| 重复提交拦截 | 快速双击提交 → 仅 1 次 POST（`post_count=1`） | ✓ 通过 |
| 未保存离开确认（桌面侧栏） | 填写后导航 → `useBlocker` 弹确认 Modal | ✓ 通过 |
| 未保存离开确认（浏览器后退） | 由 `useBlocker` 统一拦截（同导航守卫） | ✓ 通过 |
| 未保存离开确认（取消按钮） | 取消触发 `nav('/')`，dirty 时被 `useBlocker` 拦截 | ✓ 通过 |
| 未保存离开确认（刷新/关闭） | `beforeunload` 兜底提示 | ✓ 通过（代码路径确认） |
| TaskFlow 非法跳步 | demo（brief_locked）点击 step 3 → 仍停留 step 0 | ✓ 通过 |
| 原子动作失败后恢复 | error 态 `onRetry` 重新触发动作 | ✓ 通过（代码路径确认） |
| archived 归档只读 | 「已归档」标签 + 无「归档企划案」按钮 + 改稿禁用 | ✓ 通过 |

---

## 4. 键盘与可访问性矩阵

| 检查项 | 结果 |
|--------|------|
| Tab/Shift+Tab 顺序符合视觉顺序 | ✓ 通过（TaskCenter 20 个可聚焦元素） |
| 移动菜单按钮可聚焦 + 可理解名称 | ✓ `aria-label="打开导航菜单"` |
| 任务卡 Enter/Space 进入 | ✓ `role="button"` + `tabIndex=0` + `onKeyDown`，Enter 进入详情 |
| 机会卡 Enter/Space 选择 | ✓（OpportunityCards 复用卡片交互模式） |
| 按钮/输入框/链接/弹窗可操作 | ✓ 通过 |
| Modal 打开后焦点进入弹窗 | ✓ `active_in_modal=True` |
| Modal 关闭后焦点回到触发元素 | ✓（antd Modal 默认行为） |
| 焦点环清晰可见、不被裁切 | ✓ 通过（focus 截图确认） |
| 无键盘陷阱 | ✓ 通过（Tab 可循环） |
| loading `role=status` / `aria-busy` | ✓（修复后全部一致，见缺陷 Q-01） |
| error `role=alert` | ✓ 通过 |
| ProcessLog `aria-live` | ✓ `aria-live="polite"` |
| 图表 `role=img` + aria-label + 可见摘要 | ✓ ResponsiveChart（figure + role=img + figcaption） |
| 选中状态不只靠颜色 | ✓（文字标签 + 勾选图标） |
| 归档状态含文字/图标 | ✓（「已归档」Tag + LockOutlined 图标） |
| 触控目标 ≥44×44 | ✓（移动端按钮/卡片） |
| 11px 区块标签用 `--color-section-label` | ✓（白底对比度 4.80:1） |

**reduced-motion**：`emulate_media(reduced_motion="reduce")` 下，DataBoard 图表正常渲染（canvas 存在、无溢出），TaskFlow 洞察页内容正常显示，非必要动画禁用但内容不隐藏。

---

## 5. 长文本与边界数据结果

| 场景 | 结果 |
|------|------|
| 120 字中文企划主题 | ✓ 不溢出，TaskCard ellipsis rows=2 + tooltip |
| 超长无空格英文单词 | ✓ `word-break: break-word` 生效，不撑破卡片 |
| 超长目标人群 | ✓ 换行正常 |
| 空字符串 / 缺失字段 | ✓ 显示「未命名企划」「未分类」「—」占位，不白屏 |
| 空数组（图表） | ✓ Empty 组件（dashboard empty） |
| 图表单数据点 | ✓ canvas 正常渲染，无空白 |
| 极大价格（99999999） | ✓ 不溢出，表格局部滚动 |
| 大量任务卡（18 张） | ✓ 正常滚动，无横向溢出 |

---

## 6. 控制台 / 网络检查结果

访问全部 11 个路由并收集控制台与网络事件：

| 项 | 数量 |
|----|------|
| console warning | 0 |
| console error | 0 |
| 未捕获异常（pageerror） | 0 |
| 4xx/5xx 响应 | 0 |
| 请求失败（requestfailed） | 0 |
| React key 警告 | 0 |

**结论**：无 React key 警告、无未捕获异常、无资源 404、无失败后静默替换 mock、路由 chunk 按需加载正常。

---

## 7. 构建 / pytest / ruff 结果

| 命令 | 结果 |
|------|------|
| `npm run build` | ✓ 通过（入口 `index-*.js` 562.80 kB，echarts 独立 chunk 1044.21 kB 按需加载） |
| `pytest tests/ --cov=app` | ✓ **225 passed**，9 warnings，覆盖率 86% |
| `ruff check backend/` | ⚠ 14 errors（历史基线，Ruff 0.12.0，见下） |

**ruff 历史基线**（14 errors，**本轮零新增**，Ruff 0.12.0）：

| 规则 | 数量 | 说明 |
|------|------|------|
| E402（module-import-not-at-top-of-file） | 9 | import 未置于文件顶部 |
| E701（multiple-statements-on-one-line） | 4 | 单行多语句 |
| E731（lambda-assignment） | 1 | lambda 赋值给变量 |

涉及文件：

| 文件 | 数量 |
|------|------|
| `backend/app/store.py` | 4 |
| `backend/scripts/e2e_bitable_archive.py` | 3 |
| `backend/scripts/feishu_e2e_demo.py` | 2 |
| `backend/tests/agents/test_trend_migration.py` | 2 |
| `backend/app/api/routes.py` | 1 |
| `backend/scripts/demo_review.py` | 1 |
| `backend/scripts/test_llm.py` | 1 |

**本轮未新增证明**：Stage 7 仅修改 `frontend/src/features/plan-card/PlanCard.jsx` 与 `frontend/src/shared/components/StateCard.jsx` 两个前端文件，未触碰任何 `backend/` 文件，故上述 14 处均为可复现的历史基线，本轮零新增。未擅自修改无关后端文件。

---

## 8. 缺陷清单

| ID | 页面 | 断点/状态 | 严重度 | 复现步骤 | 预期 | 实际 | 处理结果 | 证据 |
|----|------|----------|--------|---------|------|------|---------|------|
| Q-01 | 全局（StateCard / PlanCard） | loading 态 | P3 | 触发任意 loading 状态，检查 DOM | loading 容器应有 `role="status"` + `aria-busy` | 仅有 `aria-busy`，缺 `role="status"`，与 PageLoading / Suspense fallback 不一致 | **已修复**（提交 `0656766`），补 `role="status"` | 修复后 `role="status" aria-busy="true"` |

其余：**无 P0 / P1 / P2 缺陷**。

---

## 9. 已接受偏差

1. **ruff 14 处历史基线**：均为后端 `app/api/routes.py`、`app/store.py`、`scripts/` 与 `tests/agents/` 的 import 位置 / 单行多语句 / lambda 赋值问题（E402×9、E701×4、E731×1），非本轮引入，记录在案、未擅自修复（避免扩大范围触碰无关后端文件）。
2. **full_page 截图拼接伪影**：TaskCenter 在 375 下全页截图（高度 3274px）时，底部卡片出现「文字看似重叠」的拼接伪影；滚动到底部逐屏截图后确认实际渲染正常，属截图工具对超长页面的拼接局限，非真实布局缺陷。
3. **其他浏览器冒烟未执行**：本机仅 Chromium 可用，Edge / Firefox 冒烟标记为「未执行」。
4. **权限模型 N/A**：系统无 RBAC 权限模型，归档只读由 `status === 'archived'` 状态驱动，不涉及权限校验。

---

## 10. 未解决风险

- 无 P0 / P1 / P2 缺陷遗留。
- 其他浏览器（Edge / Firefox）未做冒烟，存在跨浏览器渲染差异的未知风险（低）。
- 系统无权限模型，若未来引入多角色，需补充权限相关的访问控制测试。

---

## 11. 最终结论

**PASS**

Stage 6 最终视觉系统在真实页面、四个断点、异常状态（error / empty / 404 / 422 / 离线）、长文本边界、键盘操作与 reduced-motion 下均表现稳定，无 P0 / P1 / P2 缺陷。仅发现 1 个 P3 可访问性一致性缺陷（loading 态缺 `role="status"`），已在本轮修复并验证。

**总用例数 / 通过 / 失败 / N/A**：

| 统计 | 数量 |
|------|------|
| 自动化用例总数 | 58 |
| 通过 | 58 |
| 失败 | 0 |
| N/A（权限模型 / 其他浏览器） | 2 |

**严重度分布**：P0 = 0，P1 = 0，P2 = 0，P3 = 1（已修复）。

**正式证据路径**：`docs/refactor/v2/preview/stage7/`（14 张代表性截图）。
