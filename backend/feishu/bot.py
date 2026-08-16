"""
飞书消息发送
"""
from typing import Any

import requests

from .auth import FeishuAuth
from .cards import (
    build_committee_card,
    build_start_card,
    build_summary_card,
)

# 飞书 API 正常响应 <2s；10s 无响应视为对端挂死，防止请求方被拖死
_REQ_TIMEOUT = 10


class FeishuBot:
    """飞书机器人消息发送器"""

    def __init__(self, auth: FeishuAuth):
        self.auth = auth
        self.base_url = "https://open.feishu.cn/open-apis/im/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth.get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def send_text(self, chat_id: str, text: str) -> dict[str, Any]:
        """发送纯文本消息"""
        resp = requests.post(
            f"{self.base_url}?receive_id_type=chat_id",
            headers=self._headers(),
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": '{"text": "' + text + '"}',
            },
            timeout=_REQ_TIMEOUT,
        )
        return resp.json()

    def send_card(self, chat_id: str, card: dict[str, Any]) -> dict[str, Any]:
        """发送交互卡片消息"""
        import json
        resp = requests.post(
            f"{self.base_url}?receive_id_type=chat_id",
            headers=self._headers(),
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card),
            },
            timeout=_REQ_TIMEOUT,
        )
        return resp.json()

    # ===== 便捷方法：各委员发言 =====

    @staticmethod
    def build_report_card(
        role: str,
        content: str,
        evidence: list[str] | None = None,
        score: float | None = None,
    ) -> dict[str, Any]:
        """构建委员发言卡片（不发送）——handler 接入 LangGraph 事件流时用"""
        return build_committee_card(
            role=role,
            content=content,
            evidence=evidence,
            score=score,
        )

    def send_committee_report(
        self,
        chat_id: str,
        role: str,
        content: str,
        evidence: list[str] | None = None,
        score: float | None = None,
    ) -> dict[str, Any]:
        """发送委员发言卡片"""
        card = self.build_report_card(
            role=role,
            content=content,
            evidence=evidence,
            score=score,
        )
        return self.send_card(chat_id, card)

    def send_review_start(self, chat_id: str, topic: str) -> dict[str, Any]:
        """发送评审开始卡片"""
        card = build_start_card(topic)
        return self.send_card(chat_id, card)

    def send_review_summary(
        self,
        chat_id: str,
        topic: str,
        final_score: float,
        recommendation: str,
    ) -> dict[str, Any]:
        """发送评审总结卡片"""
        card = build_summary_card(topic, final_score, recommendation)
        return self.send_card(chat_id, card)
