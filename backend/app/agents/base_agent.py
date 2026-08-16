"""Agent 基类

所有 Agent 统一继承 BaseAgent，实现 run() 方法。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Agent 抽象基类"""

    name: str = ""
    description: str = ""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent 分析任务

        Args:
            context: 包含输入数据的上下文

        Returns:
            Agent 输出（结构化产物 + evidence_refs）
        """
        ...

    def validate(self, output: dict[str, Any]) -> bool:
        """验证输出是否包含必要字段"""
        return True