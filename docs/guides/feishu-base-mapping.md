# Stage 9B · 飞书 Base 字段映射设计（门禁文档）

> 本文件是 Stage 9B 的第一道门禁：在写任何飞书读取代码前，先钉死「飞书表字段 ↔ BaseRecord」的映射、
> 时间字段规则、边界处理与分页/超时/权限契约。
> 字段事实以 `backend/app/schemas/base_data.py`（BaseRecord/BaseQuery）为准；飞书 API 事实以飞书开放平台
> Bitable v1 文档为准；认证复用 `backend/feishu/auth.py`（FeishuAuth）。

---

## 一、目标与范围

**目标**：让 `FeishuBaseProvider`（Stage 9A 中 fail-closed 的占位）接入真实飞书多维表格，作为 `BaseRecord`
的统一只读数据源。

**范围（本阶段）**：
- 只读 provider：查询记录 + 分页 + 字段转换。
- 不写入、不删除、不迁移现有数据（`committee.db`/`xhs.db`/`plans_state.json` 不动）。
- 不实现七位 Agent 完整业务逻辑，不接 `RetroLedgerWriter` 持久化。

**范围（明确不做）**：真实数据导入（第 4 步之后）、RetroLedger 持久化、Agent 业务逻辑改造。

---

## 二、关键发现：Stage 9A 配置假设与现有飞书体系不一致

Stage 9A 的 `FeishuBaseProvider` 用了三枚环境变量，其中两枚的语义与项目现有飞书集成冲突：

| Stage 9A 假设 | 语义 | 问题 |
|--------------|------|------|
| `FEISHU_BASE_TOKEN` | 被当作「直接可用的访问令牌」 | ❌ 飞书不提供可直接使用的长期 token；认证需 `app_id`/`app_secret` 换取 `tenant_access_token` |
| `FEISHU_DATA_TABLE_ID` | 数据表 table_id | ✅ 合理，保留 |
| `FEISHU_SUMMARY_TABLE_ID` | 汇总表 table_id | ✅ 合理，保留 |

项目**已有**一套完整飞书认证（`backend/feishu/auth.py`），Stage 9B 必须复用而非另起炉灶：

| 现有配置 | 用途 |
|---------|------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 换取 `tenant_access_token`（`FeishuAuth` 已实现缓存 + 提前 5 分钟刷新） |
| `FEISHU_BITABLE_APP_TOKEN` / `FEISHU_BITABLE_TABLE_ID` | **企划资产库**（写入方向，企划字段，非采集记录） |

**结论**：`FEISHU_BASE_TOKEN` 语义错误，应废弃；认证统一走 `FeishuAuth`。

---

## 三、飞书认证与配置统一（前提）

### 3.1 认证

复用 `FeishuAuth`：`app_id` + `app_secret` → `tenant_access_token`（`POST /open-apis/auth/v3/tenant_access_token/internal`），
缓存 + 提前 5 分钟过期刷新。**不打印、不落盘 token**。

### 3.2 配置清单（统一后）

| 环境变量 | 语义 | 状态 |
|---------|------|------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 认证（复用现有） | 已有 |
| `FEISHU_BASE_APP_TOKEN` | Base 采集数据多维表格 ID（app_token） | 新增 |
| `FEISHU_DATA_TABLE_ID` | 数据表（采集记录明细）table_id | 保留（Stage 9A） |
| `FEISHU_SUMMARY_TABLE_ID` | 汇总表（聚合摘要/快照）table_id | 保留（Stage 9A） |
| `BASE_PROVIDER_MODE` | `disabled`（默认）/ `mock` / `feishu` | 已有（Stage 9A.1） |

> `FEISHU_BASE_APP_TOKEN` 与现有 `FEISHU_BITABLE_APP_TOKEN`（企划资产库）是**两个不同的多维表格**，
> 前者是「采集记录库」（只读来源），后者是「企划资产库」（归档写入目标），不可混用。

### 3.3 与 `BASE_PROVIDER_MODE` 的关系

- `disabled`（默认）：不读飞书，任何 Base 查询抛 `BaseUnavailable`。
- `mock`：本地 fixture（演示/测试），不碰飞书。
- `feishu`：走真实飞书；缺 `app_id`/`app_secret`/`app_token`/`table_id` 任一 → `BaseUnavailable`（fail-closed）。

---

## 四、数据表字段映射（BaseRecord ↔ 飞书字段）

数据表名：**`base_records`**（采集明细，同一 `FEISHU_BASE_APP_TOKEN` 下）。

飞书字段类型枚举（飞书开放平台 `FieldType`）：`1=Text`、`2=Number`、`3=SingleSelect`、`4=MultiSelect`、
`5=DateTime`、`15=Url`、`1001=CreatedTime` 等。

### 4.1 映射表

| BaseRecord 字段 | 建议飞书字段名 | 飞书 type | 读取转换 | 备注 |
|----------------|--------------|----------|---------|------|
| `record_id` | `record_id` | 1 (Text) | 原样 | 主列；缺省可由飞书 `record_id` 派生 |
| `keyword` | `keyword` | 1 (Text) | 原样 | 必填（`min_length=1`） |
| `platform` | `platform` | 3 (SingleSelect) | 枚举名 → `BasePlatform` | 非法枚举值 → 跳过 + 记 caveat（不归 OTHER） |
| `category` | `category` | 1 (Text) | 原样 | 空 → `""`（default） |
| `summary` | `summary` | 1 (Text) | 原样 | 空 → `""`（default） |
| `heat_index` | `heat_index` | 2 (Number) | float；空 → `None` | 越界（<0 或 >100）→ 校验失败跳过 |
| `interaction` | `interaction` | 2 (Number) | float；空 → `None` | 负值 → 校验失败跳过 |
| `brand` | `brand` | 1 (Text) | 空 → `None` | — |
| `price_range` | `price_range` | 1 (Text) | 空 → `None` | — |
| `record_date` | `record_date` | 5 (DateTime) | 毫秒时间戳 → `YYYY-MM-DD` | 见 §六 |
| `source_url` | `source_url` | 15 (Url) | 非 http(s) → `None` | 缺失/无效不伪造 |
| `snapshot_id` | `snapshot_id` | 1 (Text) | 原样 | 快照锁定（复盘时间机器） |
| `ingested_at` | `ingested_at` | 5 (DateTime) | 毫秒时间戳 → ISO8601 | 缺省可由飞书 `CreatedTime`（1001）兜底 |
| `raw_value` | `raw_value` | 1 (Text) | JSON 字符串 → dict | 解析失败 → `None`（不抛） |

### 4.2 飞书 record 结构 → BaseRecord 的转换要点

飞书查询记录返回每行 `fields`（字典，key 为字段名，value 随字段类型而异）：

- `Text`/`SingleSelect` → `str`（单选返回选项名）。
- `Number` → `float | int`（飞书数字字段可能返回 int/float，统一转 float）。
- `DateTime` → `int`（毫秒时间戳）。
- `Url` → `dict`（含 `link` 与 `text`），取 `link` 作为 `source_url`。

转换规则：**字段缺失 → 用 BaseRecord 默认值；类型不匹配/非法 → 跳过该记录并记一条 caveat（不伪造、不崩溃）**。

---

## 五、汇总表字段映射（聚合摘要）

汇总表名：**`base_summaries`**（聚合快照，同一 `FEISHU_BASE_APP_TOKEN` 下，与 `base_records` 用不同 `table_id` 区分）。

汇总表为**预聚合/快照视图**，对应 `BaseDataAdapter.get_summary()` 的返回形状，用于「复盘时间机器」锁定历史快照，
避免每次实时聚合。

### 5.1 映射表

| 汇总字段 | 建议飞书字段名 | 飞书 type | 对应 get_summary 返回键 |
|---------|--------------|----------|----------------------|
| 品类 | `category` | 1 (Text) | `category` |
| 快照 | `snapshot_id` | 1 (Text) | `snapshot_id` |
| 记录数 | `record_count` | 2 (Number) | `record_count` |
| 平均热度 | `avg_heat_index` | 2 (Number) | `avg_heat_index` |
| 品牌列表 | `brands` | 1 (Text，JSON 数组) | `brands` |
| 数据截止 | `as_of` | 5 (DateTime) | （查询边界，非返回键） |

### 5.2 汇总表定位说明

- 一期**不做静默实时聚合降级**：`get_summary()` 只读 `base_summaries`；汇总表不可用（缺配置/权限不足/空）时
  明确抛 `BaseUnavailable`，绝不静默回退到实时聚合，避免把「数据源不可用」伪装成「有数据」。
- 快照语义：`snapshot_id` 相同 + `as_of` 相同 = 同一历史快照，锁定后不再受数据表后续变更影响。

---

## 六、时间字段规则（record_date / ingested_at / snapshot_id）

| 字段 | 语义 | 飞书存储 | 读取转换 | 校验 |
|------|------|---------|---------|------|
| `record_date` | 业务日期（事实发生日） | DateTime（毫秒） | `ms → YYYY-MM-DD` | `BaseRecord` 校验 YYYY-MM-DD |
| `ingested_at` | 入库时间（进系统时刻） | DateTime（毫秒） | `ms → ISO8601` | 缺省用飞书 `CreatedTime` 兜底 |
| `snapshot_id` | 快照标识（数据版本） | Text | 原样 | 非空；查询时精确匹配锁定 |

**关键约束**：
- `as_of`（查询上界）只与 `record_date` 比较，防学习官读未来数据。
- `snapshot_id` 与 `record_date`/`ingested_at` 三者语义分离，不可混用：`record_date` 是「事件何时发生」，
  `ingested_at` 是「何时入库」，`snapshot_id` 是「哪一版快照」。

**`snapshot_id` 生成规则（已拍板）**：每次采集批次生成一个唯一批次号 `snap-YYYYMMDDTHHMMSSZ-<run-id>`；
同一批数据共用一个 `snapshot_id`，不能只用日期，也不能每条记录单独生成。

---

## 七、边界处理（缺失字段 / 非法值 / 无来源链接）

| 场景 | 处理 | 说明 |
|------|------|------|
| 飞书字段缺失 | 用 BaseRecord 默认值（`""` / `None`） | 不抛异常 |
| `heat_index` 越界（<0 / >100） | 该记录校验失败，**跳过** + 记 caveat | 不伪造合法值 |
| `interaction` 负值 | 同上 | — |
| `platform` 非法枚举 | 记 caveat，**跳过该记录**（不归 OTHER） | — |
| `source_url` 空 / 非 http(s) | → `None` | **不伪造链接**；`build_evidence_refs` 会跳过无 URL 记录 |
| `raw_value` JSON 解析失败 | → `None` | 不抛异常 |
| 日期字段毫秒时间戳非法 | 记 caveat，该记录 `record_date`/`ingested_at` 归 `None` 并跳过 | 见 §六 |

**caveat 约定**：边界处理中「跳过 + 记 caveat」统一由 provider 返回结构化 caveat 列表（`{record_id, field, reason}`），
不静默吞掉，供上层审计；但**不因个别坏记录导致整批查询失败**。

---

## 八、分页 / 超时 / 权限失败契约

### 8.1 分页

- 飞书 `POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search`，单次最多 **500 行**。
- Provider 内部分页：`page_size` 上限 500，用 `page_token` 翻页；`search_all()` 复用 Stage 9A.1 的
  `max_pages=100` + 无进展保护（防死循环）。
- `BaseQuery.page_size` 仍限制 `le=200`（BaseRecord 契约），provider 内部可上调到 500 再回传，对外语义不变。

### 8.2 超时

- 复用现有 `_REQ_TIMEOUT = 10` 秒（`bitable_sync.py` 同款）：飞书正常响应 <2s，10s 无响应视为对端挂死。
- 超时 → `BaseProviderError`（数据源故障），**与「无数据」严格区分**（Stage 9A 契约不变）。

### 8.3 权限失败

- 飞书错误码（`code != 0`）→ 抛 `BaseProviderError`，**不伪装成「无数据」**。
- 高频错误码：`1254001`（请求体错误）、`1254xxx`（Bitable 通用）、`99991672`（token 失效，由 FeishuAuth 刷新兜底）。
- 多维表格开启高级权限时，无权限调用可能「成功但返回空数据」——需在文档/日志中显式警示，不可把「权限不足」
  误判为「确实无数据」。

### 8.4 fail-closed 汇总

| 情况 | 抛出 | 语义 |
|------|------|------|
| `BASE_PROVIDER_MODE=disabled` | `BaseUnavailable` | 未启用 |
| `feishu` 但缺配置 | `BaseUnavailable` | 配置缺失 |
| 网络/超时/飞书非零错误码 | `BaseProviderError` | 数据源故障 |
| 查询成功但 0 条 | 返回空 `BaseRecordPage` | **无数据**（不抛） |

---

## 九、已拍板结论（2026-08-14 定稿）

| # | 事项 | 结论 |
|---|------|------|
| 1 | 数据表/汇总表是否已存在 | **尚未建立**，按新建处理；**不复用**现有「企划资产库」 |
| 2 | 新建表命名 | 同一 `app_token` 下两张表：`base_records`（采集明细）、`base_summaries`（聚合快照） |
| 3 | 字段名 | 按 §四/§五 建议字段名作为建表标准 |
| 4 | 认证变量 | 废弃 `FEISHU_BASE_TOKEN`，统一 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` + `FEISHU_BASE_APP_TOKEN`/`FEISHU_DATA_TABLE_ID`/`FEISHU_SUMMARY_TABLE_ID`；认证复用 `FeishuAuth`，**不自行维护 token** |
| 5 | app_token 数量 | 数据表与汇总表**同一 `FEISHU_BASE_APP_TOKEN`**，用两个 `table_id` 区分 |
| 6 | 非法 `platform` | **跳过 + 记录 caveat**，不归 `OTHER` |
| 7 | `get_summary()` 降级 | 一期**不做静默实时聚合降级**，汇总表不可用就明确失败（`BaseUnavailable`） |
| 8 | `snapshot_id` 生成 | 每次采集批次一个唯一批次号 `snap-YYYYMMDDTHHMMSSZ-<run-id>`；同一批共用，不能只用日期、不能每条单独生成 |

> **关键约束**：真实字段名与真实 `app_token`/`table_id` 尚未核对前，Provider 必须继续 **fail-closed**；
> 只能做 Mock API 测试，不能宣称已接入真实数据。

---

## 十、验收门禁（Stage 9B 第 1 步完成标准）

- [x] 字段映射已定稿（字段名按设计假设，真实字段待建表时核对）。
- [x] 配置统一方案已拍板（§三、§九）。
- [x] 边界处理、分页/超时/权限契约无歧义。
- [x] 待确认事项已逐条闭环（§九）。

> 门禁已通过（2026-08-14）。进入 Stage 9B 第 2 步「实现只读 Feishu Provider」。
> 注意：真实字段名与真实 `app_token`/`table_id` 尚未核对，Provider 必须继续 fail-closed，只做 Mock API 测试。
