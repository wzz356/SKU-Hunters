# OpenClaw 社媒证据采集 Prompt 包

> 用途：让 OpenClaw 按品类采集五看洞察所需的真实社媒证据，产出可喂进管线、可对账的 JSON。
> 落地路径：每个品类产出 JSON 后存到 `backend/app/insights/evidence_sources/social/{品类}_{日期}.json`，
> 队友的 `SocialEvidenceLoader` 会按文件名读取。
> 落盘方式：OpenClaw 只负责"生成 JSON 文本"，本地把这段文本存成文件即可，不用改它任何文件。

## 采集品类清单

| 品类 | 状态 | 发起词 |
|---|---|---|
| 小风扇 / 手持风扇 | ✅ 已示例 | 库洛米 + 小风扇 + 露营 |
| 保温杯 / 随行杯 | ⏳ | 保温杯 |
| 香薰 | ⏳ | 香薰 / 无火香薰 |
| 桌面摆件 | ⏳ | 桌面摆件 / 桌面美学 |
| 雨伞 / 晴雨伞 | ⏳ | 雨伞 / 晴雨伞 |
| 冰袖 / 防晒袖套 | ⏳ | 冰袖 / 防晒袖套 |

---

## 总纲 Prompt（唯一必发，把 {品类} 替换后使用）

```
你是名创优品新品企划的社媒情报采集员。对品类【{品类}】，
按五个模块收集近30-90天的公开社媒数据（小红书为主、抖音/天猫/微博补充），
严格输出一个 JSON，键名按以下结构，不要用别的命名：

{
  "topic": "{品类}",
  "collect_date": "今天日期",
  "trend_signals": [{ "name": "趋势名", "metric": "指标如互动量/增速", "period": "近X天",
                       "domains": ["相关领域"], "opportunity": "对名创的机会判断", "source": "来源" }],
  "hot_words": ["热词1", "热词2"],
  "consumer_voice": {
     "pain_points": [{ "text": "痛点描述", "count": 大致频次 }],
     "scenes": [{ "scene": "场景", "weight": "高/中/低" }],
     "quotes": [{ "text": "用户原声(尽量原话)", "scenario": "场景", "sentiment": "正/负/中性", "source": "来源+日期" }],
     "summary": "一段消费者情绪总述"
  },
  "competitive_map": {
     "products": [{ "name": "品牌/型号", "price": "价格", "selling_point": "核心卖点",
                     "image_url": "商品图URL(尽量给)", "design": 设计感评分0-10 }],
     "price_bands": [{ "band": "价格带", "price": "如29-79", "note": "定位说明" }],
     "gap_zone": "市场空白/差异化机会",
     "selling_points": ["行业主流卖点清单"]
  },
  "insight_base": {
     "hit_products": [{ "title": "爆款/案例", "metric": "销量或收藏等", "source": "来源" }],
     "ip_pool": [{ "ip": "IP名", "why": "为什么适合联名" }],
     "design_language": ["设计风格关键词"]
  },
  "trend_gallery": {
     "colors": ["流行色"], "patterns": ["流行图案"], "shapes": ["流行形状"], "expressions": ["风格关键词"]
  },
  "evidence_refs": [{ "title": "标题", "type": "文章/报告/案例", "publisher": "发布方", "date": "日期", "url": "链接" }]
}

要求：
- 每条数据尽量带来源和日期（可对账）；拿不到精确数字就说"约/百万+"，不要编造
- 某模块搜不到就输出空数组并注明原因，不要硬凑
- competitive_map.products 至少 5 个，尽量给 image_url（商品图）与 selling_point（卖点）
- trend_gallery 是给"流行元素板"用的，务必给流行色/图案/形状/风格关键词
```

---

## 可选：单模块细化 Prompt（总纲不够细时补发）

```
【模块①趋势】对【{品类}】整理近90天社媒趋势信号：至少5条，
每条给互动量级、增速(如+84%)、相关领域、对名创新品的机会判断、来源。

【模块②用户】对【{品类}】收集至少6条真实用户原声(小红书/评论)，标清场景与情绪；
归纳3-5个核心痛点(带频次)与3-5个高频使用场景。

【模块③竞品】对【{品类}】列出至少5个主流竞品(品牌+价格+核心卖点+设计感评分+商品图URL)，
划分价格带分层，给出"名创还没打进去的空白/差异化机会"。

【模块④爆款IP】对【{品类}】找2-3个可复盘爆款案例(销量/收藏/转化数据)，
给出可联名IP池(三丽鸥/库洛米/自有IP等)及适配理由。

【模块⑤元素】对【{品类}】总结当季流行设计元素：流行色、图案、形状、风格关键词各3-5个。
```

---

## 竞品图片说明（已支持）

后端 `CompetitorProduct` 已新增 `image_url` 和 `selling_point` 字段；
前端洞察驾驶舱新增「竞品图板」卡片墙（图+价格+卖点），
`competitive_map.products[].image_url` 有值时显示商品图，无值时显示占位块。
OpenClaw 给到真实商品图 URL，竞品图板就会真实显示。

## 管线对接说明

JSON 键名已按管线五看字段命名（trend_signals→TrendRadar，consumer_voice→ConsumerVoice，
competitive_map→CompetitiveMap，insight_base→InsightBase，trend_gallery→TrendGallery），
loader 读进后直接映射，无需二次改名。
