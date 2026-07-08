import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class SkillConfig:
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    enabled: bool = True

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "system_prompt": self.system_prompt, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("name", ""), d.get("description", ""),
                   d.get("system_prompt", ""), d.get("enabled", True))


@dataclass
class PluginConfig:
    name: str = ""
    description: str = ""
    script_path: str = ""
    enabled: bool = True
    config: dict = field(default_factory=dict)

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "script_path": self.script_path, "enabled": self.enabled,
                "config": self.config}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("name", ""), d.get("description", ""),
                   d.get("script_path", ""), d.get("enabled", True),
                   d.get("config", {}))


@dataclass
class SubAgentConfig:
    name: str = ""
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    enable_tools: bool = True
    enabled: bool = True

    def to_dict(self):
        return {"name": self.name, "model": self.model,
                "system_prompt": self.system_prompt,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "enable_tools": self.enable_tools, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("name", ""), d.get("model", ""),
                   d.get("system_prompt", ""), d.get("temperature", 0.7),
                   d.get("max_tokens", 2048), d.get("enable_tools", True),
                   d.get("enabled", True))


@dataclass
class ToolPermissions:
    execute_python: bool = True
    read_file: bool = True
    write_file: bool = True
    list_files: bool = True
    run_shell: bool = False

    def to_dict(self):
        return {"execute_python": self.execute_python, "read_file": self.read_file,
                "write_file": self.write_file, "list_files": self.list_files,
                "run_shell": self.run_shell}

    @classmethod
    def from_dict(cls, d):
        p = cls()
        for k in ("execute_python", "read_file", "write_file", "list_files", "run_shell"):
            if k in d:
                setattr(p, k, d[k])
        return p


@dataclass
class ProviderConfig:
    name: str = "default"
    provider: str = "openai"
    api_key: str = ""
    api_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = ""
    enable_tools: bool = True
    max_tool_rounds: int = 10

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})

    def display_name(self) -> str:
        return f"{self.name} ({self.model})"


@dataclass
class AIConfig:
    provider: str = "openai"
    api_key: str = ""
    api_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = (
        "你是一个安全的 AI 助手，运行在沙盒环境中。"
        "你可以使用工具在沙盒内执行 Python 代码、读写文件、运行命令来帮助用户处理任务。"
        "所有操作都被限制在沙盒目录内，不会影响外部系统。"
    )
    enable_tools: bool = True
    max_tool_rounds: int = 10
    enabled: bool = True

    # ── 上下文管理 ──
    context_mode: str = "truncation"
    context_window: int = 32000

    # ── 思考/推理 ──
    enable_thinking: bool = False
    thinking_model: str = ""
    thinking_budget: int = 2048

    # ── 网页搜索 ──
    enable_web_search: bool = False
    search_provider: str = "duckduckgo"

    # ── 识图 (Vision) ──
    vision_model: str = ""
    vision_api_url: str = ""
    vision_api_key: str = ""

    # ── 图片生成 ──
    image_gen_model: str = ""
    image_gen_api_url: str = ""
    image_gen_api_key: str = ""

    # ── 视频生成 ──
    video_gen_model: str = ""
    video_gen_api_url: str = ""
    video_gen_api_key: str = ""

    # ── 沙盒权限 ──
    tool_permissions: ToolPermissions = field(default_factory=ToolPermissions)

    # ── Skills / 插件 / 子Agent ──
    skills: List[SkillConfig] = field(default_factory=list)
    plugins: List[PluginConfig] = field(default_factory=list)
    sub_agents: List[SubAgentConfig] = field(default_factory=list)

    # ── 多供应商 ──
    providers: List[ProviderConfig] = field(default_factory=list)
    active_provider: str = "default"

    def get_active_provider_config(self) -> "ProviderConfig":
        if self.active_provider and self.active_provider != "default":
            for p in self.providers:
                if p.name == self.active_provider and p.api_key:
                    return p
        return ProviderConfig(
            name="default",
            provider=self.provider,
            api_key=self.api_key,
            api_url=self.api_url,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system_prompt=self.system_prompt,
            enable_tools=self.enable_tools,
            max_tool_rounds=self.max_tool_rounds,
        )

    def to_dict(self):
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "api_url": self.api_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "system_prompt": self.system_prompt,
            "enable_tools": self.enable_tools,
            "max_tool_rounds": self.max_tool_rounds,
            "enabled": self.enabled,
            "context_mode": self.context_mode,
            "context_window": self.context_window,
            "enable_thinking": self.enable_thinking,
            "thinking_model": self.thinking_model,
            "thinking_budget": self.thinking_budget,
            "enable_web_search": self.enable_web_search,
            "search_provider": self.search_provider,
            "vision_model": self.vision_model,
            "vision_api_url": self.vision_api_url,
            "vision_api_key": self.vision_api_key,
            "image_gen_model": self.image_gen_model,
            "image_gen_api_url": self.image_gen_api_url,
            "image_gen_api_key": self.image_gen_api_key,
            "video_gen_model": self.video_gen_model,
            "video_gen_api_url": self.video_gen_api_url,
            "video_gen_api_key": self.video_gen_api_key,
            "tool_permissions": self.tool_permissions.to_dict(),
            "skills": [s.to_dict() for s in self.skills],
            "plugins": [p.to_dict() for p in self.plugins],
            "sub_agents": [s.to_dict() for s in self.sub_agents],
            "providers": [p.to_dict() for p in self.providers],
            "active_provider": self.active_provider,
        }

    @classmethod
    def from_dict(cls, data: dict):
        cfg = cls()
        for key, value in data.items():
            if key == "tool_permissions" and isinstance(value, dict):
                cfg.tool_permissions = ToolPermissions.from_dict(value)
            elif key == "skills" and isinstance(value, list):
                cfg.skills = [SkillConfig.from_dict(s) for s in value]
            elif key == "plugins" and isinstance(value, list):
                cfg.plugins = [PluginConfig.from_dict(s) for s in value]
            elif key == "sub_agents" and isinstance(value, list):
                cfg.sub_agents = [SubAgentConfig.from_dict(s) for s in value]
            elif key == "providers" and isinstance(value, list):
                cfg.providers = [ProviderConfig.from_dict(s) for s in value]
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    def save(self, path: str):
        d = self.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str):
        if not path or not os.path.exists(path):
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
