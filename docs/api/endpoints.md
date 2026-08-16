# API 端点约定（D1 冻结版）

> 前端（组员B）与后端（组长/组员A）的对接契约。冻结后任何变更需在群里声明。

Base URL: `/api/v1`

## 1. 发起评审

```
POST /reviews
```

**Request**
```json
{
  "brief": {
    "category": "潮玩",
    "market": "TH",
    "budget_range": "mid",
    "time_window": "2026-Q4",
    "weight_template": "default",
    "custom_weights": null,
    "candidate_pool": ["Labubu", "Chiikawa", "线条小狗"]
  }
}
```

**Response 201**
```json
{ "session_id": "sess_20260808_a1b2", "status": "created" }
```

## 2. 查询会议状态（前端轮询/长连接）

```
GET /reviews/{session_id}
```

**Response 200**
```json
{
  "session_id": "sess_20260808_a1b2",
  "current_act": "act3_dual_review",
  "status": "running",
  "acts_completed": ["brief_locked", "act1_insights", "act1_gate", "act2_ideation", "act2_challenge"],
  "live_feed": [
    {
      "act": "act1",
      "agent": "trend_agent",
      "speech_card": {
        "conclusion": "Labubu 处于扩散后期",
        "confidence": "medium",
        "caveats": ["B站排行 ≠ 全网创作热度"],
        "evidence_count": 2
      },
      "timestamp": "2026-08-08T10:01:22Z"
    }
  ],
  "conflicts": [
    {
      "conflict_type": "c1_data_signal",
      "parties": ["trend_agent", "consumer_insight_agent"],
      "description": "消费需求信号与内容创作信号背离"
    }
  ]
}
```

`current_act` 枚举：`brief_locked / act1_insights / act1_gate / act2_ideation / act2_challenge / act3_dual_review / act4_decision / human_gate / approved / revised / rejected / act5_retro / learned / failed`

## 3. 获取立项建议书

```
GET /reviews/{session_id}/report
```

**Response 200**
```json
{
  "session_id": "sess_20260808_a1b2",
  "proposals": [
    {
      "name": "IP娃衣系列",
      "total_score": 76,
      "star_rating": 4,
      "recommendation": "hold",
      "dimension_scores": [
        {"dimension": "trend_heat", "score": 62, "source_agent": "trend_agent"}
      ],
      "risk_warnings": [{"risk": "娃衣复购依赖IP持续热度", "source_dimension": "trend_heat"}],
      "evidence_refs": [{"url": "...", "title": "...", "snippet": "..."}]
    }
  ],
  "divergence_records": [],
  "open_questions": ["需补充多平台趋势数据后复审方向一"],
  "markdown_url": "/api/v1/reviews/{session_id}/report.md"
}
```

## 4. 人工决策（HUMAN_GATE）

```
POST /reviews/{session_id}/decision
```

**Request**
```json
{
  "action": "approve | reject | revise | reweight",
  "reason": "否决/批准理由（action 为 approve/reject 时必填）",
  "custom_weights": null,
  "interrupt": null
}
```

- `reweight`：带 `custom_weights`，仅重跑评分合成（秒级）
- `interrupt`：打断注入，结构 `{"type": "challenge|supplement|redirect", "content": "...", "target_node": "ip_strategy_agent"}`

**Response 200**：返回更新后的状态（同端点 2 格式）

## 5. 权重模板列表

```
GET /weights/templates
```

**Response 200**
```json
{
  "templates": [
    {"key": "default", "label": "默认均衡", "weights": {"trend_heat": 0.35, "..." : "..."}},
    {"key": "volume", "label": "走量款", "weights": {}},
    {"key": "image", "label": "形象款", "weights": {}},
    {"key": "profit", "label": "利润款", "weights": {}}
  ]
}
```

## 错误格式（统一）

```json
{ "error": { "code": "WEIGHT_SUM_INVALID", "message": "五维权重之和必须为 1.0" } }
```

| 错误码 | 含义 |
|:---|:---|
| `BRIEF_INVALID` | 输入契约校验失败 |
| `WEIGHT_SUM_INVALID` | 权重和不为 1 |
| `SESSION_NOT_FOUND` | 会议不存在 |
| `SESSION_NOT_AT_GATE` | 未到人工决策点，不能提交 decision |
| `DECISION_REASON_REQUIRED` | approve/reject 未填理由 |
| `REPORT_NOT_READY` | 会议尚未到达决策，建议书未生成（D2 新增） |

---

# D2 增补（2026-08-09，编排层接入 · 只增不改）

## 动作映射（decision 端点 → 图门词汇）

| 契约动作 | 图内行为 |
|:---|:---|
| `approve` + reason | confirm（理由留痕进 review_logs） |
| `reject` + reason | 否决立项 = **bad case**：记 C4 人机冲突 → 进复盘窗 → 学习官照常归档（负样本） |
| `revise` + reason | modify，可选 `scope: "business"（默认）/"creative"` |
| `reweight` + custom_weights | modify + 新权重写入 state，仅商业官重算（秒级） |
| `chat` + content（新增） | 会后复盘窗对话：LLM 基于本场证据链作答，全部入学习官档案 |
| `done`（新增） | 结束复盘窗，归档 |

## 状态机变化

- 新增门 `retro`（会后复盘窗）：human_gate 结论（approve/reject 均可）后进入；
  窗内只对话、不打回重做；`done` 后学习官归档
- 终态：`approved` / `rejected`
- `GET /reviews/{id}` 响应新增 `pending_gate`（非 null = 正在等人操作，含 gate/prompt/options）
- `GET /reviews/{id}/report` 响应为《立项建议书》全量（ProjectRecommendation：
  proposal / opportunity_score / decision / conditions / dissent_records /
  runner_ups / confidence / summary）；未就绪返回 404 `REPORT_NOT_READY`
- `POST /decision` 响应附 `mapped` 字段（契约动作映射后的图内决策，调试用）

---

# D3 增补（2026-08-09，归档前置 + 历史复盘入口 · 只增不改）

## 顺序调整：归档先于复盘

D2 的顺序是「复盘窗 → 归档」，D3 改为「**归档 → 首次复盘入口**」：

- Gate 2 结论（approve/reject）**立即建档**：`GET /reviews/{id}` 响应新增
  `archive` 字段（快照：proposal / predicted_score / ai_decision / human_action /
  retro_turns / status=archived|rejected），status 同步进入终态 approved/rejected
- 归档不是封存：复盘窗降级为「首次复盘入口」（趁热复盘，可选），
  `done` 后复盘轮数**追加**进 archive.retro_turns
- 事件流中 learning 角色事件出现两次：首次建档、复盘追加；均附 `snapshot` 键

## 历史复盘入口（新增端点 6）

```
POST /reviews/{session_id}/retro
```

归档后**随时**可追问（几天后、复审时），与图内复盘共用同一作答逻辑
（LLM 基于本场证据链摘要，无 Key 降级为产物索引）。

**Request**
```json
{ "question": "为什么第二名落选？" }
```

**Response 200**
```json
{ "session_id": "...", "question": "...", "answer": "...", "timestamp": "..." }
```

每轮问答追加进 `GET /reviews/{id}` 的 `retro_logs`，并累加 `archive.retro_turns`——
人事后的理解与修正同样是学习官的训练信号（人机共训）。

| 新错误码 | 含义 |
|:---|:---|
| `RETRO_NOT_READY` (409) | 会议尚未归档，暂无复盘材料 |
| `RETRO_QUESTION_REQUIRED` (422) | question 必填 |
