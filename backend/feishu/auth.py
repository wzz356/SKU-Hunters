"""
飞书认证 - tenant_access_token 管理
自动缓存和刷新 token
"""
import time

import requests

from .config import FeishuConfig


class FeishuAuth:
    """飞书认证管理器"""

    def __init__(self, config: FeishuConfig):
        self.config = config
        self._token: str = ""
        self._expire_at: float = 0

    def get_token(self) -> str:
        """获取有效的 tenant_access_token"""
        if self._is_token_valid():
            return self._token
        self._refresh_token()
        return self._token

    def _is_token_valid(self) -> bool:
        """检查 token 是否还有效（提前5分钟过期）"""
        return self._token and time.time() < self._expire_at - 300

    def _refresh_token(self):
        """刷新 token"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(
            url,
            json={
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret,
            },
            timeout=10,  # 防止飞书挂死时请求方被无限拖住
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书token失败: {data}")
        self._token = data["tenant_access_token"]
        self._expire_at = time.time() + data["expire"]
