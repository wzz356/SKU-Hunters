# Stage 11B — Strict Real Mode（生产环境严格真实模式）

> 目标：正式环境完全禁用 Mock / fixture / 演示数据回退，做到「LLM 失败→阻断、
> 飞书失败→阻断、数据为空→unavailable、字段缺失→unknown、禁止回退 Mock、
> 禁止运行 fixture/demo 任务」。
> 状态：实现 + 真实 E2E 验证完成，待人工审核后提交。

## 1. 单一事实源：`backend/app/engine/strict_mode.py`

- `APP_ENV=production` 且 `ALLOW_MOCK=false` → `strict_real()=True`。
- 生产默认禁止 Mock（仅显式 `ALLOW_MOCK=true` 放行）；非生产（test/dev）默认允许 Mock（自动化测试用）。
- 对外接口：
  - `resolve_provider(role, env_key, allowed)`：严格校验 provider 必须为 `allowed` 内真实实现，否则抛 `StrictModeError`。
  - `require_mock_allowed(where)`：Mock/演示数据回退点调用，严格模式抛错阻断。
  - `planning_default_mode()`：严格模式强制 `live`，否则取 `PLANNING_DEFAULT_MODE`（默认 fixture）。
  - `allow_fixture_tasks()` / `is_demo_hidden()`：严格模式禁 fixture、隐藏 demo。

## 2. 改动点

| 层 | 文件 | 改动 |
|----|------|------|
| 契约 | `engine/strict_mode.py` | 新增，严格模式单一事实源 |
| Agent 注册表 | 7 个 `get_*_agent_class` | 经 `resolve_provider` 校验，严格模式必须 real/deterministic，否则启动阻断 |
| 真实 Agent | user/ip/business/gtm/creative | Mock fallback 点加 `require_mock_allowed`，严格模式 LLM 失败直接抛错 |
| 企划服务 | `planning/repository.py` | `create_plan` 严格模式强制 live、禁 fixture；`list_plans` 隐藏 demo |
| 企划服务 | `planning/service.py` | `seed_demo` 严格模式不预置 demo |
| API | `api/planning.py` | `create_plan` 捕获 `StrictModeError`→409 `STRICT_REAL_MODE`；`get_plan` 隐藏 demo→404 |
| 健康检查 | `main.py` | `/health` 返回 `mock_allowed`、`strict_real` |
| 测试 | `tests/engine/test_strict_mode.py` | 16 个用例 |
| 文档 | `AGENTS.md`、`.env.example`、本文件 | 说明严格模式 env 与纪律 |

**明确保留（不属于 Mock）**：使用真实飞书数据的 deterministic Agent（ConsumerInsightAgent / IPStrategyAgent / BusinessEvaluationAgent / GoToMarketAgent）、trend 官基于真实指标做规则摘要、learning/consumer 官在数据不足时输出 `unavailable/unknown`。

## 3. 生产 env 配置（`.env`，不提交）

```env
APP_ENV=production
ALLOW_MOCK=false
BASE_PROVIDER_MODE=feishu
PLANNING_DEFAULT_MODE=live
AGENT_PROVIDER=real
LEARNING_AGENT_PROVIDER=real
```

## 4. 真实 E2E 验证结果

| 验证项 | 结果 |
|--------|------|
| `/health` | `strict_real=true, mock_allowed=false` ✅ |
| 真实任务（28b2/f29b/c750） | `mode=live`、`dataSource=feishu`、`record_count>0`、`evidence_count>0`（30 / 438 / 30）✅ |
| 新建 live 任务生成洞察 | `generate-insights` → `insights_ready`，insights `dataSource=feishu`，processLog「数据源：飞书 Base 实时明细」✅ |
| 创建 fixture 任务 | → 409 `STRICT_REAL_MODE`（严格模式禁止）✅ |
| 访问 demo 详情 | → 404（隐藏）✅ |
| 任务列表 | 不包含 demo ✅ |
| Agent 注册表 | strict+real 下 7 官均解析为真实类；strict+mock 下 graph 导入即阻断 `StrictModeError` ✅ |
| Mock fallback | strict 下 `require_mock_allowed` 抛错阻断（单测覆盖）✅ |

## 5. 测试与静态检查

- 新增 `tests/engine/test_strict_mode.py`：**16 passed**（mock_allowed 默认值、resolve_provider 校验、require_mock_allowed 阻断、planning 默认模式、fixture 禁止、demo 隐藏）。
- 全量回归：**568 passed + 19 failed**。19 项为**已知历史失败**（insights `dataSource` 键与 Jimeng plan card 链导致的旧断言过期，来自 test_pipeline / test_planning_api / test_routes），与 Stage 11B 无因果，单独记录、不阻断本阶段，报告中不表述为「全量通过」。
- ruff（本阶段修改文件）：全部通过（`main.py` 的 I001/RUF100 为既有基线，源自刻意保留的 E402 导入顺序，非本阶段引入）。
- `.env` 已配置完整严格模式变量且被 gitignore，**不提交**。

## 6. 未解决 / 后续

- 19 项历史 pytest 失败建议另行立项修复（修断言或修 Jimeng plan card 链，需产品决策）。
- 生产部署需确保 `.env` 含本文件 §3 全部变量；否则后端启动即阻断（符合「配置缺失显式报错」）。
- 后续可用 CI 在严格模式 env 下跑一遍冒烟，防止 mock 回退回归。
