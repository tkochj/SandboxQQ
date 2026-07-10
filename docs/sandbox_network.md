# 沙盒网络隔离

沙盒默认只允许访问白名单中的域名。所有 26 个工具的网络请求都经过代理沙盒，未在 `allowed_hosts` 中的域名会被拦截。

## 添加允许的域名

编辑 `sandbox_config.json` 的 `allowed_hosts` 数组：

```json
"allowed_hosts": [
    "api.openai.com",
    "api.deepseek.com",
    "api.duckduckgo.com",
    "你的API域名.com"
]
```

## 需要放行的常见域名

| 用途 | 域名 |
|------|------|
| QQ API | `api.sgroup.qq.com` |
| OpenAI | `api.openai.com` |
| DeepSeek | `api.deepseek.com` |
| 智谱 | `open.bigmodel.cn` |
| 阿里通义 | `dashscope.aliyuncs.com` |
| 网络搜索 | `api.duckduckgo.com` |
| QQ 图片 CDN | `multimedia.nt.qq.com.cn` |
| 其他 AI API | 你的 API 供应商域名 |

## 注意

- `sandbox_config.json` 含本地路径，在 `.gitignore` 中，不会被提交
- 修改后需重启沙盒生效
