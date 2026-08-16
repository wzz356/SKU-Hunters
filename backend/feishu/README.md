# 飞书对接模块使用说明

## 功能

- 飞书群里 @机器人 说「评审 XXX」，自动启动一轮 AI 委员会评审
- 7 个委员用不同颜色的卡片发言，模拟圆桌讨论
- 最后输出评审结论卡片，带「通过/否决」按钮，真人拍板
- 已接入 LangGraph `run_review()` 事件流：委员 + 质询环节用不同颜色卡片发言
- 卡片内容全部来自 LangGraph 事件 / Artifact，禁止硬编码角色结论与评分
- 人工 Gate（洞察确认/立项拍板/复盘）发带 `session_id` 按钮卡片，点击后恢复同一
  LangGraph checkpoint（不重启流程）；支持文本指令 `通过/否决/修改/追问/结束`
- webhook 保持身份校验（fail-closed）+ event_id 幂等 + 异步快速返回

## 文件结构

```
feishu/
├── __init__.py      # 模块入口
├── config.py        # 配置（从环境变量读取）
├── auth.py          # Token 管理（自动缓存刷新）
├── cards.py         # 7个委员的卡片模板
├── bot.py           # 消息发送封装
├── handler.py       # 消息处理 + 评审流程调度
└── webhook.py       # FastAPI 路由
```

## 快速开始

### 1. 创建飞书应用

1. 访问 https://open.feishu.cn → 开发者后台
2. 创建企业自建应用，名字「SKU 委员会」
3. 添加应用能力 → 开启「机器人」
4. 权限管理 → 开通：
   - `im:message`（发送消息）
   - `im:message.receive_v1`（接收消息）
5. 事件与回调 → 配置请求地址：
   - `https://你的域名/feishu/webhook`
   - 本地开发用内网穿透（cpolar/ngrok）
   - 订阅事件：`接收消息 v2.0`
6. 拿到 App ID 和 App Secret

### 2. 配置环境变量

在 `.env` 文件中添加：

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_VERIFICATION_TOKEN=xxxxxxxx  # 事件与回调页面的 Verification Token
FEISHU_ENCRYPT_KEY=xxxxxxxx         # 加密 Key（如果开启了加密）
```

### 3. 集成到 FastAPI

在你的主应用文件中添加：

```python
from fastapi import FastAPI
from feishu import FeishuConfig
from feishu.webhook import create_feishu_router

app = FastAPI()

# 注册飞书路由
config = FeishuConfig.from_env()
app.include_router(create_feishu_router(config), prefix="/feishu")
```

### 4. 把机器人拉进群

1. 在飞书群里 → 群设置 → 群机器人 → 添加机器人
2. 搜索你创建的「SKU 委员会」应用，添加进去

### 5. 测试

在群里 @SKU委员会 说：
```
评审 解压玩具
```

应该会看到：
1. 一张「评审开始」卡片
2. 然后依次出现 7 个委员的发言卡片（趋势官是真实逻辑，其他是占位）
3. 最后一张「评审结论」卡片，带通过/否决按钮

## 接入你的 Agent

### 接入趋势官（已预留接口）

在 `handler.py` 的 `_run_review` 方法中，趋势官部分：

```python
# 已经写好了，只要你的 TrendAgent 有 analyze 方法，返回 dict
from agents.trend_agent import TrendAgent
agent = TrendAgent()
result = agent.analyze(topic)
# result 格式：
# {
#     "content": "趋势分析内容...",
#     "evidence": ["来源1", "来源2", ...]
# }
```

### 接入其他 Agent

把 `handler.py` 中对应的占位代码替换成真实 Agent 调用即可。每个 Agent 的返回格式统一为：

```python
{
    "content": "分析内容（支持 markdown）",
    "evidence": ["证据1", "证据2", ...],  # 可选
    "score": 85.5,  # 可选，商业官用
}
```

## 后续替换为 LangGraph

等你的 LangGraph 编排写好了，把 `handler.py` 里的 `_run_review` 方法整个替换掉就行：

```python
async def _run_review(self, chat_id: str, topic: str):
    # 原来的串行代码替换成 LangGraph 调用
    from your_langgraph_app import run_review
    async for event in run_review(topic):
        # event: {"role": "trend", "content": "...", "evidence": [...]}
        self.bot.send_committee_report(
            chat_id=chat_id,
            role=event["role"],
            content=event["content"],
            evidence=event.get("evidence"),
            score=event.get("score"),
        )
```

## 本地开发调试

### 内网穿透（让飞书能调通你本地的接口）

推荐用 cpolar 或 ngrok：

```bash
# 假设你的 FastAPI 跑在 8000 端口
cpolar http 8000
# 得到一个公网地址，比如 https://abc.cpolar.cn
# 飞书回调地址填：https://abc.cpolar.cn/feishu/webhook
```

### 测试发送消息

不用等飞书回调，直接写个测试脚本：

```python
from feishu import FeishuConfig
from feishu.auth import FeishuAuth
from feishu.bot import FeishuBot

config = FeishuConfig.from_env()
auth = FeishuAuth(config)
bot = FeishuBot(auth)

# 发个测试消息（chat_id 从群链接或 API 获取）
bot.send_text("oc_xxxxxxxxxx", "hello from SKU Hunters!")
```

## 常见问题

**Q: 收不到消息回调？**
- 检查回调地址是否正确（要公网可访问）
- 检查事件订阅是否开启了「接收消息 v2.0」
- 检查机器人是否已经被拉进群

**Q: 发消息失败？**
- 检查 App ID 和 App Secret 是否正确
- 检查权限是否开通了 `im:message`
- 检查机器人是否在群里

**Q: @机器人没反应？**
- 检查消息里是否真的 @ 了机器人（飞书会把 @ 替换成 @_user_1）
- 检查 handler.py 里的正则是否匹配

## 已知限制（生产部署前必须处理）

**Gate / 会话状态仅在进程内存中（checkpoint 恢复不支持进程重启）**

- `MessageHandler._sessions`、`gate_future` 都保存在内存中，LangGraph 的 checkpoint
  （thread_id=session_id）虽然持久化在磁盘，但进程一旦重启：
  - `_sessions` 与 `gate_future` 全部丢失；
  - 飞书按钮携带的 `session_id` 会返回 `no pending gate`；
  - 无法真正恢复人工 Gate。
- **当前能力边界**：仅支持「同一进程内」恢复 checkpoint，**不支持服务重启后恢复**。
  明天演示可接受，生产上线前必须处理。
- **建议的修复方向**（二选一）：
  1. 将 pending gate / session 元数据落盘持久化（如 SQLite/Redis），重启后按
     `session_id` 重建 Gate 状态；
  2. 按钮直接调用 LangGraph 的 `Command(resume=...)` 恢复 checkpoint，不依赖内存
     `Future`。

**鉴权（fail-closed）**
- webhook 一律先校验 token：token 缺失或 `FEISHU_VERIFICATION_TOKEN` 未配置时直接
  返回 403，验证通过后才返回 URL challenge。生产必须配置 `verification_token`。

**发送失败状态**
- `send_text` / `send_card` 返回非零 `code` 时抛 `BotSendError`，`_run_review` 将会话
  置为 `failed` 并保存 `error` / `failed_stage` / `last_event`，不会错误地显示为
  `completed`。
