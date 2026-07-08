# SandboxQQ

Windows 上的沙盒化 QQ 机器人。在隔离环境中运行 AI 代码，保护你的系统安全。

## 它能做什么？

- **QQ 机器人** — 连接 QQ，自动回复消息
- **AI 对话** — 接入 DeepSeek / OpenAI 等模型
- **安全执行代码** — AI 生成的 Python 代码在沙盒中运行，限制权限
- **生成图片/视频** — 调用外部 API 生成，自动发到 QQ
- **分析图片** — 用户发图，AI 自动识别内容
- **22 个工具** — 文件操作、网络搜索、翻译、PDF提取、数据转换等
- **插件系统** — 自己写插件扩展功能

## 快速开始

### 安装
```bash
pip install -r requirements.txt
```

### 运行
```bash
python main.py
```
或双击 `start.bat`。

### 配置 QQ 机器人
1. 去 [QQ 开放平台](https://q.qq.com) 创建机器人
2. 拿到 AppID 和 AppSecret
3. 打开程序 → QQBot 选项卡 → 填写 → 连接

### 配置 AI
程序默认识别项目根目录的 `ai_config.json`，也可以在界面上配置。

推荐配置：

| 用途 | 服务商 | API 地址 |
|------|--------|---------|
| 主模型 | DeepSeek | `https://api.deepseek.com` |
| 生成图片 | Agnes | `https://apihub.agnes-ai.com/v1` |
| 识别图片 | 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` |

## 安全机制

SandboxQQ 的核心功能是**安全地执行 AI 生成的代码**，保护你的电脑。

| 机制 | 说明 |
|------|------|
| 进程隔离 | Job Object 限制子进程的内存和数量 |
| 受限令牌 | 子进程使用低权限 Windows 令牌运行 |
| 网络代理 | 子进程的网络请求经过本地代理，按域名白名单放行 |
| 文件路径检查 | 所有文件操作限制在沙盒目录内 |
| 用户鉴权 | QQ 机器人可设置白名单，仅允许指定用户使用 |

## 项目结构

```
SandboxQQ/
├── main.py              # 入口
├── bot/                 # QQ 机器人
│   ├── qq_bot.py       # QQ 官方协议 (使用腾讯官方 botpy)
│   └── manager.py      # 机器人管理器
├── ai/                  # AI 模块
│   ├── tools.py        # 22 个沙盒工具
│   ├── provider.py     # AI 供应商管理
│   ├── memory.py       # 对话记忆（重启不丢失）
│   └── plugins.py      # 插件加载器
├── pipeline/            # 消息处理管道
│   └── stages/         # 各处理阶段
├── sandbox/             # 沙盒隔离
│   ├── core.py         # 沙盒管理器
│   ├── process.py      # 进程隔离
│   ├── filesystem.py   # 文件系统隔离
│   ├── network.py      # 防火墙规则
│   └── proxy.py        # 本地网络代理
├── gui/                 # 图形界面 (PyQt6)
├── plugins/             # 插件目录
│   ├── meme_manager.py # 表情包管理器
│   └── example_plugin.py
└── event_bus.py        # 事件总线
```

## 插件开发

在 `plugins/` 目录下创建 `.py` 文件，按以下模板写：

```python
class Plugin:
    name = "我的插件"
    description = "描述"
    version = "1.0"

    async def on_message(self, content, sender, channel):
        # 收到消息时调用，返回字符串则作为回复
        return None

    async def get_tool_definitions(self):
        # 注册 AI 可调用的工具
        return []

    def settings_widget(self):
        # 返回 PyQt6 设置面板
        return None
```

## 致谢

- [botpy](https://github.com/tencent-connect/botpy) — 腾讯官方 QQ 机器人 Python SDK
- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 参考了事件总线和管道设计
