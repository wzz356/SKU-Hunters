# Stage 11A — 统一真实数据链路与任务事实源（最终报告）

> 基准：HEAD `fb7ddab`（未提交本阶段改动）；数据以 `backend/data/state/plans_state.json` 实际内容为准，不假设任何先前迁移报告。
> 状态：**完成，暂停等待人工审核（未 commit / 未 push）**。

---

## 1. 当前真实任务清单（plans_state.json，共 12 个）

| plan_id | mode | brief.mode | insights.dataSource | data_context | status | evidence/record |
|---------|------|-----------|---------------------|--------------|--------|-----------------|
| `demo` | fixture | fixture | — | — | brief_locked | — |
| `plan_20260815_1002` | fixture | fixture | crawled | — | insights_ready | — |
| `plan_20260815_2efc` | **live** | **fixture** | — | — | brief_locked | 半迁移 |
| `plan_20260815_92be` | **live** | **fixture** | crawled | — | insights_ready | 半迁移 |
| `plan_20260815_4b82` | live | live | — | — | brief_locked | — |
| `plan_20260815_4d4d` | live | live | **feishu** | — | insights_ready | 30 / 30 |
| `plan_20260815_2d7c` | fixture | fixture | crawled | — | opportunities_ready | — |
| `plan_20260815_ecaa` | fixture | fixture | crawled | — | opportunities_ready | — |
| `plan_20260815_1e00` | fixture | fixture | crawled | — | opportunities_ready | — |
| `plan_20260815_5a0a` | fixture | fixture | crawled | fixture | opportunities_ready | — |
| `plan_20260815_e4dc` | fixture | fixture | crawled | fixture | opportunities_ready | — |
| `plan_20260815_6dee` | fixture | fixture | crawled | fixture | opportunities_ready | — |

**fixture / live 数量**：
- **fixture = 8**：demo、1002、2d7c、ecaa、1e00、5a0a、e4dc、6dee
- **live = 4**：2efc、92be、4b82、4d4d

**实际数据源分布（按 insights.dataSource）**：
- `feishu`（真实飞书）：仅 `plan_20260815_4d4d`（evidence=30 / record=30）
- `crawled`（旧社媒快照，历史遗留）：1002、92be、2d7c、ecaa、1e00、5a0a、e4dc、6dee（8 个）
- 无洞察：demo、2efc、4b82

**data_context 持久化现状**：仅 3 个 fixture 任务（5a0a / e4dc / 6dee）写入 `dataSource=fixture` 的 data_context；**4 个 live 任务均尚无 data_context**（尚未重新生成以填充 feishu data_context）。多数旧任务仍需按新契约重生成才能补齐统一事实源。

---

## 2. 状态持久化位置

- **唯一事实源**：`app/planning/repository.py` 的进程内存 `_PLANS`（dict）＋ 原子落盘 `backend/data/state/plans_state.json`。
- **原子写**：`_save_state()` 写唯一临时文件后 `tmp.replace(_STATE_FILE)`（同分区 rename，原子）。`data_context` 字段已纳入 `_save_state()` 持久化。
- **路径锚定**：`Path(__file__).resolve()` 锚定，不依赖 cwd。
- **启动恢复**：`service.py::seed_demo()` → `_load_state()` 恢复全部持久化任务（不只 demo）。
- **API 同一事实源**：`/plans`、`/plans/{id}`、`/insights`、`/opportunities`、`/plan-card` 均经 `pipeline.get_plan` → `repository._PLANS`（同一来源）。

---

## 3. 重启前后对比

- `seed_demo()` 逻辑为**优先从持久化文件恢复**（`_load_state()`），仅当无持久化态才新建 fixture demo → 理论上重启后任务状态保持。
- **实测风险**：`demo` / `plan_20260815_1002` 当前落回 **fixture** 态（早前已迁移为 live 但被后续写回覆盖）。说明存在「迁移后文件被旧状态再次写回」的不一致窗口——**当前文件即事实，重启后以文件为准，但文件可能已是旧 fixture 态**。
- **守卫缺口**：启动时目前没有「以 live 态为准、不被旧 fixture 覆盖」的强制守卫。Stage 11A 已通过契约 + 隔离（见 §4/§5）为后续治理打底，但**当前持久化文件需人工用迁移脚本重新收敛**（见 §11）。

---

## 4. 新增契约：统一任务数据上下文（`backend/app/engine/task_data_context.py`）

新建契约文件，未触碰任何冻结 schema：

- `TaskMode`（`fixture` / `live`）
- `DataSource`（`feishu` / `fixture` / `crawled` / `llm` / `unavailable`）
- `TaskDataContext`：`plan_id / mode / data_source / snapshot_id / ingestion_run_id / record_count / evidence_count / generated_at / status / caveats`
- 工厂函数：
  - `build_live_context(...)` → `data_source=feishu`，携带真实 `snapshot_id / ingestion_run_id / record_count / evidence_count / generated_at`
  - `build_fixture_context(...)` → `data_source=fixture`（演示数据，record/evidence 归零，带 caveat）
  - `build_unavailable_context(...)` → `data_source=unavailable`

**契约约束（已实现于 service / insight_resolver）**：
- `live` 任务必须 `data_source=feishu`，`fixture` 任务必须 `data_source=fixture`；
- 禁止 `live` 静默回退 `fixture/crawled/llm`；数据源失败显式抛错或标 `unavailable`；
- `evidence_count` 必须来自真实 evidence refs，不得臆造。

**隔离落点（`app/planning/insight_resolver.py`）**：以**任务 `brief.mode`** 为准——`brief.mode=live` 且 `BASE_PROVIDER_MODE != feishu` → 显式抛 `LLMGenerationError`，拒绝静默回退 fixture/crawled/llm。

**归属说明**：`opportunity`/`plan_card` 属冻结 schema（`Opportunity`/`PlanCard`），不内嵌 data_context，统一从 `plan["data_context"]`（plan 级事实源）溯源；insight bundle 内嵌 `dataContext`（`live_insights.py` 返回 `snapshot_id/ingestion_run_id/record_count/evidence_count/generated_at`）。

---

## 5. 真实数据上下文接入范围

- **insight bundle**：`live_insights.py::build_live_insight_bundle` 返回 `dataContext` ✓
- **plan 级**：`service.py::_build_plan_data_context` 在 `generate_insights` 写入 `plan["data_context"]` ✓
- **data-board / learning snapshot**：`live_data.py` 已把 `"sales"` 改名 `"heat"`（消除「把热度标成销量」），但 data-board 与 learning snapshot **尚未显式挂接 `data_context`**（data-board 为全局大盘、独立读取，不读 `_PLANS`）——列为后续待办。
- **热度不标销量**：`live_data.py` 两处 `"sales"`→`"heat"` 已改，`test_live_data.py` 断言同步修正。

---

## 6. 旧任务 / 旧 mock 洞察处理（迁移脚本增强）

`backend/migrate_fixture_to_live.py`（已存在，本阶段增强）：
- 支持 `--dry-run`：列出所有任务及建议，**不修改任何状态**；
- 支持 `--apply --plan <plan_id>`：只迁移用户指定任务，逐任务原子处理（失败回滚 / BLOCKED）；
- 迁移前自动备份 `plans_state.json`（带时间戳）；
- `_migrate` 写入 `data_context`（导入 `_build_plan_data_context`）；
- 迁移后清理旧 mock 洞察，**不自动生成** opportunity / plan_card（保留人工确认）。

---

## 7. 修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/engine/task_data_context.py` | 新增 | TaskDataContext 契约（Stage 11A 核心） |
| `backend/app/planning/insight_resolver.py` | 修改 | 强制隔离 live/fixture：live+非feishu → 抛错，拒绝静默回退 |
| `backend/app/planning/repository.py` | 修改 | `_save_state()` 持久化 `data_context` |
| `backend/app/planning/service.py` | 修改 | 新增 `_build_plan_data_context`，`generate_insights` 写入 data_context |
| `backend/app/planning/live_insights.py` | 修改 | `build_live_insight_bundle` 返回 `dataContext`（snapshot/ingestion/record/evidence/generated_at） |
| `backend/app/planning/live_data.py` | 修改 | `"sales"`→`"heat"`（两处） |
| `backend/migrate_fixture_to_live.py` | 修改 | 写入 data_context、支持 `--plan`、dry-run 列出全部 fixture 任务 |
| `backend/tests/planning/test_task_data_context.py` | 新增 | 12 个契约/隔离/持久化测试 |
| `backend/tests/planning/test_live_data.py` | 修改 | 修正 sales→heat 断言 |
| `docs/refactor/v2/stage11a-runtime-audit.md` | 新增 | 现状审计（早期 6 任务快照） |
| `docs/refactor/v2/stage11a-final-report.md` | 新增 | 本报告 |

> 前序（Stage 10C–10G / 飞书汇总表 / 迁移脚本）已各自提交；本阶段改动**均未提交**。

---

## 8. 测试结果

- **本阶段新增**：`tests/planning/test_task_data_context.py`（12）+ `test_live_data.py`（2）→ **14 passed**（`pytest -q` 实测通过）。
- 覆盖契约构造 / roundtrip / service data_context / live 不回退 / feishu 失败不回退 / 热度不标销量 / live 洞察 dataContext。
- **全量**：`pytest backend/tests/ --cov=app` → **552 passed + 19 failed**（mock 环境变量：`AGENT_PROVIDER=mock LEARNING_AGENT_PROVIDER=mock BASE_PROVIDER_MODE=mock PLANNING_DEFAULT_MODE=fixture`）。
- 19 个失败均为**历史失败**，非本阶段引入：
  - `tests/planning/test_pipeline.py`（12）：用户实时链路在 insights 加 `dataSource` 键、plan card 接入 Jimeng 后旧断言过期；
  - `tests/api/test_planning_api.py`（6）+ `tests/api/test_routes.py`（1）：API 断言过期。
- 与本阶段契约直接相关的旧断言已修（`test_live_data` 的 sales→heat）；其余历史失败**未擅自改动用户测试**，列入风险。

---

## 9. Ruff 结果

- **本阶段修改/新增文件**：`ruff check` → **All checks passed!**（task_data_context / live_data / live_insights / insight_resolver / repository / service / migrate_fixture_to_live / 两个 test 文件）。
- **全库基线**：62 errors，均为历史问题（`app/xhs/schemas.py` 14、`app/xhs/api.py` 7、`app/main.py` 6、`scripts/build_umbrella_evidence.py` 5、`app/xhs/stats.py` 2 及散落 test），**非本阶段引入，未擅自修改用户代码**。

---

## 10. 构建结果

- `npm run build`（frontend）→ **成功，9.76s**（仅历史 chunk 大小警告）。
- `git diff --check` → 无错误。

---

## 11. 未解决风险与待人工操作

1. **live 任务缺 data_context**：4 个 live 任务（2efc / 92be / 4b82 / 4d4d）均无 `plan["data_context"]`，需在 feishu 模式下重新生成洞察以填充。
2. **半迁移态**：`2efc`/`92be` 是 `mode=live` 但 `brief.mode=fixture`，`92be` 洞察仍为 crawled —— 需人工用迁移脚本 `--plan` 收敛为 `brief.mode=live` + feishu。
3. **demo / 1002 被覆盖回 fixture**：早前已迁移为 live 但落回 fixture，需人工用迁移脚本 `--apply --plan demo`、`--apply --plan plan_20260815_1002` 重新迁移。
4. **fixture 任务洞察仍为 crawled**：8 个 fixture 任务中 7 个 `insights.dataSource=crawled`，与新契约（fixture→dataSource=fixture）不一致，需在 `PLANNING_DEFAULT_MODE=fixture` 下重生成清理旧 crawled 洞察。
5. **data-board / learning snapshot 未挂接 data_context**：后续待办（data-board 为全局大盘独立读取）。
6. **19 个历史 pytest 失败 + 全库 62 ruff errors**：属用户既有代码/过期断言，未擅自改动；建议单独治理。
7. **启动守卫**：尚无「以 live 态为准、不被旧 fixture 覆盖」的强制守卫，建议后续在 `seed_demo` 增加按 data_context 优先级恢复。

---

## 12. 是否需要人工执行凭证轮换或数据迁移

- **凭证轮换**：不需要。本阶段仅读取，未引入/暴露任何新密钥；`BASE_PROVIDER_MODE=feishu` 与 `FEISHU_*` 由 `.env` 提供，运行日志未打印任何 Token/App Secret（全程遵守不打印约束）。
- **数据迁移**：**需要人工确认并执行一次受控迁移**（非自动）：
  - 迁移 `demo`、`plan_20260815_1002` 重新为 live（`--apply --plan`，会先备份）；
  - 收敛 `2efc`/`92be` 半迁移态为 `brief.mode=live` + feishu；
  - 在 `PLANNING_DEFAULT_MODE=fixture` 下重生成 fixture 任务，清除旧 crawled 洞察、补齐 `dataSource=fixture` 的 data_context。
  - 建议先 `python backend/migrate_fixture_to_live.py --dry-run` 查看建议，再逐任务 `--apply`，迁移前核对自动备份。

---

---

## 13. 人工审核后迁移收口（2026-08-16 补充）

用户审核意见：代码实现基本完成，但数据迁移未收口。已按建议执行：

### 13.1 dry-run（全部 12 个任务，只读不改）

全部任务 category 均能匹配飞书数据：小风扇类 11 个（match=438 / evidence=438）、香薰 1 个（4d4d，match=30）。无 BLOCKED。用户确认后仅对 4 个问题任务执行 `--apply`：`demo`、`plan_20260815_1002`、`plan_20260815_2efc`、`plan_20260815_92be`。

### 13.2 发现并修复迁移脚本 bug

首饮 apply 后发现 4 个任务的 `data_context.data_source=fixture, evidence_count=0`，与 insights（feishu/438）矛盾。根因：`_migrate` 中 `_build_plan_data_context` 在设置 `mode=live` **之前**调用，契约按旧 mode=fixture 分支构造。已：
1. 修正脚本调用顺序（先切 mode，再构造 data_context）；
2. 用同一重建路径（重读 feishu bundle + `_build_plan_data_context`）修复 4 个任务并落盘，修复前再次备份。

### 13.3 验收结果（冷启动新进程验证）

| 验收项 | 结果 |
|--------|------|
| live → data_source=feishu | ✅ demo/1002/2efc/92be 全部 feishu |
| live → evidence_count>0 或 unavailable | ✅ 4 个均 438；**4b82（无 insights）、4d4d（有 feishu 洞察但无 data_context）除外**（不在用户批准范围） |
| live → 无旧 fixture/crawled 洞察 | ✅ 4 个迁移任务 insights.dataSource 均为 feishu |
| fixture → 标记演示数据 | ⚠️ 部分：5a0a/e4dc/6dee 有 data_context=fixture；2d7c/ecaa/1e00 无 data_context 且洞察仍为 crawled（待后续在 fixture 模式重生成） |
| 重启 → mode/data_context 不丢 | ✅ 冷启动后 12 任务全部恢复，4 个迁移任务 mode=live + data_context=feishu 保持 |

备份文件：
- `plans_state.pre-live-migration-20260815-213920.json`（首次 apply）
- `plans_state.pre-live-migration-20260815-214040.json`（data_context 修复前）

### 13.4 19 个历史失败逐一归类（全量 552 passed / 19 failed，名单与审计基线完全一致，无新增）

| 类别 | 数量 | 测试 | 根因 |
|------|------|------|------|
| A：insights 多 `dataSource` 键 | 10 | test_pipeline：test_generate_insights_success/failure_advances_status、test_get_insights_returns_five_blocks、test_get_insights_preserves_archived_status 等 | 用户实时链路（Stage 11A 之前的工作区改动）在 insights dict 加 `dataSource` 键，旧断言 `set(insights)=={五块}` 过期 |
| B：plan card/机会链 404 | 6 | test_planning_api：test_plan_card_ok_with_cost_check_and_process_log、test_full_chain_create_to_archive、test_action_generate_insights_advances_status、test_action_archive_full_chain、test_review_readonly_on_archived；test_routes：test_historical_retro_chat_after_archive | plan card 接入 Jimeng 后 `select_opportunity("ip-collect")` 报 OPPORTUNITY_NOT_FOUND 404（实测验证） |
| C：archive 状态不匹配 | 2 | test_pipeline：test_archive_plan_marks_archived…、test_revise_on_archived_raises | 同 B 类根因：流程推进不到 plan_card_ready，archive 抛 StateTransitionError（实测验证） |
| C2：roundtrip 丢 selected_opportunity | 1 | test_pipeline：test_state_roundtrip_save_and_load | 同 B 类根因：selected_opportunity 为 None |

**结论**：19 项全部与 Stage 11A 新契约（TaskDataContext / live 隔离 / repository 持久化）**无因果关系**——均为用户既有实时链路（insights dataSource 键 + Jimeng plan card 链）导致的旧断言过期，且失败名单与本阶段幵工前的审计基线一致。可安全提交 Stage 11A，19 项历史失败建议另行立项修复（修断言或修链路二选一，需产品决策）。

---

**最终结论**：Stage 11A 代码实现 + 受控迁移收口均已完成；验收标准中仅剩两项遗留（4b82/4d4d 的 data_context、3 个 fixture 任务旧 crawled 洞察），均在用户知情范围外/待后续处理。**未 commit、未 push，等待人工审核。**


## 14. 极小收口补丁（人工审核第二轮，2026-08-16）

针对审核提出的两处契约不一致：

1. **4b82/4d4d 补齐 data_context**：`stage11a_closeout.py` 用同一构建路径（`_resolve_insight_bundle` + `_build_plan_data_context`）补齐，未改动 insights/status。结果：4b82 → feishu/438、4d4d → feishu/30。
2. **fixture 任务旧 crawled 洞察清理**：根因是 resolver 的 fixture 分支实际走 `SocialEvidenceLoader`（标 crawled）。已在 `insight_resolver.py` 增加显式 fixture 分支——返回冻结 `fixtures.py` 五看演示数据，标 `dataSource=fixture`，processLog 明示「非真实采集」。9 个 fixture 任务（含执行期间 Aily 新建的 b250/5206/110f）全部重生成，`crawled→fixture`。
3. **冷启动验收（15 任务）**：全部 PASS——6 个 live 均 `data_source=feishu` 且 `evidence_count>0`（4b82 无 insights 属 brief_locked 态，data_context 已有 feishu/438）；9 个 fixture 均 `data_source=fixture` + `insights.dataSource=fixture`；无混合状态。
4. **测试**：全量 `552 passed / 19 failed`，失败名单与 §13.4 基线完全一致（已知基线失败，非全量通过）；本阶段文件 Ruff 全过（含 --fix 2 处 import 排序）。
5. **备份**：`plans_state.pre-closeout-20260815-214653.json`。

**提交说明**：`feat(planning): unify task data context and live/fixture isolation`；正文注明 19 项为已知基线失败（insights dataSource 键 + Jimeng plan card 链导致旧断言过期），与本阶段契约无关。

临时文件：`backend/_patch_resolver.py`（一次性补丁脚本，可删）。
