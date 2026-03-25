#!/usr/bin/env python3
"""
WeChat AI Bridge - MCP Mode

启动 MCP server，供 Claude Code / OpenClaw 等客户端连接。
基于原版 claude_channel_app，扩展了子模型调用 tools。

用法:
    # 通过 Claude Code 启动
    claude --mcp-config .mcp.json

作者: Carol Shen
"""

import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import re
from wechat_agent.constants import BACKOFF_DELAY_MS, MAX_CONSECUTIVE_FAILURES, RETRY_DELAY_MS
from wechat_agent.media import parse_inbound_message
from wechat_agent.state import SYNC_BUF_FILE, get_credentials_file, load_account
from wechat_agent.util import log, sleep_ms
from wechat_agent.wechat import WechatClient

# 使用扩展的 MCP server
from gateway.mcp_server import McpBridgeServer, SessionStore, SESSIONS_DIR
# 子模型注册表
from gateway.models.registry import registry

# 子模型图标映射
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

# @ 路由正则：匹配 @xxx 开头的消息（支持中文）
AT_PATTERN = re.compile(r"^@([\w\u4e00-\u9fff]+)\s*(.*)", re.DOTALL)

# 子模型默认 system prompt（让回复精简）
DEFAULT_SYSTEM_PROMPT = """你在微信聊天。请：
- 回复简洁，像朋友聊天一样
- 除非用户要求写长文/文章，否则控制在 2-3 段以内
- 不要用 Markdown 格式
- 直接回答，不要啰嗦
- 不知道的事情就说不知道，不要瞎编"""

# 用户会话缓存
_session_stores: dict = {}


def _log_startup_state():
    account = load_account()
    if not account:
        log("未找到微信登录凭据，请先运行 npm run claude:setup")
        log(f"凭据文件位置: {get_credentials_file()}")
    elif account.get("source") == "env":
        log("使用环境变量 BOT_TOKEN 登录微信")
    else:
        suffix = f": {account.get('accountId')}" if account.get("accountId") else ""
        log(f"使用本地微信登录凭据{suffix}")


def _get_session_store(sender_id: str) -> SessionStore:
    """获取用户会话存储"""
    if sender_id not in _session_stores:
        _session_stores[sender_id] = SessionStore(sender_id)
    return _session_stores[sender_id]


def _debug_log(msg: str):
    """写调试日志到文件"""
    with open("/tmp/wechat_bridge_debug.log", "a") as f:
        f.write(f"{msg}\n")


# 助手对话 context 文件
ASSISTANT_CONTEXT_FILE = Path(__file__).parent / "gateway_sessions" / "_assistant_context.json"


def _save_assistant_context(sender_id: str, alias: str, label: str, user_msg: str, assistant_msg: str):
    """保存助手对话到 context（静默，不通知 Claude）"""
    import json
    try:
        if ASSISTANT_CONTEXT_FILE.exists():
            data = json.loads(ASSISTANT_CONTEXT_FILE.read_text(encoding="utf-8"))
        else:
            data = {}

        # 每个用户保存最近的助手对话（最多 3 条）
        if sender_id not in data:
            data[sender_id] = []

        data[sender_id].append({
            "alias": alias,
            "label": label,
            "user": user_msg,
            "assistant": assistant_msg[:500]  # 截断避免太长
        })

        # 只保留最近 3 条
        data[sender_id] = data[sender_id][-3:]

        ASSISTANT_CONTEXT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _debug_log(f"[context] Save failed: {e}")


def _get_and_clear_assistant_context(sender_id: str) -> str:
    """获取并清除助手对话 context"""
    import json
    try:
        if not ASSISTANT_CONTEXT_FILE.exists():
            return ""

        data = json.loads(ASSISTANT_CONTEXT_FILE.read_text(encoding="utf-8"))
        if sender_id not in data or not data[sender_id]:
            return ""

        # 构建 context 字符串
        contexts = []
        for item in data[sender_id]:
            contexts.append(f"[{item['label']}] 用户说：「{item['user']}」→ 回复：「{item['assistant']}」")

        # 清除已读的 context
        data[sender_id] = []
        ASSISTANT_CONTEXT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        return "\n\n[最近的助手对话记录]\n" + "\n".join(contexts)
    except Exception as e:
        _debug_log(f"[context] Get failed: {e}")
        return ""

def route_to_submodel(text: str, sender_id: str, context_token: str, wechat_client, mcp_bridge=None) -> bool:
    """
    检查消息是否以 @xxx 开头，如果是则直接路由到子模型。
    支持：
    1. 内置模型别名：@d @q @g 等
    2. 用户自定义助手：@巴巴 @小s 等

    返回 True 表示已处理，False 表示应交给 Claude。
    如果是自定义助手，会把对话内容通知给 Claude（让 Claude 知道助手说了什么）。
    """
    _debug_log(f"[route] called with text: {text[:50]}")

    match = AT_PATTERN.match(text.strip())
    if not match:
        _debug_log(f"[route] No @ pattern match for: {text[:30]}")
        return False

    alias = match.group(1).lower()
    _debug_log(f"[route] Matched alias: {alias}")
    content = match.group(2).strip() or "你好"

    # 1. 先查内置模型
    model = registry.get(f"@{alias}")
    _debug_log(f"[route] registry.get('@{alias}') = {model}")
    if model:
        _debug_log(f"[route] Calling builtin model: {model.name}")
        return _call_builtin_model(model, content, sender_id, context_token, wechat_client)

    # 2. 再查用户自定义助手
    store = _get_session_store(sender_id)
    custom_aliases = store.get_model_aliases()
    _debug_log(f"[route] Custom aliases: {custom_aliases}")

    if alias in custom_aliases:
        model_prefix = custom_aliases[alias]
        # 找到对应的内置模型（model_prefix 已经带 @ 了，如 '@d'）
        model = registry.get(model_prefix)
        _debug_log(f"[route] Custom assistant '{alias}' -> model_prefix='{model_prefix}', model={model}")
        if model:
            return _call_custom_assistant(model, alias, content, sender_id, context_token, wechat_client, store, mcp_bridge)

    # 未知的 @，交给 Claude 处理
    return False


def _call_builtin_model(model, content: str, sender_id: str, context_token: str, wechat_client) -> bool:
    """调用内置模型"""
    if not model.is_available():
        try:
            wechat_client.send_message(sender_id, context_token, f"[{model.name}] 模型未配置 API Key")
        except:
            pass
        return True

    icon = MODEL_ICONS.get(model.name, "🤖")

    try:
        wechat_client.send_message(sender_id, context_token, icon)
    except:
        pass

    log(f"路由到内置模型: {model.name} ({icon})")

    try:
        messages = [{"role": "user", "content": content}]
        response = model.call(messages, system=DEFAULT_SYSTEM_PROMPT)
        wechat_client.send_message(sender_id, context_token, response)
    except Exception as e:
        log(f"内置模型调用失败: {e}")
        try:
            wechat_client.send_message(sender_id, context_token, f"[错误] {e}")
        except:
            pass

    return True


def _call_custom_assistant(model, alias: str, content: str, sender_id: str, context_token: str, wechat_client, store: SessionStore, mcp_bridge=None) -> bool:
    """调用用户自定义助手（带历史记忆）"""
    if not model.is_available():
        try:
            wechat_client.send_message(sender_id, context_token, f"[@{alias}] 对应的 {model.name} 模型未配置 API Key")
        except:
            pass
        return True

    icon = MODEL_ICONS.get(model.name, "🤖")
    # 自定义助手显示：图标+名字，如 🐳巴巴
    assistant_label = f"{icon}{alias}"

    try:
        wechat_client.send_message(sender_id, context_token, assistant_label)
    except:
        pass

    log(f"路由到自定义助手: @{alias} -> {model.name} ({assistant_label})")

    try:
        # 获取历史记录
        history = store.get_history(alias)
        messages = history.copy()
        messages.append({"role": "user", "content": content})

        # 调用模型（带简洁 prompt）
        response = model.call(messages, system=DEFAULT_SYSTEM_PROMPT)

        # 保存到历史
        store.add_message(alias, "user", content)
        store.add_message(alias, "assistant", response)

        wechat_client.send_message(sender_id, context_token, response)

        # 静默保存对话记录（不通知 Claude，等下次用户发消息时带上）
        _save_assistant_context(sender_id, alias, assistant_label, content, response)
        _debug_log(f"[route] Saved {alias}'s response to context file")

    except Exception as e:
        log(f"自定义助手调用失败: {e}")
        try:
            wechat_client.send_message(sender_id, context_token, f"[错误] {e}")
        except:
            pass

    return True


def main():
    log("WeChat AI Bridge (MCP Mode) 启动中...")
    _log_startup_state()

    if not load_account():
        raise RuntimeError("未找到微信登录凭据")

    wechat_client = WechatClient()
    context_token_cache = {}

    # 使用扩展的 MCP server（支持子模型调用）
    mcp_bridge = McpBridgeServer(wechat_client, context_token_cache)
    mcp_bridge.start()

    get_updates_buf = ""
    consecutive_failures = 0
    if SYNC_BUF_FILE.exists():
        try:
            get_updates_buf = SYNC_BUF_FILE.read_text(encoding="utf-8")
            log("恢复上次同步状态")
        except Exception:
            pass

    log("开始监听微信消息...")

    while True:
        try:
            response = wechat_client.get_updates(get_updates_buf)

            is_error = (
                ("ret" in response and response.get("ret") not in (None, 0))
                or ("errcode" in response and response.get("errcode") not in (None, 0))
            )
            if is_error:
                consecutive_failures += 1
                errmsg = response.get("errmsg") or ""
                log(f"getUpdates 失败: ret={response.get('ret')} errcode={response.get('errcode')} errmsg={errmsg}")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log(f"连续失败 {MAX_CONSECUTIVE_FAILURES} 次，等待 {BACKOFF_DELAY_MS // 1000}s...")
                    consecutive_failures = 0
                    sleep_ms(BACKOFF_DELAY_MS)
                else:
                    sleep_ms(RETRY_DELAY_MS)
                continue

            consecutive_failures = 0

            if response.get("get_updates_buf"):
                get_updates_buf = response["get_updates_buf"]
                try:
                    SYNC_BUF_FILE.write_text(get_updates_buf, encoding="utf-8")
                except Exception:
                    pass

            for msg in response.get("msgs") or []:
                if msg.get("message_type") != 1:
                    continue

                inbound = parse_inbound_message(wechat_client, msg)
                if not inbound.text and not inbound.has_media:
                    continue

                sender_id = msg.get("from_user_id") or "unknown"
                context_token = msg.get("context_token")
                if context_token:
                    context_token_cache[sender_id] = context_token
                else:
                    log(f"收到消息但缺少 context_token: from={sender_id.split('@')[0]}，后续可能无法自动回复")

                preview = inbound.text[:60] if inbound.text else "[附件消息]"
                log(
                    f"收到消息: from={sender_id.split('@')[0]} text={preview}"
                    + (f" images={len(inbound.images)} files={len(inbound.files)}" if inbound.has_media else "")
                )

                # 检查是否 @子模型，如果是则直接路由（不经过 Claude）
                if inbound.text and context_token:
                    if route_to_submodel(inbound.text, sender_id, context_token, wechat_client, mcp_bridge):
                        continue  # 已由子模型处理，跳过

                # 发送确认符号（Claude）
                if context_token:
                    try:
                        wechat_client.send_message(sender_id, context_token, "👾")
                    except:
                        pass

                # 获取助手对话 context（如果有的话，附加到消息里）
                assistant_context = _get_and_clear_assistant_context(sender_id)
                prompt_with_context = inbound.prompt + assistant_context if assistant_context else inbound.prompt

                # 通知 Claude
                mcp_bridge.notify_claude_channel(prompt_with_context, sender_id)

        except KeyboardInterrupt:
            raise
        except Exception as err:
            consecutive_failures += 1
            log(f"轮询异常: {err}")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                consecutive_failures = 0
                sleep_ms(BACKOFF_DELAY_MS)
            else:
                sleep_ms(RETRY_DELAY_MS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as err:
        print(f"错误: {err}", file=sys.stderr)
        raise SystemExit(1)
