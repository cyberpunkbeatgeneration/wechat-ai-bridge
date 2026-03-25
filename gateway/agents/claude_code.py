"""
Claude Code Agent - 使用本地 Claude Code 作为主 Agent

支持多实例：
- 每个实例有独立的 session_id
- 可以通过 @c1, @c2 等调用不同实例
- 实例间可以互相通信（通过主 Agent 协调）
"""
import subprocess
import json
import os
import uuid
from typing import Dict, Any, Optional, List
from pathlib import Path

from .base import BaseAgent


class ClaudeCodeInstance:
    """单个 Claude Code 实例"""

    # 历史记录最大轮数
    MAX_HISTORY_ROUNDS = 10

    def __init__(self, instance_id: str, claude_path: str, session_id: str = None,
                 system_prompt: str = None, timeout: int = 120, display_name: str = None):
        self.instance_id = instance_id
        self.claude_path = claude_path
        self.session_id = session_id or str(uuid.uuid4())
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.message_count = 0
        self.display_name = display_name  # 显示名称/别名
        self.history: List[Dict[str, str]] = []  # 对话历史

    def _build_prompt_with_history(self, message: str) -> str:
        """构建带历史的 prompt"""
        if not self.history:
            return message

        # 只取最近的历史
        recent_history = self.history[-(self.MAX_HISTORY_ROUNDS * 2):]

        lines = ["以下是之前的对话历史：", ""]
        for msg in recent_history:
            role = "用户" if msg["role"] == "user" else "助手"
            lines.append(f"[{role}]: {msg['content']}")
        lines.append("")
        lines.append("现在用户的新消息：")
        lines.append(message)

        return "\n".join(lines)

    def chat(self, message: str) -> str:
        """发送消息到这个实例（带历史记忆）"""
        # 构建带历史的 prompt
        prompt_with_history = self._build_prompt_with_history(message)

        cmd = [
            self.claude_path,
            "-p", prompt_with_history,
            "--output-format", "text",
        ]

        if self.system_prompt:
            cmd.extend(["--system-prompt", self.system_prompt])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=os.path.expanduser("~")
            )

            self.message_count += 1

            # 保存历史
            self.history.append({"role": "user", "content": message})

            if result.returncode != 0:
                stderr = result.stderr.strip()
                if stderr:
                    return f"[实例 {self.instance_id} 错误] {stderr[:200]}"
                return f"[实例 {self.instance_id}] 执行失败"

            response = result.stdout.strip()
            if response:
                # 保存助手回复到历史
                self.history.append({"role": "assistant", "content": response})
                # 限制历史长度
                if len(self.history) > self.MAX_HISTORY_ROUNDS * 2:
                    self.history = self.history[-(self.MAX_HISTORY_ROUNDS * 2):]
            return response if response else f"[实例 {self.instance_id}] 无回复"

        except subprocess.TimeoutExpired:
            return f"[实例 {self.instance_id}] 响应超时"
        except Exception as e:
            return f"[实例 {self.instance_id} 错误] {str(e)}"

    def get_info(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "display_name": self.display_name,
            "session_id": self.session_id,
            "message_count": self.message_count,
        }


class ClaudeCodeAgent(BaseAgent):
    """Claude Code 多实例主 Agent"""

    name = "claude_code"

    # 实例配置存储路径
    INSTANCES_FILE = Path(__file__).parent.parent.parent / "gateway_instances.json"

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self._claude_path = self._find_claude()
        self._instances: Dict[str, ClaudeCodeInstance] = {}
        self._aliases: Dict[str, str] = {}  # display_name -> instance_id
        self._load_instances()

    def _find_claude(self) -> Optional[str]:
        """查找 claude CLI 路径"""
        try:
            result = subprocess.run(
                ["which", "claude"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass

        paths = [
            "/usr/local/bin/claude",
            "/opt/homebrew/bin/claude",
            os.path.expanduser("~/.claude/local/claude"),
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    def _load_instances(self):
        """加载保存的实例配置"""
        if self.INSTANCES_FILE.exists():
            try:
                data = json.loads(self.INSTANCES_FILE.read_text())
                for inst_id, info in data.items():
                    inst = ClaudeCodeInstance(
                        instance_id=inst_id,
                        claude_path=self._claude_path,
                        session_id=info.get("session_id"),
                        system_prompt=info.get("system_prompt"),
                        timeout=self.timeout,
                        display_name=info.get("display_name")
                    )
                    self._instances[inst_id] = inst
                    # 注册别名
                    if inst.display_name:
                        self._aliases[inst.display_name.lower()] = inst_id
            except:
                pass

    def _save_instances(self):
        """保存实例配置"""
        data = {}
        for inst_id, inst in self._instances.items():
            data[inst_id] = {
                "session_id": inst.session_id,
                "system_prompt": inst.system_prompt,
                "display_name": inst.display_name,
            }
        self.INSTANCES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def is_available(self) -> bool:
        """检查 Claude Code 是否可用"""
        if not self._claude_path:
            return False
        try:
            result = subprocess.run(
                [self._claude_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except:
            return False

    def resolve_instance_id(self, name_or_id: str) -> Optional[str]:
        """解析实例名称或别名为实例ID"""
        name_lower = name_or_id.lower()
        # 先检查别名
        if name_lower in self._aliases:
            return self._aliases[name_lower]
        # 再检查实例ID
        if name_or_id in self._instances:
            return name_or_id
        return None

    def get_instance(self, name_or_id: str) -> ClaudeCodeInstance:
        """获取或创建实例（支持别名）"""
        # 先尝试解析
        inst_id = self.resolve_instance_id(name_or_id)
        if inst_id:
            return self._instances[inst_id]

        # 不存在则创建新实例
        self._instances[name_or_id] = ClaudeCodeInstance(
            instance_id=name_or_id,
            claude_path=self._claude_path,
            timeout=self.timeout
        )
        self._save_instances()
        return self._instances[name_or_id]

    def create_instance(self, instance_id: str, system_prompt: str = None,
                        display_name: str = None) -> ClaudeCodeInstance:
        """创建新实例"""
        inst = ClaudeCodeInstance(
            instance_id=instance_id,
            claude_path=self._claude_path,
            system_prompt=system_prompt,
            timeout=self.timeout,
            display_name=display_name
        )
        self._instances[instance_id] = inst
        # 注册别名
        if display_name:
            self._aliases[display_name.lower()] = instance_id
        self._save_instances()
        return inst

    def rename_instance(self, name_or_id: str, new_display_name: str) -> Optional[str]:
        """重命名实例（设置显示名称）"""
        inst_id = self.resolve_instance_id(name_or_id)
        if not inst_id:
            return None

        inst = self._instances[inst_id]
        # 移除旧别名
        if inst.display_name:
            self._aliases.pop(inst.display_name.lower(), None)
        # 设置新别名
        inst.display_name = new_display_name
        self._aliases[new_display_name.lower()] = inst_id
        self._save_instances()
        return inst_id

    def list_instances(self) -> List[Dict[str, Any]]:
        """列出所有实例"""
        return [inst.get_info() for inst in self._instances.values()]

    def delete_instance(self, name_or_id: str) -> bool:
        """删除实例（支持别名）"""
        inst_id = self.resolve_instance_id(name_or_id)
        if not inst_id:
            return False

        inst = self._instances[inst_id]
        # 移除别名
        if inst.display_name:
            self._aliases.pop(inst.display_name.lower(), None)
        del self._instances[inst_id]
        self._save_instances()
        return True

    def chat(self, message: str, context: Dict[str, Any] = None) -> str:
        """
        主 Agent 处理消息

        支持特殊指令：
        - /instances - 列出所有实例
        - /new <id> [prompt] - 创建新实例
        - /del <id> - 删除实例
        """
        if not self._claude_path:
            return "[错误] Claude Code 未安装"

        context = context or {}

        # 特殊指令处理
        msg_lower = message.strip().lower()

        if msg_lower == "/instances":
            instances = self.list_instances()
            if not instances:
                return "没有实例。用 /new <id> 创建"
            lines = ["Claude 实例:"]
            for inst in instances:
                name = inst['display_name'] or inst['instance_id']
                id_hint = f" ({inst['instance_id']})" if inst['display_name'] else ""
                lines.append(f"  @{name}{id_hint} - {inst['message_count']} msgs")
            return "\n".join(lines)

        if msg_lower.startswith("/new "):
            parts = message[5:].strip().split(maxsplit=1)
            inst_id = parts[0]
            prompt = parts[1] if len(parts) > 1 else None
            inst = self.create_instance(inst_id, prompt)
            return f"已创建 @{inst_id}\n用 /rename {inst_id} <名称> 设置别名"

        if msg_lower.startswith("/rename "):
            # /rename <id> <新名称>
            parts = message[8:].strip().split(maxsplit=1)
            if len(parts) < 2:
                return "用法: /rename <实例ID> <新名称>\n例: /rename c1 小千"
            old_name, new_name = parts
            inst_id = self.rename_instance(old_name, new_name)
            if inst_id:
                return f"已重命名: @{new_name} (ID: {inst_id})"
            return f"实例 @{old_name} 不存在"

        if msg_lower.startswith("/del "):
            name = message[5:].strip()
            if self.delete_instance(name):
                return f"已删除 @{name}"
            return f"@{name} 不存在"

        # 默认实例处理
        default_inst = self.get_instance("default")

        # 构建 system context
        system_context = """你是微信 AI 网关的主 Agent。

你可以：
1. 直接回答用户问题
2. 创建和管理子实例：
   - /new <id> [prompt] - 创建带特定角色的实例
   - /instances - 查看所有实例
   - 用户可以用 @<id> 消息 来调用特定实例

可用的子模型 API：
- @q / @qwen → 千问
- @d / @deepseek → DeepSeek
- @g / @gemini → Gemini
- @db / @doubao → 豆包

保持回复简洁（微信有字数限制）。
"""

        if not default_inst.system_prompt:
            default_inst.system_prompt = system_context

        return default_inst.chat(message)

    def chat_to_instance(self, instance_id: str, message: str) -> str:
        """发送消息到指定实例"""
        inst = self.get_instance(instance_id)
        return inst.chat(message)
