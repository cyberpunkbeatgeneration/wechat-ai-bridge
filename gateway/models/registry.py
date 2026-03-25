"""
Model Registry - 子模型注册表
"""
import os
from typing import Dict, List, Optional

from .base import BaseModel, http_post


class QwenModel(BaseModel):
    name = "qwen"
    aliases = ["@qwen", "@q"]

    def is_available(self) -> bool:
        return bool(os.environ.get("QWEN_API_KEY"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("QWEN_API_KEY")
        if not api_key:
            return "[错误] 缺少 QWEN_API_KEY"

        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {"model": "qwen-plus", "messages": msgs, "max_tokens": 4096}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[错误] 无返回")


class DeepSeekModel(BaseModel):
    name = "deepseek"
    aliases = ["@deepseek", "@d"]

    def is_available(self) -> bool:
        return bool(os.environ.get("DOUBAO_API_KEY") and os.environ.get("DEEPSEEK_BOT_ID"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("DOUBAO_API_KEY")
        bot_id = os.environ.get("DEEPSEEK_BOT_ID")
        if not api_key or not bot_id:
            return "[错误] 缺少 DOUBAO_API_KEY 或 DEEPSEEK_BOT_ID"

        url = "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {"model": bot_id, "messages": msgs, "max_tokens": 4096}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[错误] 无返回")


class GeminiModel(BaseModel):
    name = "gemini"
    aliases = ["@gemini", "@g"]

    def is_available(self) -> bool:
        return bool(os.environ.get("GOOGLE_API_KEY"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return "[错误] 缺少 GOOGLE_API_KEY"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        payload = {"contents": contents, "generationConfig": {"maxOutputTokens": 4096}}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        candidates = result.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        return "[错误] 无返回"


class DoubaoModel(BaseModel):
    name = "doubao"
    aliases = ["@doubao", "@db"]

    def is_available(self) -> bool:
        return bool(os.environ.get("DOUBAO_API_KEY") and os.environ.get("DOUBAO_BOT_ID"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("DOUBAO_API_KEY")
        bot_id = os.environ.get("DOUBAO_BOT_ID")
        if not api_key or not bot_id:
            return "[错误] 缺少 DOUBAO_API_KEY 或 DOUBAO_BOT_ID"

        url = "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {"model": bot_id, "messages": msgs, "max_tokens": 4096}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[错误] 无返回")


class KimiModel(BaseModel):
    name = "kimi"
    aliases = ["@kimi", "@k"]

    def is_available(self) -> bool:
        return bool(os.environ.get("MOONSHOT_API_KEY"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("MOONSHOT_API_KEY")
        if not api_key:
            return "[错误] 缺少 MOONSHOT_API_KEY"

        url = "https://api.moonshot.cn/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {"model": "moonshot-v1-8k", "messages": msgs, "max_tokens": 4096}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[错误] 无返回")


class MiniMaxModel(BaseModel):
    name = "minimax"
    aliases = ["@minimax", "@m"]

    def is_available(self) -> bool:
        return bool(os.environ.get("MINIMAX_API_KEY") and os.environ.get("MINIMAX_GROUP_ID"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("MINIMAX_API_KEY")
        group_id = os.environ.get("MINIMAX_GROUP_ID")
        if not api_key or not group_id:
            return "[错误] 缺少 MINIMAX_API_KEY 或 MINIMAX_GROUP_ID"

        url = f"https://api.minimax.chat/v1/text/chatcompletion_v2?GroupId={group_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {"model": "abab6.5s-chat", "messages": msgs}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[错误] 无返回")


class GPTModel(BaseModel):
    """OpenAI GPT 模型"""
    name = "gpt"
    aliases = ["@gpt", "@openai", "@o"]

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "[错误] 缺少 OPENAI_API_KEY"

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {"model": "gpt", "messages": msgs, "max_tokens": 4096}

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        return result.get("choices", [{}])[0].get("message", {}).get("content", "[错误] 无返回")


class ClaudeAPIModel(BaseModel):
    """Claude API 模型（作为子模型使用，非主 Agent）"""
    name = "claude_api"
    aliases = ["@claude_api", "@api"]

    def is_available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def call(self, messages: List[Dict], system: str = None) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "[错误] 缺少 ANTHROPIC_API_KEY"

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }

        payload = {"model": "claude-sonnet-4-20250514", "max_tokens": 4096, "messages": messages}
        if system:
            payload["system"] = system

        result = http_post(url, headers, payload)
        if "error" in result:
            return f"[错误] {result['error']}"
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0].get("text", "")
        return "[错误] 无返回"


# ============ 注册表 ============

class ModelRegistry:
    """模型注册表"""

    def __init__(self):
        self._models: Dict[str, BaseModel] = {}
        self._aliases: Dict[str, str] = {}  # alias -> model_name

        # 注册内置模型
        self._register_builtin()

    def _register_builtin(self):
        """注册内置模型"""
        builtin = [
            QwenModel(),
            DeepSeekModel(),
            GeminiModel(),
            DoubaoModel(),
            KimiModel(),
            MiniMaxModel(),
            GPTModel(),
            ClaudeAPIModel(),
        ]
        for model in builtin:
            self.register(model)

    def register(self, model: BaseModel):
        """注册模型"""
        self._models[model.name] = model
        for alias in model.aliases:
            self._aliases[alias.lower()] = model.name

    def get(self, name_or_alias: str) -> Optional[BaseModel]:
        """通过名称或别名获取模型"""
        key = name_or_alias.lower()
        if key in self._models:
            return self._models[key]
        if key in self._aliases:
            return self._models[self._aliases[key]]
        return None

    def list_available(self) -> List[Dict]:
        """列出所有可用模型"""
        return [m.get_info() for m in self._models.values() if m.is_available()]

    def list_all(self) -> List[Dict]:
        """列出所有模型"""
        return [m.get_info() for m in self._models.values()]


# 全局实例
registry = ModelRegistry()
