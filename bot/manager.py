import asyncio
import logging
from typing import Optional, Callable, Dict, List

from bot.qq_bot import QQOfficialPlatform, BotConfig

logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self, sandbox_root: str = ""):
        self.sandbox_root = sandbox_root
        self._platforms: Dict[str, QQOfficialPlatform] = {}
        self._configs: Dict[str, BotConfig] = {}
        self._on_bot_log: Optional[Callable] = None
        self._on_message: Optional[Callable] = None
        self._event_bus = None

    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    def on_bot_log(self, callback: Callable):
        self._on_bot_log = callback

    def on_message(self, callback: Callable):
        self._on_message = callback

    def _make_bot_id(self, config: BotConfig) -> str:
        return config.name or config.app_id[:8]

    def configure_all(self, configs: List[dict]):
        for cfg_dict in configs:
            self.configure(cfg_dict)

    def configure(self, config_dict: dict, bot_id: str = ""):
        config = BotConfig.from_dict(config_dict)
        if not bot_id:
            bot_id = self._make_bot_id(config)
        self._configs[bot_id] = config

    def start_bot(self, bot_id: str) -> bool:
        if bot_id in self._platforms and self._platforms[bot_id] is not None:
            return True
        cfg = self._configs.get(bot_id)
        if not cfg:
            logger.warning("Bot %s not configured", bot_id)
            return False
        if not cfg.app_id or not (cfg.app_secret or cfg.bot_token):
            logger.warning("Bot %s: AppID or AppSecret missing", bot_id)
            return False

        platform = QQOfficialPlatform(cfg, self._event_bus)
        if self._on_message:
            platform.on_message(self._on_message)
        platform.on_event(self._handle_event)
        try:
            asyncio.run(platform.start())
        except Exception as e:
            logger.error("Bot %s start failed: %s", bot_id, e)
            return False
        self._platforms[bot_id] = platform
        return True

    def stop_bot(self, bot_id: str):
        platform = self._platforms.pop(bot_id, None)
        if platform:
            try:
                asyncio.run(platform.stop())
            except Exception as e:
                logger.error("Bot %s stop error: %s", bot_id, e)

    def start_all(self):
        for bot_id in list(self._platforms.keys()):
            self.start_bot(bot_id)

    def stop_all(self):
        for bot_id in list(self._platforms.keys()):
            self.stop_bot(bot_id)

    def get_config(self, bot_id: str) -> Optional[BotConfig]:
        return self._configs.get(bot_id)

    def _handle_event(self, event_type: str, data: dict):
        log_msg = "[Bot Event] %s" % event_type
        if self._on_bot_log:
            self._on_bot_log(log_msg)
        logger.debug(log_msg)

    def is_running(self, bot_id: str = "") -> bool:
        if bot_id:
            p = self._platforms.get(bot_id)
            return p is not None and p.is_running()
        return any(p.is_running() for p in self._platforms.values() if p)

    def get_platform(self, bot_id: str) -> Optional[QQOfficialPlatform]:
        return self._platforms.get(bot_id)

    def get_status(self) -> dict:
        status = {}
        for bot_id, platform in self._platforms.items():
            if platform:
                status[bot_id] = {
                    "running": platform.is_running(),
                    "name": platform.config.name or bot_id,
                    "app_id": platform.config.app_id[:8] + "..." if platform.config.app_id else "",
                }
            else:
                status[bot_id] = {"running": False, "name": bot_id, "app_id": ""}
        return status

    def send_image(self, channel_id: str, image_path: str,
                    content: str = "", msg_id: str = "",
                    event_type: str = "", bot_id: str = "") -> bool:
        return self.send_file(channel_id, image_path, content, msg_id, event_type, bot_id=bot_id)

    def send_file(self, channel_id: str, file_path: str,
                  content: str = "", msg_id: str = "",
                  event_type: str = "", bot_id: str = "") -> bool:
        platform = self._platforms.get(bot_id)
        if not platform or not platform.is_running():
            logger.warning("Bot %s not running, cannot send file", bot_id)
            return False
        loop = platform._loop
        if not loop or loop.is_closed():
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                platform.send_file(channel_id, file_path, content, msg_id, event_type), loop
            )
            return future.result(timeout=30)
        except Exception as e:
            logger.error("Bot %s send file error: %s", bot_id, e)
            return False

    def send_message(self, channel_id: str, content: str,
                     msg_id: str = "", event_type: str = "",
                     bot_id: str = "") -> bool:
        platform = self._platforms.get(bot_id)
        if not platform or not platform.is_running():
            logger.warning("Bot %s not running, cannot send message", bot_id)
            return False
        loop = platform._loop
        if not loop or loop.is_closed():
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                platform.send_message(channel_id, content, msg_id, event_type), loop
            )
            return future.result(timeout=10)
        except asyncio.TimeoutError:
            logger.error("Bot %s send message timeout", bot_id)
            return False
        except Exception as e:
            logger.error("Bot %s send message error: %s", bot_id, e)
            return False

    def cleanup(self):
        self.stop_all()
