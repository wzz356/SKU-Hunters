"""
飞书 Webhook 路由 - 接收飞书消息回调和卡片事件
集成到你的 FastAPI 应用中

第三阶段增强：
- event_id 幂等：飞书回调可能重试，重复 event_id 只处理一次，避免重复启动评审
- 身份校验 fail-closed：配置了 verification_token 时必须匹配，否则 403
- 异步快速返回：事件处理放入后台任务，webhook 立即返回，不阻塞飞书回调
"""

import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .auth import FeishuAuth
from .bot import FeishuBot
from .config import FeishuConfig
from .handler import MessageHandler

# 已处理 event_id 集合（幂等去重）。演示用单机内存；多实例部署应换分布式存储。
_PROCESSED_EVENTS: set[str] = set()
_LOCK = threading.Lock()


def is_event_processed(event_id: str) -> bool:
    """幂等检查：已在处理集合中则 True（重复）；否则登记并返回 False。

    模块级可测试：重复 event_id 只处理一次。
    """
    with _LOCK:
        if event_id in _PROCESSED_EVENTS:
            return True
        _PROCESSED_EVENTS.add(event_id)
    return False


def create_feishu_router(
    config: FeishuConfig,
    bot: Any | None = None,
    handler: Any | None = None,
) -> APIRouter:
    """
    创建飞书 Webhook 路由

    使用方式：
        from feishu import create_feishu_router, FeishuConfig
        config = FeishuConfig.from_env()
        app.include_router(create_feishu_router(config), prefix="/feishu")

    Args:
        config: 飞书配置
        bot: 可选注入（测试用 FakeBot）；默认真实 FeishuBot
        handler: 可选注入（测试用）；默认基于 bot 构建
    """
    router = APIRouter()

    if bot is None:
        auth = FeishuAuth(config)
        bot = FeishuBot(auth)
    if handler is None:
        handler = MessageHandler(bot)

    @router.post("/events")
    async def feishu_events(request: Request):
        """
        飞书事件回调入口
        飞书开放平台配置的回调地址填这个：https://your-domain.com/api/v1/feishu/events
        """
        body = await request.json()

        # 1. 先验证 token（fail-closed，永不绕过）
        #    无论后续是 URL 验证还是事件投递，身份校验都前置执行；
        #    token 缺失或配置缺失一律 403，杜绝鉴权绕过。
        if not config.verification_token:
            raise HTTPException(
                status_code=403, detail="verification_token not configured"
            )
        token = body.get("token", "")
        if not token or token != config.verification_token:
            raise HTTPException(status_code=403, detail="Invalid token")

        # 2. 验证通过后再返回 URL challenge（飞书首次配置回调的验证请求）
        if "challenge" in body:
            return {"challenge": body["challenge"]}

        # 3. event_id 幂等去重（飞书可能重试投递）
        header = body.get("header", {})
        event_id = header.get("event_id") or ""
        if event_id and is_event_processed(event_id):
            return {"code": 0, "msg": "duplicate, ignored"}

        event_type = header.get("event_type", "")
        event = body.get("event", {})

        if event_type == "im.message.receive_v1":
            # 接收消息事件（后台处理，快速返回）
            await handler.handle_message(event)
        elif event_type == "card.action.trigger":
            # 卡片按钮点击事件
            await handler.handle_card_action(event)

        return {"code": 0, "msg": "ok"}

    @router.get("/health")
    async def health():
        """健康检查"""
        return {"status": "ok", "service": "feishu-bot"}

    return router
