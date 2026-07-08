import os
import sys
import logging
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"


class PluginBase:
    name: str = ""
    description: str = ""
    version: str = "1.0"

    def on_load(self):
        pass

    async def on_message(self, content: str, sender: dict, channel: dict) -> Optional[str]:
        return None

    async def on_tool_call(self, tool_name: str, args: dict) -> Optional[str]:
        return None

    async def get_tool_definitions(self) -> list:
        return []

    async def get_skill_prompts(self) -> list:
        return []


class PluginManager:
    def __init__(self):
        self._plugins: Dict[str, PluginBase] = {}
        self._loaded = False

    def load_all(self):
        if self._loaded:
            return
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        for f in sorted(PLUGIN_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            self._load_plugin(f)
        self._loaded = True
        logger.info(f"插件系统就绪: {len(self._plugins)} 个插件")

    def _load_plugin(self, path: Path):
        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{path.stem}", path)
            if not spec or not spec.loader:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "Plugin"):
                logger.warning(f"插件 {path.name} 缺少 Plugin 类")
                return
            instance = mod.Plugin()
            if hasattr(instance, "on_load"):
                instance.on_load()
            self._plugins[path.stem] = instance
            desc = getattr(instance, "description", "")
            logger.info(f"加载插件: {getattr(instance, 'name', path.stem)} - {desc}")
        except Exception as e:
            logger.error(f"插件加载失败 {path.name}: {e}")

    def get_all(self) -> List[PluginBase]:
        return list(self._plugins.values())

    async def get_tool_definitions(self) -> list:
        tools = []
        for p in self._plugins.values():
            if hasattr(p, "get_tool_definitions"):
                try:
                    if inspect.iscoroutinefunction(p.get_tool_definitions):
                        result = await p.get_tool_definitions()
                    else:
                        result = p.get_tool_definitions()
                    if result:
                        tools.extend(result)
                except Exception as e:
                    logger.warning(f"插件工具加载失败: {e}")
        return tools

    async def on_message(self, content: str, sender: dict, channel: dict) -> Optional[str]:
        for p in self._plugins.values():
            if hasattr(p, "on_message"):
                try:
                    if inspect.iscoroutinefunction(p.on_message):
                        result = await p.on_message(content, sender, channel)
                    else:
                        result = p.on_message(content, sender, channel)
                    if result:
                        return result
                except Exception as e:
                    logger.warning(f"插件 on_message 错误: {e}")
        return None



