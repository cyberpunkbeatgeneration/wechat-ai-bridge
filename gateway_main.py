#!/usr/bin/env python3
"""
WeChat Agent Gateway - 微信 AI 网关

两层架构：
- 主 Agent: Claude Code (使用本地 Max 订阅)
- 子模型: @前缀路由到各模型 API

用法:
    python gateway_main.py

作者: Carol Shen
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_agent.wechat import WechatClient
from wechat_agent.state import load_account, SYNC_BUF_FILE

from gateway.core.router import MessageRouter
from gateway.agents.claude_code import ClaudeCodeAgent

# ============ 配置 ============

SESSION_DIR = Path(__file__).parent / "gateway_sessions"
SESSION_DIR.mkdir(exist_ok=True)
MAX_RESPONSE_LENGTH = 1800


# ============ 会话管理 ============

class SessionStore:
    """会话存储"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.file = SESSION_DIR / f"{user_id.replace('@', '_').replace('.', '_')}.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.file.exists():
            try:
                return json.loads(self.file.read_text(encoding="utf-8"))
            except:
                pass
        return {"sessions": {}, "current": "default", "is_new_user": True}

    def is_new_user(self) -> bool:
        """检查是否是新用户"""
        return self.data.get("is_new_user", True)

    def mark_welcomed(self):
        """标记已欢迎"""
        self.data["is_new_user"] = False
        self._save()

    def _save(self):
        self.file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_history(self, model: str = "default") -> List[Dict]:
        session = self.data.get("current", "default")
        return self.data.setdefault("sessions", {}).setdefault(session, {}).setdefault("history", {}).setdefault(model, [])

    def add_message(self, model: str, role: str, content: str):
        history = self.get_history(model)
        history.append({"role": role, "content": content})
        if len(history) > 50:
            history[:] = history[-50:]
        self._save()

    def clear(self):
        session = self.data.get("current", "default")
        if session in self.data.get("sessions", {}):
            self.data["sessions"][session]["history"] = {}
        self._save()

    def new_session(self, name: str = None) -> str:
        name = name or f"s{int(time.time())}"
        self.data.setdefault("sessions", {})[name] = {"history": {}}
        self.data["current"] = name
        self._save()
        return name


# ============ 工具函数 ============

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_my_assistants(store: SessionStore, router: MessageRouter) -> str:
    """获取用户的助手列表"""
    lines = ["📋 我的助手", ""]

    # 用户自定义的模型别名
    user_aliases = store.data.get("model_aliases", {})
    model_names = {
        "@d": "DeepSeek",
        "@q": "千问",
        "@g": "Gemini",
        "@db": "豆包",
        "@k": "Kimi",
        "@m": "MiniMax",
    }

    if user_aliases:
        lines.append("== 自定义助手 ==")
        for alias, model_prefix in user_aliases.items():
            model_name = model_names.get(model_prefix, model_prefix)
            # 获取对话数
            history = store.get_history(alias)
            msg_count = len(history) // 2  # user+assistant 算一轮
            lines.append(f"  @{alias} → {model_name} ({msg_count}轮对话)")
        lines.append("")

    # Claude 实例
    instances = router.primary_agent.list_instances()
    if instances:
        lines.append("== Claude 实例 ==")
        for inst in instances:
            name = inst['display_name'] or inst['instance_id']
            id_hint = f" ({inst['instance_id']})" if inst['display_name'] else ""
            lines.append(f"  @{name}{id_hint}")
        lines.append("")

    # 内置模型
    lines.append("== 内置模型 ==")
    lines.append("  @d DeepSeek | @q 千问 | @g Gemini")
    lines.append("  @db 豆包 | @k Kimi")

    if not user_aliases and not instances:
        lines.insert(2, "还没有自定义助手")
        lines.insert(3, "发「创建一个叫xxx的deepseek助手」试试")
        lines.insert(4, "")

    return "\n".join(lines)


def split_message(text: str, max_len: int = MAX_RESPONSE_LENGTH) -> List[str]:
    """分割长消息"""
    if len(text) <= max_len:
        return [text]

    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break

        split_pos = text.rfind('\n', 0, max_len)
        if split_pos < max_len // 2:
            for p in ['。', '！', '？', '.', '!', '?']:
                pos = text.rfind(p, 0, max_len)
                if pos > max_len // 2:
                    split_pos = pos + 1
                    break

        if split_pos < max_len // 2:
            split_pos = max_len

        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    return parts


WELCOME_MESSAGE = """欢迎使用 AI Gateway!

直接发消息 → Claude (主助手)
@名称 消息 → 指定助手

快捷命令:
/list - 查看我的助手
@q @d @g - 调用千问/DeepSeek/Gemini

试试发: 你好"""


def handle_command(text: str, store: SessionStore, router: MessageRouter) -> str:
    """处理命令"""
    cmd = text.strip().lower()

    if cmd in ("/help", "帮助"):
        return router.get_help()

    if cmd in ("/list", "/助手", "花名册"):
        return get_my_assistants(store, router)

    # 自然语言识别 - 查看助手列表
    list_keywords = ["有哪些助手", "助手列表", "所有助手", "我的助手", "哪些助手", "什么助手", "助手有哪些"]
    if any(kw in cmd for kw in list_keywords):
        return get_my_assistants(store, router)

    if cmd in ("/status", "状态"):
        return router.get_status()

    if cmd.startswith("/new "):
        # 转发给主 Agent 处理
        return router.primary_agent.chat(text)

    if cmd.startswith("/rename "):
        return router.primary_agent.chat(text)

    if cmd == "/instances":
        return router.primary_agent.chat(text)

    if cmd.startswith("/del "):
        return router.primary_agent.chat(text)

    if cmd.startswith("/new"):
        name = cmd.replace("/new", "").strip() or None
        session_id = store.new_session(name)
        return f"新会话: {session_id}"

    if cmd in ("/clear", "清空"):
        store.clear()
        return "已清空当前会话"

    return None


def parse_intent(text: str) -> tuple:
    """
    解析用户意图，识别自然语言命令

    Returns:
        (command, args) 或 (None, None)

    args 格式:
        create: (name, model_type)  # model_type: None=Claude, "deepseek", "qwen", etc.
        rename: (old_name, new_name)
    """
    import re
    text_lower = text.lower()

    # 识别模型类型
    model_type = None
    if 'deepseek' in text_lower or '深度' in text_lower:
        model_type = "deepseek"
    elif 'qwen' in text_lower or '千问' in text_lower or '通义' in text_lower:
        model_type = "qwen"
    elif 'gemini' in text_lower:
        model_type = "gemini"
    elif 'doubao' in text_lower or '豆包' in text_lower:
        model_type = "doubao"
    elif 'kimi' in text_lower:
        model_type = "kimi"

    # 创建实例: "帮我创建一个叫小D的deepseek助手"
    create_match = re.search(
        r'(?:帮我|请)?(?:开|创建|新建|建).*?(?:叫|命名为?|名字是?)\s*[「」""\'"]?([^\s「」""\'的]+)[「」""\'"]?',
        text
    )
    if create_match:
        name = create_match.group(1).strip()
        name = re.sub(r'[的]$', '', name).strip()
        if name and 1 <= len(name) <= 20:
            return ("create", (name, model_type))

    # 简单格式: "创建 xxx"
    simple_create = re.search(
        r'(?:帮我|请)?(?:开|创建|新建)(?:一个)?\s*[「」""\'"]?([a-zA-Z0-9\u4e00-\u9fa5]{1,10})[「」""\'"]?\s*(?:助手|实例|instance)?$',
        text.strip()
    )
    if simple_create:
        name = simple_create.group(1).strip()
        if name and name not in ['一个', '助手', '实例']:
            return ("create", (name, model_type))

    # 重命名: "把xxx改名为yyy"
    rename_match = re.search(
        r'(?:把|将)?\s*[「」""\'"]?([^\s「」""\']+)[「」""\'"]?\s*(?:改名|重命名)\s*(?:为|成|叫)\s*[「」""\'"]?([^\s「」""\']+)[「」""\'"]?',
        text
    )
    if rename_match:
        old_name = rename_match.group(1).strip()
        new_name = rename_match.group(2).strip()
        if old_name and new_name:
            return ("rename", (old_name, new_name))

    return (None, None)


# ============ 主循环 ============

def main():
    log("WeChat Agent Gateway 启动中...")

    # 检查凭据
    account = load_account()
    if not account:
        log("错误: 未找到微信凭据")
        return

    log(f"账号: {account.get('accountId', 'unknown')}")

    # 初始化
    wechat = WechatClient()
    router = MessageRouter()
    context_cache = {}

    # 检查主 Agent
    if router.primary_agent.is_available():
        log(f"主 Agent: Claude Code ✓")
    else:
        log(f"主 Agent: Claude Code ✗ (将使用子模型)")

    # 恢复同步
    get_updates_buf = ""
    if SYNC_BUF_FILE.exists():
        try:
            get_updates_buf = SYNC_BUF_FILE.read_text(encoding="utf-8")
            log("恢复同步状态")
        except:
            pass

    log("开始监听...")
    log("发送 /help 查看帮助")

    consecutive_failures = 0

    while True:
        try:
            response = wechat.get_updates(get_updates_buf)

            # 检查错误
            is_error = (
                ("ret" in response and response.get("ret") not in (None, 0)) or
                ("errcode" in response and response.get("errcode") not in (None, 0))
            )

            if is_error:
                consecutive_failures += 1
                log(f"轮询失败: {response.get('errmsg', 'unknown')}")
                if consecutive_failures >= 3:
                    consecutive_failures = 0
                    time.sleep(30)
                else:
                    time.sleep(2)
                continue

            consecutive_failures = 0

            # 更新同步状态
            if response.get("get_updates_buf"):
                get_updates_buf = response["get_updates_buf"]
                try:
                    SYNC_BUF_FILE.write_text(get_updates_buf, encoding="utf-8")
                except:
                    pass

            # 处理消息
            for msg in response.get("msgs") or []:
                if msg.get("message_type") != 1:
                    continue

                # 提取文本
                text = ""
                for item in msg.get("item_list") or []:
                    if item.get("type") == 1:
                        text = item.get("text_item", {}).get("text", "")
                        break

                if not text:
                    continue

                sender_id = msg.get("from_user_id") or "unknown"
                context_token = msg.get("context_token")

                if context_token:
                    context_cache[sender_id] = context_token

                sender_short = sender_id.split("@")[0][:12]
                log(f"收到 [{sender_short}]: {text[:50]}{'...' if len(text) > 50 else ''}")

                # 会话存储
                store = SessionStore(sender_id)

                # 新用户欢迎
                if store.is_new_user():
                    store.mark_welcomed()
                    log(f"新用户欢迎")
                    try:
                        wechat.send_message(sender_id, context_cache.get(sender_id, context_token), WELCOME_MESSAGE)
                        time.sleep(0.5)  # 等一下再处理消息
                    except Exception as e:
                        log(f"发送欢迎失败: {e}")

                # 检查命令
                cmd_resp = handle_command(text, store, router)
                if cmd_resp:
                    log(f"命令响应")
                    try:
                        wechat.send_message(sender_id, context_cache.get(sender_id, context_token), cmd_resp)
                    except Exception as e:
                        log(f"发送失败: {e}")
                    continue

                # 解析自然语言意图
                intent, args = parse_intent(text)
                if intent == "create":
                    name, model_type = args
                    log(f"意图: 创建 {name} (模型: {model_type or 'claude'})")

                    if model_type:
                        # 绑定到子模型 API（用别名系统）
                        # 创建一个"模型别名"，@小s -> @d
                        model_aliases = {
                            "deepseek": "@d",
                            "qwen": "@q",
                            "gemini": "@g",
                            "doubao": "@db",
                            "kimi": "@k",
                            "minimax": "@m",
                        }
                        model_prefix = model_aliases.get(model_type, "@d")
                        model_display = {
                            "deepseek": "DeepSeek",
                            "qwen": "千问",
                            "gemini": "Gemini",
                            "doubao": "豆包",
                            "kimi": "Kimi",
                            "minimax": "MiniMax",
                        }.get(model_type, model_type)

                        # 存储别名映射（模型别名不需要复杂ID，直接用名字）
                        store.data.setdefault("model_aliases", {})[name.lower()] = model_prefix
                        store._save()

                        reply = f"已创建 @{name} ({model_display})\n\n用 @{name} 消息 来对话\n对话历史会保留"
                    else:
                        # Claude Code 实例 - 需要唯一 ID
                        inst_id = f"c_{int(time.time()) % 10000}"
                        inst = router.primary_agent.create_instance(inst_id, display_name=name)
                        reply = f"已创建 @{name} (Claude)\nID: {inst_id}\n\n用 @{name} 消息 来对话"

                    try:
                        wechat.send_message(sender_id, context_cache.get(sender_id, context_token), reply)
                    except Exception as e:
                        log(f"发送失败: {e}")
                    continue

                if intent == "rename":
                    old_name, new_name = args
                    log(f"意图: 重命名 {old_name} -> {new_name}")
                    result = router.primary_agent.rename_instance(old_name, new_name)
                    if result:
                        reply = f"已重命名: @{new_name} (ID: {result})"
                    else:
                        reply = f"找不到 @{old_name}"
                    try:
                        wechat.send_message(sender_id, context_cache.get(sender_id, context_token), reply)
                    except Exception as e:
                        log(f"发送失败: {e}")
                    continue

                # 解析目标 (target_type: None/model/instance/user_alias, target_id, content)
                target_type, target_id, content = router.parse_message(text)

                if not content and target_type not in ("instance", "user_alias"):
                    continue

                # 检查用户自定义模型别名
                original_alias = None  # 保存原始别名用于独立历史
                if target_type == "user_alias":
                    user_aliases = store.data.get("model_aliases", {})
                    model_prefix = user_aliases.get(target_id.lower())
                    if model_prefix:
                        # 转换为模型调用，但保留原始别名用于独立历史
                        log(f"用户别名 @{target_id} -> {model_prefix}")
                        original_alias = target_id.lower()  # 小s
                        target_type = "model"
                        target_id = model_prefix  # @d
                    else:
                        # 未知别名，当作新 Claude 实例
                        log(f"未知别名 @{target_id}，创建 Claude 实例")
                        target_type = "instance"

                # 构建上下文 - 用户别名有独立历史
                # 如果是用户别名（如 小s），用别名作为 key，而不是模型 key（@d）
                model_key = original_alias or target_id or "agent"
                context = {
                    "sender_id": sender_id,
                    "history": {target_id or "agent": store.get_history(model_key)}
                }

                # 路由处理 - 记录回复来源
                reply_source = None  # 用于标记回复来源
                if target_type == "model":
                    log(f"路由到子模型: {target_id}")
                    # 查找用户给这个模型的别名
                    user_aliases = store.data.get("model_aliases", {})
                    for alias_name, alias_target in user_aliases.items():
                        if alias_target == target_id:
                            model_name = {"@d": "DeepSeek", "@q": "千问", "@g": "Gemini", "@db": "豆包", "@k": "Kimi"}.get(target_id, target_id)
                            reply_source = f"{alias_name} ({model_name})"
                            break
                    if not reply_source:
                        reply_source = {"@d": "DeepSeek", "@q": "千问", "@g": "Gemini", "@db": "豆包", "@k": "Kimi"}.get(target_id, target_id)
                elif target_type == "instance":
                    log(f"路由到实例: @{target_id}")
                    inst = router.primary_agent.get_instance(target_id)
                    info = inst.get_info()
                    name = info.get('display_name') or target_id
                    if info.get('display_name'):
                        reply_source = f"{name} ({target_id})"
                    else:
                        reply_source = name
                else:
                    log(f"路由到主 Agent")
                    reply_source = None  # 主 Agent 不加前缀

                try:
                    reply = router.route(
                        text, context,
                        override_type=target_type,
                        override_id=target_id,
                        override_content=content
                    )
                    # 添加回复来源前缀
                    if reply_source and not reply.startswith("["):
                        reply = f"[{reply_source}]\n{reply}"
                except Exception as e:
                    reply = f"[错误] {str(e)}"

                # 保存历史
                store.add_message(model_key, "user", content)
                store.add_message(model_key, "assistant", reply)

                # 发送回复
                log(f"回复: {reply[:50]}{'...' if len(reply) > 50 else ''}")

                parts = split_message(reply)
                for i, part in enumerate(parts):
                    if i > 0:
                        part = f"[{i+1}/{len(parts)}]\n{part}"
                    try:
                        wechat.send_message(sender_id, context_cache.get(sender_id, context_token), part)
                        if len(parts) > 1:
                            time.sleep(0.5)
                    except Exception as e:
                        log(f"发送失败: {e}")
                        break

        except KeyboardInterrupt:
            log("退出")
            break
        except Exception as e:
            log(f"异常: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
