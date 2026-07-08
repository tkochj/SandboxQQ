# SandboxQQ

基于 PyQt6 的 Windows 沙盒化 QQ 机器人运行环境。集成 AI 对话、多模型供应商、文件生成与发送、对话记忆等功能。

## 功能

- 🛡️ **沙盒隔离**：文件系统 + 网络 + 进程三重隔离
- 🤖 **QQ 机器人双协议**：QQ 官方机器人 + OneBot
- 🧠 **多模型 AI 供应商**：OpenAI / DeepSeek / Anthropic / 自定义
- 🎨 **AI 生图 / 生视频**：调用外部 API 生成并自动发送到 QQ
- 👁️ **自动识图**：用户发图自动调用 Vision 模型分析
- 💾 **对话记忆**：跨会话持久化，重启不丢失
- 🔧 **12 个沙盒工具**：Python 执行、文件读写、Shell、图片/视频生成、压缩、搜索等
- 📊 **可视化仪表盘**：进程监控、文件浏览、实时日志

## 快速开始

1. 安装 Python 3.12+
```
pip install -r requirements.txt
```

2. 配置 QQ 机器人
   - 前往 [QQ 开放平台](https://q.qq.com) 创建机器人
   - 获取 AppID 和 AppSecret
   - 在程序 Bot 配置页面填写

3. 运行
```
python main.py
```

或直接双击 `start.bat`。

## 配置 AI 供应商

在"AI 配置"选项卡中可添加多个模型供应商（DeepSeek、OpenAI、GLM Vision 等），对话时可在 AI 对话选项卡中切换。

### 推荐配置

| 用途 | API 地址 | 模型 |
|------|---------|------|
| 主模型 | `https://api.deepseek.com` | `deepseek-chat` |
| 生图 | `https://apihub.agnes-ai.com/v1` | `agnes-image-2.1-flash` |
| 识图 | `https://open.bigmodel.cn/api/paas/v4` | `GLM-4.6V-Flash` |

## 项目结构

```
SandboxQQ/
├── main.py                 # 入口
├── bot/                    # QQ机器人
│   ├── base.py            # Platform抽象基类
│   ├── qq_bot.py          # QQ官方平台(botpy)
│   └── manager.py         # Bot管理器
├── ai/                     # AI模块
│   ├── config.py          # 配置数据类
│   ├── provider.py        # 供应商管理器
│   ├── tools.py           # 沙盒工具(12个)
│   ├── skills.py          # 技能(7个)
│   ├── memory.py          # 对话记忆
│   └── agent.py           # AI代理
├── pipeline/               # 消息管道
│   ├── stage.py           # Stage基类
│   ├── scheduler.py       # 洋葱模型调度器
│   └── stages/            # 各处理阶段
├── sandbox/                # 沙盒
├── gui/                    # PyQt6界面
└── event_bus.py           # 事件总线
```
