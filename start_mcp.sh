#!/bin/bash
# WeChat AI Bridge - MCP 模式启动脚本
# 使用 tmux 保持会话，关闭终端也不会中断

SESSION_NAME="wechat-ai-bridge"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 检查 tmux 是否安装
if ! command -v tmux &> /dev/null; then
    echo "tmux 未安装，请先安装："
    echo "  brew install tmux"
    exit 1
fi

# 检查会话是否已存在
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "会话 '$SESSION_NAME' 已在运行"
    echo ""
    echo "操作选项："
    echo "  1. 连接到会话: tmux attach -t $SESSION_NAME"
    echo "  2. 停止会话:   tmux kill-session -t $SESSION_NAME"
    echo ""
    read -p "是否连接到现有会话? (y/n) " choice
    if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
        tmux attach -t "$SESSION_NAME"
    fi
    exit 0
fi

# 创建新的 tmux 会话并启动
echo "启动 WeChat AI Bridge (MCP 模式)..."
tmux new-session -d -s "$SESSION_NAME" -c "$SCRIPT_DIR"
# --dangerously-skip-permissions: 自动批准所有工具调用（包括 MCP 工具）
tmux send-keys -t "$SESSION_NAME" "claude --dangerously-load-development-channels server:wechat --mcp-config .mcp.json --dangerously-skip-permissions" Enter

echo ""
echo "已在后台启动！"
echo ""
echo "常用命令："
echo "  连接会话: tmux attach -t $SESSION_NAME"
echo "  脱离会话: 在会话中按 Ctrl+B 然后按 D"
echo "  停止服务: tmux kill-session -t $SESSION_NAME"
echo ""
echo "提示: 关闭终端不会中断服务"
