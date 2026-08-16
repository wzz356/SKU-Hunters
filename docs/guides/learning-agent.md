# LearningAgent — 学习官（真实实现）设计文档

> 本阶段把 `learning_node` 从"仅归档快照"升级为受权限约束、可处理真实/缺失实际结果的
> `LearningAgent`，并建立统一的 `NormalizedActualSignal` 契约。**不伪造销量和上市结果。**

## 1. 核心契约

### NormalizedActualSignal（`backend/app/learning/actual_signal.py`）

明确区分实际结果状态，避免把热度/搜索量/聚合数据伪装成销量：

| status | 含义 |
|--------|------|
| `observed` | 有真实、完整实际结果（4 项指标齐备且通过范围校验） |
| `partial` | 只有部分有效结果（部分指标，conf = `low`） |
| `unavailable` | 实际数据源未接入或无数据（conf = `unknown`） |
| `invalid` | 输入存在但字段非法，已跳过（conf = `unknown`） |

字段：`status` / `metrics` / `period` / `source` / `snapshot_id` / `evidence_refs` / `confidence` / `caveats`。

支持的实际指标（0~1 范围校验）：
`first_month_sales_attainment` / `sell_through_rate` / `sellout_rate` / `social_buzz_persistence`。

**规范**：
- 缺失指标不默认填 0；
- 非法数值不静默转 0，跳过并记录 caveat；
- 无 source_url 不伪造 EvidenceRef；
- 统一 `model_dump(mode="json")`。

## 2. 权限边界

- 只读 `views["LearningLedgerReadView"]`；
- 写入只经独立 `write_port = RetroLedgerWriter`（**只追加，不覆盖/删除**）；
- 不持有 `BaseDataAdapter` / Provider / 其他 View / connector；
- 不调用 LLM。

`RetroLedgerWriter` 当前为**内存测试实现**（list），docstring 明确标记未接入持久化，
生产需替换为真实后端（飞书 Base / SQLite）。

> **暂不写入**：`RetroLedgerWriter` 已注入 LearningAgent，但本阶段 LearningAgent 仅生成
> `NormalizedActualSignal` 与 `RetroReport`（写入 `retro_reports` / snapshot），**尚未执行
> 复盘对话的追加落库**。后续复盘对话持久化（`append_retro_entry`）待真实存储后端接入后启用。

## 3. 无实际数据时的行为

`sales_actuals` 未接入 → `status="unavailable"`，`metrics={}`，`confidence="unknown"`，`evidence_refs=[]`，
`caveats=["sales_actuals 未接入，无法获得真实上市结果"]`。

`RetroReport` 保守输出：
- `dimension_gaps` 逐维 `actual_signal="unavailable"`、`accuracy="unknown"`；
- `attribution` 明确"无法进行预测结果归因"；
- `weight_advice=None`；`advice_basis_periods=0`；
- 不生成任何自动调权建议。

数据源故障（`BaseUnavailable` / `BaseProviderError`）→ 同 unavailable，不崩溃、不回退 Mock。

## 4. 首次 / 二次 learning 流程（幂等）

- **首过**：经 `_instantiate_agent("learning")` 生成 `NormalizedActualSignal` + `RetroReport`
  （通过 `RetroReport.model_validate()`），写入 `state["retro_reports"]`；
  保留原有 archive snapshot，learning 事件携带 snapshot。
- **二过**：只把 `retro_turns` 追加到 existing snapshot，**不重复生成 RetroReport**、不重复建档。
- approve/reject 都归档；reject 仍作 bad case。

## 5. Provider 切换

`LEARNING_AGENT_PROVIDER`（默认/未设置 → `MockLearningAgent`；`real` → `LearningAgent`；
real 失败不回退 Mock）。

## 6. 关键文件

- `backend/app/learning/actual_signal.py` — NormalizedActualSignal 契约
- `backend/app/agents/learning_agent.py` — LearningAgent / MockLearningAgent / get_learning_agent_class
- `backend/app/engine/graph.py` — learning 注册表 + access key + learning_node 首过接入
- `backend/tests/agents/test_learning_agent.py` — 25 项测试
