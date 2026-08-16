# Stage 11A — 运行时现状审计（Runtime Audit）

> 审计时间：以当前代码（HEAD `fb7ddab`）与 `backend/data/state/plans_state.json` 实际状态为准。
> 本审计不假设任何先前迁移报告的准确性。

## 1. 当前任务清单（plans_state.json 共 6 个）

| plan_id | mode | status | brief.mode | insights.dataSource | evidence | 备注 |
|---------|------|--------|-----------|---------------------|----------|------|
| `demo` | fixture | brief_locked | fixture | — | — | 演示任务 |
| `plan_20260815_1002` | fixture | insights_ready | fixture | **crawled** | — | 旧 crawled 洞察残留 |
| `plan_20260815_2efc` | live | brief_locked | **fixture** | — | — | 半迁移：mode=live 但 brief.mode=fixture |
| `plan_20260815_92be` | live | insights_ready | **fixture** | **crawled** | — | 半迁移：mode=live 但 brief.mode=fixture、旧 crawled 洞察 |
| `plan_20260815_4b82` | live | brief_locked | live | — | — | 新建（真实 live） |
| `plan_20260815_4d4d` | live | insights_ready | live | **feishu** | 30 | 新建（真实 live，feishu 洞察） |

**fixture / live 数量**：fixture = 2（demo、plan_20260815_1002）；live = 4（2efc、92be、4b82、4d4d）。

**实际数据源分布**：
- `feishu`：仅 `plan_20260815_4d4d`（evidence=30）
- `crawled`（旧社媒快照）：`plan_20260815_1002`、`plan_20260815_92be`
- 无 insights：demo、2efc、4b82

## 2. 代码中的真实调用路径

- **fixture**：`app/planning/fixtures.py`（`DATA_BOARD`、`DEMO_BRIEF`、`INSIGHT_BASE`、`TREND_GALLERY`）
- **live（飞书）**：`app/planning/live_data.py::build_live_data_board`、`live_insights.py::build_live_insight_bundle`
- **crawled（社媒快照）**：`app/insights/loaders/social_evidence.py::SocialEvidenceLoader`
- **llm（生成）**：`app/planning/insight_resolver.py::_llm_insight_bundle`

解析入口 `insight_resolver._resolve_insight_bundle(category, brief)`：
- `brief.mode == "live"` 且 `BASE_PROVIDER_MODE == "feishu"` → `live_insights`（真实飞书）
- 否则 → `SocialEvidenceLoader`（crawled）→ 无数据时 LLM

**关键缺陷**：`_resolve_insight_bundle` 仅以「brief.mode + BASE_PROVIDER_MODE」决定来源，未以**任务级 `mode`/`data_source` 契约**为准；`mode=live` 的任务在 `BASE_PROVIDER_MODE != feishu` 时会静默走 crawled/llm，违反「live 不回退 fixture」纪律。

## 3. 状态持久化位置

- 唯一事实源：`app/planning/repository.py` 的 `_PLANS`（进程内存 dict）＋ 原子落盘 `_STATE_FILE = backend/data/state/plans_state.json`（`_save_state()` 唯一临时文件 + rename）。
- 启动恢复：`service.py::seed_demo()` → `_load_state()` 恢复全部任务。
- 路径 `Path(__file__).resolve()` 锚定 ✓。

## 4. 服务重启后任务状态是否保持

- `seed_demo()` 从 `plans_state.json` 恢复 → **保持**。
- 但审计发现 demo / plan_20260815_1002 处于 fixture 态（早前迁移被覆盖回 fixture），说明存在「迁移后文件被再次写回旧状态」或「服务运行中内存旧状态覆盖文件」的不一致窗口。
- 现状：**重启后以当前文件为准，但文件可能已被旧状态覆盖**，缺一个「启动时以 live 态为准、不被旧 fixture 覆盖」的守卫。

## 5. API 是否读取同一数据事实源

- **plan 相关**：`/api/v1/plans`、`/plans/{id}`、`/insights`、`/opportunities`、`/plan-card` 全部经 `pipeline.get_plan` → `repository._PLANS`（**同一事实源**）✓
- **data-board**：`/api/v1/data-board` 独立读取（feishu 模式 → `build_live_data_board`，否则 fixture），**不读 `_PLANS`**，与 plan 状态无关（全局大盘）。

## 6. 旧任务 / 旧 mock 洞察 / 旧机会卡 / 旧企划卡

- 旧 crawled 洞察：`plan_20260815_1002`、`plan_20260815_92be` 的 `insights.dataSource=crawled`。
- 旧机会卡 / 企划卡：当前 6 个任务均无 `opportunities`/`plan_card`（都被清空或从未生成）。
- `demo` 与 `plan_20260815_1002` 为 fixture 态（演示/旧态）。

## 7. 哪些任务实际读取飞书

- 实际读飞书（feishu 洞察已生成）：`plan_20260815_4d4d`。
- 配置为 live 但未读飞书（半迁移 / 无洞察）：`2efc`、`92be`、`4b82`。
- 仍使用 fixture：`demo`、`plan_20260815_1002`。

## 8. 测试失败与 Ruff 错误来源

**pytest：540 passed / 19 failed**（mock 环境）。失败均为**历史失败**，来源：
- `tests/planning/test_pipeline.py`（12）：用户实时链路在 insights 引入 `dataSource` 键、plan card 接入 Jimeng 后，旧断言过期；
- `tests/api/test_planning_api.py`（6）+ `tests/api/test_routes.py`（1）：同上，API 断言过期。

均非本阶段引入；本阶段新增测试不得新增失败。

**Ruff：62 errors**（历史基线）。主要来源：
- `app/xhs/schemas.py`（14）、`app/xhs/api.py`（7）、`app/main.py`（6）、`scripts/build_umbrella_evidence.py`（5）、`app/xhs/stats.py`（2），及散落各 test 文件。
- 均为历史问题，非本阶段引入。

## 9. 结论 / 待解决

1. **任务状态不一致**：`2efc`/`92be` 是 `mode=live` 但 `brief.mode=fixture`、insights 仍为 crawled 的半迁移态；`demo`/`1002` 被旧状态覆盖回 fixture。
2. **缺统一数据上下文契约**：insights/opportunities/plan_card 无可追溯的 `data_source/snapshot/evidence_count` 契约。
3. **缺启动守卫**：启动时旧 fixture 状态可能覆盖已迁移的 live 态。
4. **live 可能静默回退**：`_resolve_insight_bundle` 以环境变量为准，未以任务契约强制 live=feishu。
5. **`live_data.py::_hot_rows` 把 heat_index 命名为 `"sales"`**：违反「禁止把热度标成销量」，需改名。
