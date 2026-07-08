import json
import os
import logging
from pathlib import Path
from typing import List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
USER_CONFIG_FILE = str(APP_DIR / "user_config.json")


@dataclass
class UserConfig:
    auth_enabled: bool = False
    authorized_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "auth_enabled": self.auth_enabled,
            "authorized_ids": self.authorized_ids,
        }

    @classmethod
    def from_dict(cls, data: dict):
        cfg = cls()
        cfg.auth_enabled = data.get("auth_enabled", False)
        cfg.authorized_ids = data.get("authorized_ids", [])
        return cfg

    def save(self, path: str = USER_CONFIG_FILE):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str = USER_CONFIG_FILE):
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load user config: {e}")
            return cls()
