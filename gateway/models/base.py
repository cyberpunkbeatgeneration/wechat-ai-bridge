"""
Base Model - 子模型基类
"""
import json
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


def http_post(url: str, headers: dict, payload: dict, timeout: int = 120) -> dict:
    """同步 HTTP POST 请求"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"error": str(e)}


class BaseModel(ABC):
    """子模型基类"""

    name: str = "base"
    aliases: List[str] = []  # 别名，如 ["@q", "@qwen"]

    @abstractmethod
    def call(self, messages: List[Dict], system: str = None) -> str:
        """调用模型 API"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查模型是否可用（API key 是否配置）"""
        pass

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "aliases": self.aliases,
            "available": self.is_available()
        }
