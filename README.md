# SandboxQQ

基于 PyQt6 的 Windows 沙盒化 QQ 机器人运行环境。集成 AI 对话、多模型供应商、文件生成与发送、对话记忆、插件系统等功能。

## 截图预览

(项目运行截图)

## 功能特性

### 🤖 QQ 机器人
- QQ 官方机器人协议（AppID + AppSecret 鉴权）
- OneBot 协议
- 多机器人配置管理（添加/保存/加载/切换）
- 消息接收、自动回复、文件发送

### 🧠 AI 引擎
- 多模型供应商：OpenAI / DeepSeek / Anthropic / Google / 自定义
- AI 对话选项卡 + QQ 机器人自动回复
- 一键切换供应商
- 深度思考模式（先分析再回答）
- 上下文管理（截断/压缩/完整）

### 🛠️ 22 个沙盒工具
| 工具 | 说明 |
|------|------|
| execute_python | 执行 Python 代码 |
| read_file / write_file | 读写文件 |
| list_files | 列出目录 |
| run_shell | Shell 命令 |
| generate_image | AI 生图 |
| analyze_image | 图片识别分析 |
| generate_video | AI 生成视频 |
| web_download | 下载文件到沙盒 |
| compress_files | 压缩为 ZIP |
| search_files | 搜索文件 |
| system_info | 系统信息 |
| web_search | 网络搜索 |
| pdf_extract | 提取 PDF 文本 |
| ocr_image | 图片文字识别 |
| translate | 多语言翻译 |
| hash_text | 哈希/Base64 |
| datetime_tool | 日期时间 |
| convert_data | CSV/JSON/YAML 互转 |
| qrcode | 生成二维码 |
| create_chart | 创建图表(折线/柱状/饼图) |
| send_file | 发送文件给用户 |

### 🎨 表情包管理器
- AI 回复中检测情绪标记自动配图
- 支持 `&&happy&&` `[sad]` `(angry)` 等格式
- 12 种情绪默认表情包
- 自定义图库管理

### 🔌 插件系统
- `plugins/` 目录放 `.py` 文件自动加载
- 支持消息拦截、工具注册、独立设置面板
- GUI 管理：新建/加载/设置/打开目录
- 示例插件 + 表情管理器内置

### 💾 对话记忆
- 跨会话持久化存储
- 按用户会话隔离
- 重启不丢失

### 🛡️ 沙盒隔离
- 文件系统：限制写入范围，保护系统目录
- 网络：默认放行，可配置白名单
- 进程：Windows Job Object 管理

## 快速开始

### 环境要求
- Windows 10/11
- Python 3.12+
- pip

### 安装
```bash
# 克隆项目
git clone https://github.com/tkochj/SandboxQQ.git
cd SandboxQQ

# 安装依赖
pip install -r requirements.txt
```

### 配置 QQ 机器人
1. 前往 [QQ 开放平台](https://q.qq.com) 创建机器人
2. 获取 AppID 和 AppSecret
3. 启动程序后，在 QQBot 选项卡填写并连接

### 运行
```bash
python main.py
```
或直接双击 `start.bat`。

## 推荐 AI 模型配置

| 用途 | API 地址 | 模型 |
|------|---------|------|
| 主模型 | `https://api.deepseek.com` | `deepseek-chat` |
| 生图 | `https://apihub.agnes-ai.com/v1` | `agnes-image-2.1-flash` |
| 识图 | `https://open.bigmodel.cn/api/paas/v4` | `GLM-4.6V-Flash` |

## 项目结构

```
SandboxQQ/
├── main.py                  # 入口
├── event_bus.py             # 事件总线
├── message.py               # 消息事件模型
├── start.bat                # 一键启动
│
├── bot/                     # QQ 机器人
│   ├── base.py              # Platform 抽象基类
│   ├── qq_bot.py            # QQ 官方平台 (botpy)
│   └── manager.py           # Bot 管理器
│
├── ai/                      # AI 模块
│   ├── config.py            # 配置数据类
│   ├── provider.py          # 供应商管理器
│   ├── tools.py             # 22 个沙盒工具
│   ├── skills.py            # 技能系统
│   ├── memory.py            # 对话记忆
│   ├── agent.py             # AI 代理 (GUI 对话用)
│   ├── chat.py              # 聊天会话
│   ├── sub_agent.py         # 子 Agent
│   └── plugins.py           # 插件管理器
│
├── pipeline/                # 消息处理管道
│   ├── stage.py             # Stage 基类
│   ├── scheduler.py         # 洋葱模型调度器
│   └── stages/              # 各处理阶段
│       ├── auth_stage.py    # 用户鉴权
│       ├── sandbox_stage.py # 沙盒检查
│       ├── ai_stage.py      # AI 响应
│       ├── respond_stage.py # 回复发送
│       └── plugin_stage.py  # 插件处理
│
├── sandbox/                 # 沙盒隔离
│   ├── core.py              # 沙盒管理器
│   ├── filesystem.py        # 文件系统隔离
│   ├── network.py           # 网络隔离
│   └── process.py           # 进程隔离
│
├── gui/                     # PyQt6 界面
│   └── main_window.py       # 主窗口
│
├── plugins/                 # 插件目录
│   ├── example_plugin.py    # 示例插件
│   └── meme_manager.py      # 表情管理器
│
└── utils/                   # 工具
    └── win32_utils.py       # Windows 实用工具
```

## 插件开发

在 `plugins/` 目录下创建 `.py` 文件，包含 `class Plugin:` 即可：

```python
class Plugin:
    name = "我的插件"
    description = "插件描述"
    version = "1.0"

    async def on_message(self, content, sender, channel):
        # 处理消息，返回字符串作为回复
        return None

    async def get_tool_definitions(self):
        # 注册 AI 工具
        return []

    def settings_widget(self):
        # 返回 PyQt6 QWidget 作为设置面板
        return None
```

## 协议

MIT License
