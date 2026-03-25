"""
Message Router - 消息路由器

两层架构：
1. 主 Agent (Claude Code) - 处理无前缀消息，支持多实例
2. 子模型 (@前缀) - 直接路由到对应模型 API

多实例支持：
- @c1, @c2 等 → Claude Code 子实例
- /new <id> [prompt] → 创建新实例
- /instances → 列出所有实例
"""
import re
from typing import Tuple, Optional, List, Dict, Any

from ..agents.base import BaseAgent
from ..agents.claude_code import ClaudeCodeAgent
from ..models.registry import registry, BaseModel


class MessageRouter:
    """消息路由器"""

    def __init__(self, primary_agent: ClaudeCodeAgent = None):
        """
        初始化路由器

        Args:
            primary_agent: 主 Agent，默认使用 Claude Code
        """
        self.primary_agent = primary_agent or ClaudeCodeAgent()
        self.model_registry = registry

    def parse_message(self, text: str) -> Tuple[Optional[str], Optional[str], str]:
        """
        解析消息，提取目标类型和内容

        Returns:
            (target_type, target_id, content)
            - target_type: None=主Agent, "model"=子模型, "instance"=Claude实例
            - target_id: 模型别名或实例ID
            - content: 实际消息内容
        """
        text = text.strip()

        if not text.startswith('@'):
            return None, None, text

        # 先尝试有空格的情况: "@小d 你好"
        match_space = re.match(r'^@([^\s]+)\s+(.+)', text, re.DOTALL)
        if match_space:
            name = match_space.group(1)
            content = match_space.group(2).strip()
        else:
            # 无空格情况: "@小d你好" - 需要智能分割
            # 先提取 @ 后的全部内容
            full_name = text[1:]  # 去掉 @

            # 尝试匹配已知实例/别名
            # 从长到短尝试
            name = None
            content = ""
            for i in range(len(full_name), 0, -1):
                candidate = full_name[:i]
                if self.primary_agent.resolve_instance_id(candidate):
                    name = candidate
                    content = full_name[i:]
                    break
                # 也检查子模型
                if self.model_registry.get(f"@{candidate.lower()}"):
                    name = candidate
                    content = full_name[i:]
                    break

            # 如果没找到已知的，智能分割名字和内容
            if not name:
                # 名字模式：中文/英文/数字的组合，但通常较短（1-8字符）
                # 内容模式：中文句子通常以"你/我/他/是/有/在/的"等开头
                content_starters = r'[你我他她它们的是有在了吗呢啊呀吧呐哦嗯好请帮能可以怎么什么为什么]'

                # 尝试在内容起始词处分割
                for i in range(1, min(len(full_name), 10)):
                    if re.match(content_starters, full_name[i:]):
                        name = full_name[:i]
                        content = full_name[i:]
                        break

                # 如果没找到内容起始词，取1-4个字符作为名字
                if not name:
                    # 取连续的字母数字中文（但限制长度）
                    m = re.match(r'^([a-zA-Z0-9\u4e00-\u9fa5_]{1,6})(.*)', full_name)
                    if m:
                        candidate_name = m.group(1)
                        candidate_content = m.group(2)
                        # 如果剩余内容不为空且像句子，就用这个分割
                        if candidate_content:
                            name = candidate_name
                            content = candidate_content
                        else:
                            # 全是名字，没有内容
                            name = full_name
                            content = ""
                    else:
                        name = full_name
                        content = ""

        prefix = f"@{name.lower()}"

        # 检查是否是已知子模型 (@q, @d, @g 等)
        if self.model_registry.get(prefix):
            return "model", prefix, content

        # 检查是否是已知 Claude 实例
        if self.primary_agent.resolve_instance_id(name):
            return "instance", name, content

        # 未知的名称，可能是用户自定义别名，返回特殊类型让 gateway_main 处理
        return "user_alias", name, content

    def route(self, text: str, context: Dict[str, Any] = None,
              override_type: str = None, override_id: str = None, override_content: str = None) -> str:
        """
        路由消息到对应处理器

        Args:
            text: 原始消息
            context: 上下文（sender_id, history 等）
            override_type: 覆盖目标类型（由 gateway_main 处理用户别名后传入）
            override_id: 覆盖目标 ID
            override_content: 覆盖内容

        Returns:
            回复文本
        """
        if override_type:
            target_type = override_type
            target_id = override_id
            content = override_content
        else:
            target_type, target_id, content = self.parse_message(text)

        context = context or {}

        if not content and target_type not in ("instance", "user_alias"):
            return "请输入消息内容"

        # 子模型 API 路由
        if target_type == "model":
            model = self.model_registry.get(target_id)
            if model:
                if not model.is_available():
                    return f"[{model.name}] 模型不可用，请检查 API Key"

                # 构建消息
                history = context.get("history", {}).get(model.name, [])
                messages = history + [{"role": "user", "content": content}]

                return model.call(messages)
            return f"未知的模型: {target_id}"

        # Claude Code 实例路由
        if target_type == "instance":
            if not self.primary_agent.is_available():
                return "[错误] Claude Code 不可用"

            # 如果没有内容，可能是查看实例状态
            if not content:
                inst = self.primary_agent.get_instance(target_id)
                info = inst.get_info()
                name = info.get('display_name') or target_id
                return f"实例 @{name}\nID: {target_id}\n消息数: {info['message_count']}"

            return self.primary_agent.chat_to_instance(target_id, content)

        # 主 Agent 处理（默认实例）
        if not self.primary_agent.is_available():
            return "[错误] 主 Agent 不可用"

        return self.primary_agent.chat(content, context)

    def get_help(self) -> str:
        """获取帮助信息"""
        lines = [
            "WeChat Agent Gateway",
            "",
            "== Claude Code ==",
            "直接发 → 默认实例",
            "@<名称> 消息 → 指定实例",
            "",
            "实例命令:",
            "  /new <id> [prompt]",
            "  /rename <id> <名称>",
            "  /instances",
            "  /del <名称>",
            "",
            "== 子模型 ==",
        ]

        for info in self.model_registry.list_all():
            status = "✓" if info["available"] else "✗"
            aliases = " / ".join(info["aliases"])
            lines.append(f"  {status} {aliases}")

        lines.extend([
            "",
            "== 其他 ==",
            "  /help /status /clear",
        ])

        return "\n".join(lines)

    def get_status(self) -> str:
        """获取状态信息"""
        lines = ["Gateway 状态", ""]

        # 主 Agent
        agent_status = "✓" if self.primary_agent.is_available() else "✗"
        lines.append(f"Claude Code: {agent_status}")

        # Claude 实例
        instances = self.primary_agent.list_instances()
        if instances:
            lines.append("")
            lines.append(f"实例 ({len(instances)}):")
            for inst in instances:
                name = inst['display_name'] or inst['instance_id']
                id_hint = f" ({inst['instance_id']})" if inst['display_name'] else ""
                lines.append(f"  @{name}{id_hint} - {inst['message_count']} msgs")

        # 子模型
        lines.append("")
        lines.append("子模型:")
        for info in self.model_registry.list_all():
            status = "✓" if info["available"] else "✗"
            lines.append(f"  {status} {info['name']}")

        return "\n".join(lines)
