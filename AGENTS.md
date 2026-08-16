# AGENTS.md — AI 编程工具协作者指南

> 本文件面向 AI 编程助手（Claude Code / Cursor / Copilot 等）。
> 人类队友请先看各模块 README；本文件是**机器可执行的接口契约**。

## 项目一句话

SKU Hunters · AI Product Committee：7 个角色 Agent 模拟名创优品商品评审会，
LangGraph 编排，FastAPI + 飞书机器人交互。代码在 `backend/`。

## 硬性纪律（违反 = CI 红）

1. **密钥只存在于 `.env`**，禁止硬编码 App ID / Secret / API Key（GitHub push protection 会拦截）
2. **D1 已冻结的 schema 不得修改**（`app/schemas/` 现有文件）；新增契约 = 新增文件
3. 所有路径用 `Path(__file__).resolve()` 锚定，禁止绝对路径
4. 提交前本地跑：`ruff check backend/`（从仓库根）+ `pytest tests/ --cov=app`（从 backend/）

## 严格真实模式（Strict Real Mode）

生产环境禁止一切 Mock / fixture / 演示数据回退，由 `app/engine/strict_mode.py` 单一事实源判定：

```env
APP_ENV=production
ALLOW_MOCK=false
BASE_PROVIDER_MODE=feishu
PLANNING_DEFAULT_MODE=live
AGENT_PROVIDER=real
LEARNING_AGENT_PROVIDER=real
```

- `APP_ENV=production` 且 `ALLOW_MOCK=false` → 严格模式：LLM / 数据源失败**阻断**（抛 `StrictModeError`），不回退 Mock；真实数据不足 → `unavailable`（合法态），不用演示内容填满页面；字段缺失 → `unknown`。
- 严格模式强制：企划默认模式 `live`；**禁止**创建/打开 `fixture` 与 `demo` 任务；`/health` 返回 `mock_allowed=false, strict_real=true`。
- Agent 注册表（`get_*_agent_class`）经 `resolve_provider` 校验：严格模式必须 `real`（或含确定性官允许 `deterministic`），否则启动即阻断。
- 真实 Agent 内部 Mock fallback 经 `require_mock_allowed`：严格模式抛错，非严格放行（测试用）。
- 使用真实数据的 deterministic Agent（如 ConsumerInsightAgent / IPStrategyAgent / GoToMarketAgent）不属于 Mock，可保留。
- Mock 代码保留给自动化测试（测试环境 `APP_ENV` 留空、`ALLOW_MOCK` 默认 true）。

## 接口 A：接入新 Agent（替换 mock）

编排层在 `backend/app/engine/graph.py`。所有图节点是薄包装层，只认注册表：

1. 继承 `app.agents.base_agent.BaseAgent`，实现 `async def run(self, context: dict) -> dict`
2. 返回值必须通过对应 schema 的 `model_validate`：

| 注册表键 | 返回契约 |
|:---|:---|
| `trend` | `FeatureMatrix` |
| `user` | `UserSentiment` |
| `ip` | `IPAssessment` |
| `creative` | `ProposalSet` |
| `business` | `{"opportunity_scores": [OpportunityScore, ...]}` |
| `gtm` | `{"gtm_plans": [GTMPlan, ...]}` |
| `learning` | `{"normalized_actual_signal": NormalizedActualSignal, "retro_report": RetroReport, "archive_update": {...}}` |

3. 洞察官（trend/user/ip）的 `evidence_refs` 必须非空，否则节点边界拒绝
   （例外：`confidence="unknown"` 时合法，自动记 C5 冲突——"无法判断"是合法输出）
4. context 可用键：
   - 所有 Agent：`brief`、`feedback`（人工修改意见，修改回退重跑时非空）
   - creative：+ `feature_matrix`、`user_sentiment`、`ip_assessment`
   - business：+ `weights`、`proposal_set`、`upstream_confidences`、`feature_matrix`、`user_sentiment`、`ip_assessment`
   - gtm：+ `proposal_set`、`challenges`、`opportunity_scores`、`ip_assessment`、`feedback`
   - learning：+ `proposal`、`opportunity_score`、`decision`、`human_action`、`session_id`、`category`、`market`
5. 接入方式：改 `graph.py` 里 `AGENT_REGISTRY` 对应键的类，**其他一律不动**
6. 禁止：Agent 返回未过 schema 的 dict；依赖 state 里未声明的键

## 接口 C：消费评审事件流（飞书 handler）

```python
from app.engine.graph import run_review

async for event in run_review(brief, ask_human=your_callback, session_id=None):
    ...  # event 恒为 {"role": str, "content": str, "evidence": list[str], "score": float | None}
```

- `role` 枚举：`trend` / `user` / `ip` / `creative` / `business` / `global` /
  `decision` / `learning` / `challenge` / `act1_gate` / `human_gate` / `retro` / `qa`
  （`challenge` 为 ACT2_CHALLENGE 质询环节事件：三位洞察官对 ProposalSet 的结构化
  质询，四键契约不变，evidence 为质询证据链，来源角色保留在 content 中）
- `brief` 必须过 `Brief` schema：`{"category": str, "market": str, "budget_range": "low"|"mid"|"high"}`
- `ask_human(gate_info) -> dict`，`gate_info = {"gate", "prompt", "options"}`。
  门有两个半：act1_gate（方向确认）、human_gate（立项拍板）、retro（首次复盘入口：
  **归档之后**开启，不打回重做，只对话/总结教训；归档后另有 API 历史复盘入口）。
  返回值按门选用：
  - `{"action": "confirm"}`
  - `{"action": "modify", "suggestion": str, "scope"?: str, "custom_weights"?: dict}`
    （`scope` 仅 human_gate 用：`"business"`=只重算评分（默认）/ `"creative"`=回退重做方案；
    `custom_weights` 合法时写入 state 即 reweight，权重和必须 = 1.0）
  - `{"action": "question", "question": str}`（qa 作答后自动回到同一门再次询问）
  - `{"action": "reject", "reason": str}`（仅 human_gate：否决立项 = bad case，
    记 C4 冲突后**先归档**（负样本）再进复盘入口——否决理由是负样本来源）
  - retro 门专用：`{"action": "chat", "content": str}`（LLM 基于本场证据链作答，
    无 Key 降级为产物索引）/ `{"action": "done"}`（结束本轮复盘，轮数追加入档）
- **10 秒超时由调用方实现**：`asyncio.wait_for(等待按钮回调, timeout=10)`，超时返回 `confirm`
  （retro 门超时返回 `done`）。图对超时一无所知（interrupt 无限期等待是 checkpoint 可靠性特性）
- 门事件会成对出现：先是提问（prompt），`ask_human` 返回后紧跟一条人决策回显
- `decision` 事件额外携带 `report` 键（完整《立项建议书》dict）；
  `learning` 事件额外携带 `snapshot` 键（归档快照），出现两次：建档 + 复盘轮数追加。
  四键契约不变
- 归档顺序：human_gate 结论 → learning_node 建档 → retro 首次复盘入口 →
  learning_node 二过追加 retro_turns → END（learning_node 幂等，靠路由函数分流）

## 排障速查

| 报错 | 原因 | 解法 |
|:---|:---|:---|
| `InvalidUpdateError: Can receive only one value per step` | 并行节点同写共享标量键 | 并行节点只写各自 artifact 键和 reducer 键；`current_act` 由下游单点写 |
| msgpack 反序列化告警 | 枚举/日期实例进 checkpoint | 入 state 一律 `model_dump(mode="json")` |
| 会议在门之间无限循环 | `ask_human` 每次都返回 modify | 回调侧控制：修改意见生效后人应 confirm；飞书侧 10s 超时兜底 |
| API 后台会议不推进 | TestClient 没用 `with` | `with TestClient(app) as c:`，portal 持续运转任务才推进 |
| `pytest` exit code 5 | tests/ 无测试被收集 | 检查文件名 `test_*.py` 与目录结构 |
