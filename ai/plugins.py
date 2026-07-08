import os
import sys
import json
import logging
import importlib.util
from pathlib import Path
from typing import Dict, Any, Optional, List
from ai.config import PluginConfig

logger = logging.getLogger(__name__)


class Plugin:
    def __init__(self, config: PluginConfig):
        self.config = config
        self.module = None
        self._loaded = False

    async def load(self):
        if self._loaded:
            return
        path = self.config.script_path
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"插件脚本不存在: {path}")
        try:
            spec = importlib.util.spec_from_file_location(
                f"plugin_{self.config.name}", path
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.module = mod
                self._loaded = True
                logger.info(f"插件已加载: {self.config.name}")
        except Exception as e:
            logger.error(f"插件加载失败 {self.config.name}: {e}")
            raise

    async def run(self, sandbox_root: str, **kwargs) -> str:
        if not self._loaded:
            await self.load()
        if hasattr(self.module, "run"):
            if hasattr(self.module.run, "__call__"):
                result = self.module.run(sandbox_root, self.config.config, **kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                return str(result)
        return f"插件 {self.config.name} 无 run() 函数"


class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, Plugin] = {}

    def add(self, config: PluginConfig):
        self.plugins[config.name] = Plugin(config)

    def remove(self, name: str):
        self.plugins.pop(name, None)

    def get(self, name: str) -> Optional[Plugin]:
        return self.plugins.get(name)

    def get_enabled(self) -> List[Plugin]:
        return [p for p in self.plugins.values() if p.config.enabled]

    def to_config_list(self) -> list:
        return [p.config.to_dict() for p in self.plugins.values()]

    def load_from_config(self, plugins_data: list):
        for pd in plugins_data:
            self.add(PluginConfig.from_dict(pd))
