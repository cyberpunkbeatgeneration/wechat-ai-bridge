# WeChat AI Bridge

微信 AI 网关 — 在微信里使用 Claude Code + 多模型路由。

**不只是桥接，是一个有记忆的多模型助手系统。**

## 特性

- **Claude Code 免费用** — Max 订阅用户不花 API 钱
- **多模型 @ 路由** — `@d` DeepSeek / `@q` 千问 / `@g` Gemini / `@k` Kimi...
- **自然语言创建助手** — "创建一个叫小s的deepseek助手"
- **智能记忆系统** — 最近 10 轮 + 自动总结，不会聊久了变笨
- **助手间对话** — Claude 可以协调多个助手对话
- **语音转文字** — 直接发语音，自动转文字处理

## 架构

```
微信用户
    ↓
┌─────────────────────────────────────────┐
│          WeChat AI Bridge               │
├─────────────────────────────────────────┤
│              消息路由层                  │
│  ┌─────────────────────────────────┐    │
│  │  @d @q @g ...  →  子模型直接调用 │    │
│  │  普通消息      →  Claude Code    │    │
│  └─────────────────────────────────┘    │
└────────┬────────────────────┬───────────┘
         │                    │
    ┌────┴────┐          ┌────┴────┐
    │ 子模型   │          │ Claude  │
    │ (API)   │          │  Code   │
    └────┬────┘          └────┬────┘
         │                    │
    DeepSeek / 千问 / Gemini / Kimi / GPT...
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 2. 配置 API Keys

```bash
cp .env.example .env
# 编辑 .env 填入各模型的 API Key
```

### 3. 登录微信

```bash
npm run claude:setup
# 扫码登录
```

### 4. 选择运行模式

#### MCP 模式（推荐）

```bash
# 需要先安装 tmux
brew install tmux

# 启动
./start_mcp.sh

# 连接到会话查看日志
tmux attach -t wechat-ai-bridge
```

#### Gateway 模式

```bash
# 启动
./start_gateway.sh start

# 查看日志
./start_gateway.sh log

# 停止
./start_gateway.sh stop
```

## 使用方法

### 基本对话

| 发送 | 回复者 | 图标 |
|------|--------|------|
| `你好` | Claude | 👾 |
| `@d 你好` | DeepSeek | 🐳 |
| `@q 你好` | 千问 | 🦄 |
| `@g 你好` | Gemini | 💠 |
| 发语音 | Claude（自动转文字）| 👾 |

### 内置模型

| 别名 | 模型 | 图标 | 需要的 API Key |
|------|------|------|---------------|
| `@d` / `@deepseek` | DeepSeek | 🐳 | DOUBAO_API_KEY + DEEPSEEK_BOT_ID |
| `@q` / `@qwen` | 千问 | 🦄 | QWEN_API_KEY |
| `@g` / `@gemini` | Gemini | 💠 | GOOGLE_API_KEY |
| `@db` / `@doubao` | 豆包 | 🌱 | DOUBAO_API_KEY + DOUBAO_BOT_ID |
| `@k` / `@kimi` | Kimi | 🌑 | MOONSHOT_API_KEY |
| `@m` / `@minimax` | MiniMax | 🐚 | MINIMAX_API_KEY + MINIMAX_GROUP_ID |
| `@o` / `@gpt` | GPT | 🍬 | OPENAI_API_KEY |
| `@api` / `@claude_api` | Claude API | 🍥 | ANTHROPIC_API_KEY |

### 创建自定义助手

```
创建一个叫巴巴的deepseek助手
```

然后就可以：
```
@巴巴 你好
```

回复会显示助手标识：`🐳巴巴`

### 管理助手

```
有哪些助手          # 查看所有助手
删除巴巴这个助手     # 删除助手
```

### 智能记忆

每个助手有独立的对话历史：
- **最近对话**：保留最近 10 轮（20 条消息）
- **自动总结**：超过 10 轮时自动总结旧对话
- **长期记忆**：最多保留 5 个总结

可在 `gateway/mcp_server.py` 的 `SessionStore` 类中调整：
```python
MAX_RECENT_ROUNDS = 10      # 保留最近 N 轮对话
MAX_COMPACTS = 5            # 最多保留 N 个总结
```

## MCP 工具

| 工具 | 功能 |
|------|------|
| `wechat_reply` | 回复微信消息 |
| `call_model` | 调用子模型并发送到微信 |
| `create_assistant` | 创建自定义助手 |
| `delete_assistant` | 删除助手 |
| `list_assistants` | 列出所有助手 |
| `get_assistant_history` | 获取助手对话历史 |

## 配置

### .env

```bash
# DeepSeek（通过豆包 Ark 调用）
DOUBAO_API_KEY=xxx
DEEPSEEK_BOT_ID=xxx

# 千问
QWEN_API_KEY=sk-xxx

# Gemini
GOOGLE_API_KEY=AIza-xxx

# 豆包
DOUBAO_BOT_ID=xxx

# Kimi
MOONSHOT_API_KEY=sk-xxx

# MiniMax
MINIMAX_API_KEY=xxx
MINIMAX_GROUP_ID=xxx

# GPT
OPENAI_API_KEY=sk-xxx

# Claude API（可选，作为子模型）
ANTHROPIC_API_KEY=sk-xxx
```

## 文件结构

```
wechat-ai-bridge/
├── mcp_main.py          # MCP 模式入口
├── gateway_main.py      # Gateway 模式入口
├── start_mcp.sh         # MCP 启动脚本
├── start_gateway.sh     # Gateway 启动脚本
├── .mcp.json            # MCP 配置
├── gateway/
│   ├── mcp_server.py    # MCP server + 记忆系统
│   └── models/          # 子模型 API 封装
└── wechat_agent/        # 微信 API 封装
```

## 自定义

### 修改 Emoji

默认 emoji 在 `mcp_main.py` 的 `MODEL_ICONS`，可自行修改：

```python
MODEL_ICONS = {
    "deepseek": "🐳",
    "qwen": "🦄",
    "gemini": "💠",
    # ...
}
```

### 添加新模型

在 `gateway/models/registry.py` 中添加新的模型类，参考现有模型实现。

## 致谢

微信 API 封装参考了 [wechat-agent-channel](https://github.com/anthropics/wechat-agent-channel)

## License

MIT
