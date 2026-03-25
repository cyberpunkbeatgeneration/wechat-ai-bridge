"""
WeChat AI Bridge - MCP Server

扩展原有 MCP server，添加子模型调用和助手管理功能。
支持 Claude Code / OpenClaw 等任何 MCP client。

Tools:
- wechat_reply: 回复微信消息
- call_model: 调用子模型 (deepseek, qwen, gemini, etc.)
- create_assistant: 创建自定义助手别名
- list_assistants: 列出用户的助手
- get_assistant_history: 获取助手对话历史
"""

import json
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

# 子模型注册
from .models.registry import registry


# ============ 常量 ============

CHANNEL_NAME = "wechat-ai-bridge"
CHANNEL_VERSION = "2.0.0"
MCP_LATEST_PROTOCOL_VERSION = "2024-11-05"
MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05", "2024-10-07"]

SESSIONS_DIR = Path(__file__).parent.parent / "gateway_sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


# ============ 会话存储 ============

class SessionStore:
    """用户会话存储 - 支持智能记忆管理"""

    # 记忆配置
    MAX_RECENT_ROUNDS = 10      # 保留最近 N 轮对话（1轮 = 1问1答 = 2条消息）
    MAX_RECENT_MESSAGES = 20    # = MAX_RECENT_ROUNDS * 2
    MAX_COMPACTS = 5            # 最多保留 N 个 compact 总结
    COMPACT_THRESHOLD = 20      # 超过这么多消息时触发 compact

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.file = SESSIONS_DIR / f"{user_id.replace('@', '_').replace('.', '_')}.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.file.exists():
            try:
                return json.loads(self.file.read_text(encoding="utf-8"))
            except:
                pass
        return {"sessions": {}, "current": "default", "model_aliases": {}}

    def _save(self):
        self.file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_assistant_data(self, model: str) -> dict:
        """获取助手的完整数据（包括 history 和 compacts）"""
        session = self.data.get("current", "default")
        session_data = self.data.setdefault("sessions", {}).setdefault(session, {})
        assistants = session_data.setdefault("assistants", {})

        # 检查旧数据结构（兼容迁移）
        old_history = session_data.get("history", {}).get(model, [])

        if model not in assistants:
            if old_history:
                # 迁移旧数据到新结构
                assistants[model] = {"history": old_history, "compacts": []}
                self._save()
            else:
                assistants[model] = {"history": [], "compacts": []}
        elif not assistants[model].get("history") and old_history:
            # 如果新结构存在但为空，且旧数据有内容，也迁移
            assistants[model]["history"] = old_history
            self._save()

        return assistants[model]

    def get_history(self, model: str = "default") -> list:
        """获取历史记录（包含 compact 总结 + 最近对话）"""
        data = self._get_assistant_data(model)

        # 构建完整的消息列表
        messages = []

        # 1. 先加入 compact 总结（作为 system 消息或开头的 assistant 消息）
        if data.get("compacts"):
            compact_text = "\n\n".join(data["compacts"])
            messages.append({
                "role": "system",
                "content": f"[之前的对话总结]\n{compact_text}"
            })

        # 2. 再加入最近的对话
        messages.extend(data.get("history", []))

        return messages

    def get_raw_history(self, model: str = "default") -> list:
        """获取原始历史记录（不含 compact）"""
        data = self._get_assistant_data(model)
        return data.get("history", [])

    def add_message(self, model: str, role: str, content: str):
        """添加消息，并在需要时触发 compact"""
        data = self._get_assistant_data(model)
        history = data.setdefault("history", [])

        history.append({"role": role, "content": content})

        # 检查是否需要 compact
        if len(history) >= self.COMPACT_THRESHOLD:
            self._do_compact(model, data)

        self._save()

    def _do_compact(self, model: str, data: dict):
        """执行 compact：总结旧对话，保留最近对话"""
        history = data.get("history", [])
        if len(history) < self.COMPACT_THRESHOLD:
            return

        # 分割：旧对话（要总结的）和新对话（保留的）
        old_messages = history[:-self.MAX_RECENT_MESSAGES]
        new_messages = history[-self.MAX_RECENT_MESSAGES:]

        # 生成总结
        summary = self._summarize_messages(old_messages)

        # 更新 compacts
        compacts = data.setdefault("compacts", [])
        compacts.append(summary)

        # 如果 compacts 太多，丢弃最早的
        if len(compacts) > self.MAX_COMPACTS:
            compacts[:] = compacts[-self.MAX_COMPACTS:]

        # 更新 history
        data["history"] = new_messages

    def _summarize_messages(self, messages: list) -> str:
        """总结对话（简单版：提取关键信息）"""
        if not messages:
            return ""

        # 简单总结：提取每轮对话的主题
        summary_parts = []
        for i in range(0, len(messages), 2):
            user_msg = messages[i].get("content", "")[:100] if i < len(messages) else ""
            assistant_msg = messages[i+1].get("content", "")[:100] if i+1 < len(messages) else ""
            if user_msg:
                summary_parts.append(f"用户问：{user_msg[:50]}...")
                if assistant_msg:
                    summary_parts.append(f"回答：{assistant_msg[:50]}...")

        return f"[第{len(summary_parts)//2}轮对话] " + " | ".join(summary_parts[:6])  # 最多6条

    def get_model_aliases(self) -> dict:
        return self.data.get("model_aliases", {})

    def set_model_alias(self, alias: str, model_prefix: str):
        self.data.setdefault("model_aliases", {})[alias.lower()] = model_prefix
        self._save()

    def delete_model_alias(self, alias: str) -> bool:
        """删除自定义助手"""
        aliases = self.data.get("model_aliases", {})
        if alias.lower() in aliases:
            del aliases[alias.lower()]
            # 同时删除历史记录和 compacts
            session = self.data.get("current", "default")
            assistants = self.data.get("sessions", {}).get(session, {}).get("assistants", {})
            if alias.lower() in assistants:
                del assistants[alias.lower()]
            self._save()
            return True
        return False

    def list_all_assistants(self) -> list:
        """列出所有助手（别名 + 内置模型）"""
        result = []
        # 用户自定义别名
        for alias, model_prefix in self.get_model_aliases().items():
            data = self._get_assistant_data(alias)
            history_count = len(data.get("history", [])) // 2
            compact_count = len(data.get("compacts", []))
            result.append({
                "name": alias,
                "type": "custom",
                "model": model_prefix,
                "recent_rounds": history_count,
                "compact_count": compact_count,
                "total_memory": f"{history_count}轮 + {compact_count}个总结"
            })
        return result


# ============ MCP Server ============

class McpBridgeServer:
    """扩展的 MCP Server，支持子模型调用"""

    def __init__(self, wechat_client, context_token_cache: dict):
        self.wechat_client = wechat_client
        self.context_token_cache = context_token_cache
        self._write_lock = threading.Lock()
        self._initialized = False
        self._pending_notifications = []
        self._transport = None
        self._session_stores: Dict[str, SessionStore] = {}
        # 消息队列（polling 模式）
        self._message_queue: list = []
        self._queue_lock = threading.Lock()

    def _get_store(self, sender_id: str) -> SessionStore:
        if sender_id not in self._session_stores:
            self._session_stores[sender_id] = SessionStore(sender_id)
        return self._session_stores[sender_id]

    def start(self):
        thread = threading.Thread(target=self._read_loop, name="mcp-stdio", daemon=True)
        thread.start()

    def notify_claude_channel(self, content: str, sender_id: str):
        """通知 Claude 有新消息"""
        import sys
        print(f"[MCP] notify_claude_channel called, initialized={self._initialized}", file=sys.stderr, flush=True)

        payload = {
            "method": "notifications/claude/channel",
            "params": {
                "content": content,
                "meta": {
                    "sender": sender_id.split("@")[0] if sender_id else sender_id,
                    "sender_id": sender_id,
                },
            },
        }
        with self._write_lock:
            if self._initialized:
                print(f"[MCP] Sending notification to Claude", file=sys.stderr, flush=True)
                self._write_message(payload)
            else:
                print(f"[MCP] Queuing notification (not initialized)", file=sys.stderr, flush=True)
                self._pending_notifications.append(payload)

    def _read_loop(self):
        while True:
            message = self._read_message()
            if message is None:
                return

            method = message.get("method")

            # 处理初始化完成通知（没有 id）
            if method == "notifications/initialized":
                with self._write_lock:
                    self._initialized = True
                    # 发送待发送的通知
                    for pending in self._pending_notifications:
                        self._write_message(pending)
                    self._pending_notifications.clear()
                continue

            # 处理请求（有 id）
            if "id" in message and method:
                self._handle_request(message)

    def _handle_request(self, message: dict):
        method = message.get("method")
        request_id = message.get("id")

        try:
            if method == "initialize":
                self._handle_initialize(request_id, message)
            elif method == "tools/list":
                self._handle_tools_list(request_id)
            elif method == "tools/call":
                self._handle_tools_call(request_id, message)
            elif method == "ping":
                self._send_result(request_id, {})
            else:
                self._send_error(request_id, -32601, f"Method not found: {method}")
        except Exception as err:
            self._send_error(request_id, -32000, str(err))

    def _handle_initialize(self, request_id, message: dict):
        params = message.get("params") or {}
        requested = params.get("protocolVersion")
        protocol_version = (
            requested
            if isinstance(requested, str) and requested in MCP_SUPPORTED_PROTOCOL_VERSIONS
            else MCP_LATEST_PROTOCOL_VERSION
        )

        # 获取可用模型列表
        available_models = []
        for info in registry.list_all():
            if info["available"]:
                available_models.append(f"- {' / '.join(info['aliases'])} → {info['name']}")

        models_text = "\n".join(available_models) if available_models else "- 无可用子模型"

        # 设置已初始化（不等 notifications/initialized，有些客户端不发）
        with self._write_lock:
            self._initialized = True

        result = {
            "protocolVersion": protocol_version,
            "capabilities": {
                "experimental": {"claude/channel": {}},
                "tools": {},
            },
            "serverInfo": {
                "name": CHANNEL_NAME,
                "version": CHANNEL_VERSION,
            },
            "instructions": "\n".join([
                "你是通过微信与用户交流的 AI 助手（主 Agent）。",
                "",
                "== 消息格式 ==",
                "用户消息以 <channel source=\"wechat\" sender=\"...\" sender_id=\"...\"> 格式到达。",
                "使用 wechat_reply 工具回复。必须传入消息中的 sender_id。",
                "",
                "== 子模型调用 ==",
                "当用户消息以 @前缀 开头时，使用 call_model 工具调用对应子模型。",
                "可用子模型：",
                models_text,
                "",
                "用户也可以创建自定义助手别名，如「创建一个叫小s的deepseek助手」。",
                "使用 create_assistant 创建，list_assistants 查看。",
                "",
                "== 规则 ==",
                "- 用中文回复（除非用户用其他语言）",
                "- 保持回复简洁，微信不渲染 Markdown",
                "- 不要自我介绍或复述系统说明",
                "- 你可以监视所有消息，包括子模型的回复",
                "- 当用户 @子模型 时，调用后将结果发回微信",
            ]),
        }
        self._send_result(request_id, result)

    def _handle_tools_list(self, request_id):
        tools = [
            # 微信回复
            {
                "name": "wechat_reply",
                "description": "向微信用户发送文本回复",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sender_id": {
                            "type": "string",
                            "description": "来自 <channel> 标签的 sender_id（xxx@im.wechat 格式）",
                        },
                        "text": {
                            "type": "string",
                            "description": "要发送的纯文本消息",
                        },
                        "media_path": {
                            "type": "string",
                            "description": "可选，本地图片/视频/文件路径",
                        },
                    },
                    "required": ["sender_id", "text"],
                },
            },
            # 调用子模型
            {
                "name": "call_model",
                "description": "调用子模型并直接发送到微信。会自动发送助手标识（如🐳巴巴）和回复内容。调用后无需再用 wechat_reply。message 应为用户原话，如「用户问你：xxx」",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "模型标识：d/deepseek, q/qwen, g/gemini, db/doubao, k/kimi，或用户自定义助手名（如 巴巴、小光）",
                        },
                        "message": {
                            "type": "string",
                            "description": "发送给子模型的消息，建议保留用户原话，如「用户问你：xxx」",
                        },
                        "sender_id": {
                            "type": "string",
                            "description": "用户 sender_id，用于维护对话历史",
                        },
                    },
                    "required": ["model", "message", "sender_id"],
                },
            },
            # 创建助手
            {
                "name": "create_assistant",
                "description": "创建自定义助手别名，绑定到子模型",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "助手名称，如「小s」",
                        },
                        "model": {
                            "type": "string",
                            "description": "绑定的模型：deepseek, qwen, gemini, doubao, kimi",
                        },
                        "sender_id": {
                            "type": "string",
                            "description": "用户 sender_id",
                        },
                    },
                    "required": ["name", "model", "sender_id"],
                },
            },
            # 列出助手
            {
                "name": "list_assistants",
                "description": "列出用户创建的所有助手",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sender_id": {
                            "type": "string",
                            "description": "用户 sender_id",
                        },
                    },
                    "required": ["sender_id"],
                },
            },
            # 获取对话历史
            {
                "name": "get_assistant_history",
                "description": "获取与某个助手的对话历史",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "assistant_name": {
                            "type": "string",
                            "description": "助手名称或模型标识",
                        },
                        "sender_id": {
                            "type": "string",
                            "description": "用户 sender_id",
                        },
                        "limit": {
                            "type": "number",
                            "description": "返回最近 N 条消息，默认 10",
                        },
                    },
                    "required": ["assistant_name", "sender_id"],
                },
            },
            # 删除助手
            {
                "name": "delete_assistant",
                "description": "删除自定义助手（同时删除对话历史）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要删除的助手名称",
                        },
                        "sender_id": {
                            "type": "string",
                            "description": "用户 sender_id",
                        },
                    },
                    "required": ["name", "sender_id"],
                },
            },
        ]
        self._send_result(request_id, {"tools": tools})

    def _handle_tools_call(self, request_id, message: dict):
        params = message.get("params") or {}
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}

        if tool_name == "wechat_reply":
            self._tool_wechat_reply(request_id, arguments)
        elif tool_name == "call_model":
            self._tool_call_model(request_id, arguments)
        elif tool_name == "create_assistant":
            self._tool_create_assistant(request_id, arguments)
        elif tool_name == "list_assistants":
            self._tool_list_assistants(request_id, arguments)
        elif tool_name == "get_assistant_history":
            self._tool_get_history(request_id, arguments)
        elif tool_name == "delete_assistant":
            self._tool_delete_assistant(request_id, arguments)
        else:
            raise RuntimeError(f"unknown tool: {tool_name}")

    def _tool_wechat_reply(self, request_id, arguments: dict):
        sender_id = str(arguments.get("sender_id") or "")
        text = str(arguments.get("text") or "")
        media_path = str(arguments.get("media_path") or "").strip()

        if not text and not media_path:
            raise RuntimeError("text 和 media_path 至少要提供一个")

        context_token = self.context_token_cache.get(sender_id)
        if not context_token:
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"error: 找不到 {sender_id} 的 context_token"}]
            })
            return

        try:
            if media_path:
                self.wechat_client.send_media_message(sender_id, context_token, text[:1000], media_path)
            else:
                self.wechat_client.send_message(sender_id, context_token, text[:1000])
            self._send_result(request_id, {"content": [{"type": "text", "text": "sent"}]})
        except Exception as err:
            self._send_result(request_id, {"content": [{"type": "text", "text": f"send failed: {err}"}]})

    # 模型图标映射
    MODEL_ICONS = {
        "deepseek": "🐳",
        "qwen": "🦄",
        "gemini": "💠",
        "doubao": "🌱",
        "kimi": "🌑",
        "minimax": "🐚",
        "claude_api": "🍥",
        "gpt": "🍬",
    }

    # 子模型默认 system prompt（让回复精简）
    DEFAULT_SYSTEM_PROMPT = """你在微信聊天。请：
- 回复简洁，像朋友聊天一样
- 除非用户要求写长文/文章，否则控制在 2-3 段以内
- 不要用 Markdown 格式
- 直接回答，不要啰嗦
- 不知道的事情就说不知道，不要瞎编"""

    def _tool_call_model(self, request_id, arguments: dict):
        model_key = str(arguments.get("model") or "").lower()
        message = str(arguments.get("message") or "")
        sender_id = str(arguments.get("sender_id") or "")
        send_to_wechat = arguments.get("send_to_wechat", True)  # 默认直接发微信

        if not model_key or not message:
            raise RuntimeError("model 和 message 是必填的")

        store = self._get_store(sender_id)

        # 检查是否是用户自定义别名
        user_aliases = store.get_model_aliases()
        is_custom_assistant = model_key in user_aliases
        if is_custom_assistant:
            actual_model = user_aliases[model_key]
            history_key = model_key  # 用别名作为历史 key
            assistant_name = model_key  # 自定义助手名
        else:
            # 标准化模型名
            if not model_key.startswith("@"):
                model_key = f"@{model_key}"
            actual_model = model_key
            history_key = model_key
            assistant_name = None  # 内置模型不显示名字

        # 获取模型
        model = registry.get(actual_model)
        if not model:
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"error: 未知模型 {model_key}"}]
            })
            return

        if not model.is_available():
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"error: {model.name} 不可用，请检查 API Key"}]
            })
            return

        # 构建助手标识（如 🐳巴巴 或 🐳）
        icon = self.MODEL_ICONS.get(model.name, "🤖")
        assistant_label = f"{icon}{assistant_name}" if assistant_name else icon

        # 构建消息（带历史）
        history = store.get_history(history_key)
        messages = history + [{"role": "user", "content": message}]

        try:
            reply = model.call(messages, system=self.DEFAULT_SYSTEM_PROMPT)
            # 保存历史
            store.add_message(history_key, "user", message)
            store.add_message(history_key, "assistant", reply)

            # 如果需要直接发微信（模拟直接路由的格式）
            if send_to_wechat:
                context_token = self.context_token_cache.get(sender_id)
                if context_token:
                    try:
                        # 先发标识
                        self.wechat_client.send_message(sender_id, context_token, assistant_label)
                        # 再发内容
                        self.wechat_client.send_message(sender_id, context_token, reply[:1000])
                    except:
                        pass

            # 返回结果给 Claude（带标识）
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"{assistant_label}\n{reply}"}]
            })
        except Exception as err:
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"error: {str(err)}"}]
            })

    def _tool_create_assistant(self, request_id, arguments: dict):
        name = str(arguments.get("name") or "").strip()
        model = str(arguments.get("model") or "").lower()
        sender_id = str(arguments.get("sender_id") or "")

        if not name or not model:
            raise RuntimeError("name 和 model 是必填的")

        # 模型映射
        model_aliases = {
            "deepseek": "@d",
            "qwen": "@q",
            "gemini": "@g",
            "doubao": "@db",
            "kimi": "@k",
            "minimax": "@m",
        }
        model_prefix = model_aliases.get(model)
        if not model_prefix:
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"error: 未知模型 {model}，可选: deepseek, qwen, gemini, doubao, kimi"}]
            })
            return

        store = self._get_store(sender_id)
        store.set_model_alias(name, model_prefix)

        model_display = {
            "deepseek": "DeepSeek",
            "qwen": "千问",
            "gemini": "Gemini",
            "doubao": "豆包",
            "kimi": "Kimi",
        }.get(model, model)

        self._send_result(request_id, {
            "content": [{"type": "text", "text": f"已创建助手 @{name} ({model_display})"}]
        })

    def _tool_list_assistants(self, request_id, arguments: dict):
        sender_id = str(arguments.get("sender_id") or "")
        store = self._get_store(sender_id)
        assistants = store.list_all_assistants()

        if not assistants:
            text = "还没有自定义助手。\n\n内置模型：@d(DeepSeek) @q(千问) @g(Gemini) @db(豆包) @k(Kimi)"
        else:
            lines = ["自定义助手："]
            model_names = {"@d": "DeepSeek", "@q": "千问", "@g": "Gemini", "@db": "豆包", "@k": "Kimi"}
            for a in assistants:
                model_name = model_names.get(a["model"], a["model"])
                lines.append(f"- @{a['name']} → {model_name} ({a['message_count']}轮对话)")
            lines.append("\n内置模型：@d @q @g @db @k")
            text = "\n".join(lines)

        self._send_result(request_id, {"content": [{"type": "text", "text": text}]})

    def _tool_get_history(self, request_id, arguments: dict):
        assistant_name = str(arguments.get("assistant_name") or "").lower()
        sender_id = str(arguments.get("sender_id") or "")
        limit = int(arguments.get("limit") or 10)

        store = self._get_store(sender_id)
        history = store.get_history(assistant_name)[-limit*2:]  # user+assistant 成对

        if not history:
            text = f"@{assistant_name} 还没有对话历史"
        else:
            lines = [f"@{assistant_name} 最近对话："]
            for msg in history:
                role = "用户" if msg["role"] == "user" else "助手"
                content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
                lines.append(f"[{role}] {content}")
            text = "\n".join(lines)

        self._send_result(request_id, {"content": [{"type": "text", "text": text}]})

    def _tool_delete_assistant(self, request_id, arguments: dict):
        name = str(arguments.get("name") or "").strip()
        sender_id = str(arguments.get("sender_id") or "")

        if not name:
            raise RuntimeError("name 是必填的")

        store = self._get_store(sender_id)
        if store.delete_model_alias(name):
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"已删除助手 @{name}（对话历史也已清除）"}]
            })
        else:
            self._send_result(request_id, {
                "content": [{"type": "text", "text": f"助手 @{name} 不存在"}]
            })

    # ============ MCP 通信 ============

    def _read_message(self):
        if self._transport == "jsonl":
            return self._read_jsonl_message()
        if self._transport == "framed":
            return self._read_framed_message()

        first_line = sys.stdin.buffer.readline()
        if not first_line:
            return None
        if first_line in (b"\r\n", b"\n"):
            return self._read_message()

        stripped = first_line.lstrip()
        if stripped.startswith((b"{", b"[")):
            self._transport = "jsonl"
            return json.loads(first_line.decode("utf-8"))

        self._transport = "framed"
        return self._read_framed_message(first_line=first_line)

    def _read_jsonl_message(self):
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                continue
            return json.loads(line.decode("utf-8"))

    def _read_framed_message(self, first_line=None):
        headers = {}
        line = first_line
        while True:
            if line is None:
                line = sys.stdin.buffer.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                break
            if ":" in decoded:
                key, value = decoded.split(":", 1)
                headers[key.strip().lower()] = value.strip()
            line = None

        content_length = int(headers.get("content-length", "0"))
        if content_length <= 0:
            return None

        body = sys.stdin.buffer.read(content_length)
        if not body:
            return None

        return json.loads(body.decode("utf-8"))

    def _send_result(self, request_id, result):
        with self._write_lock:
            self._write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _send_error(self, request_id, code, message):
        with self._write_lock:
            self._write_message({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            })

    def _write_message(self, message):
        if "jsonrpc" not in message:
            message = {"jsonrpc": "2.0", **message}
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if self._transport == "jsonl":
            sys.stdout.buffer.write(body + b"\n")
        else:
            sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
            sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()
