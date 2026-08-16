# frontend — 圆桌会议 Dashboard

> 负责人：组员B（D2 开工）

## 开工前必读

1. **API 契约**：`docs/api/endpoints.md`（D1 已冻结，照此对接）
2. **联调数据**：`data/sample/real_data_report.json`（真实数据快照，不是 mock）
3. **技术选型自定**：Vite + React 或飞书妙搭均可，本目录不预设结构

## 三个页面（最小集）

| 页面 | 数据源 | 说明 |
|:---|:---|:---|
| 圆桌直播页 | `GET /api/v1/reviews/{id}` 轮询 | 哪位委员在发言、发言卡、证据数、冲突标记 |
| 立项建议书页 | `GET /api/v1/reviews/{id}/report` | 五维评分解剖、证据链可点击、分歧记录 |
| 机会值看板 | 同上 | 方案对比 + 权重模板切换（`GET /weights/templates`） |
