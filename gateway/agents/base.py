"""
Base Agent - 主 Agent 基类
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


class BaseAgent(ABC):
    """主 Agent 基类"""

    name: str = "base"

    @abstractmethod
    def chat(self, message: str, context: Dict[str, Any] = None) -> str:
        """
        处理消息并返回回复

        Args:
            message: 用户消息
            context: 上下文信息 (sender_id, history 等)

        Returns:
            回复文本
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查 Agent 是否可用"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """获取 Agent 信息"""
        return {
            "name": self.name,
            "available": self.is_available()
        }
