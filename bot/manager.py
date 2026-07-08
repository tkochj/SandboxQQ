import asyncio
import logging
from typing import Optional, Callable

from bot.qq_bot import QQOfficialPlatform, BotConfig

logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self, sandbox_root: str = ""):
        self.sandbox_root = sandbox_root
        self.config = BotConfig()
        self._platform: Optional[QQOfficialPlatform] = None
        self._running = False
        self._on_bot_log: Optional[Callable] = None
        self._on_message: Optional[Callable] = None
        self._event_bus = None

    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    def on_bot_log(self, callback: Callable):
        self._on_bot_log = callback

    def on_message(self, callback: Callable):
        self._on_message = callback

    def configure(self, config_dict: dict):
        old_enabled = self.config.enabled
        self.config = BotConfig.from_dict(config_dict)
        if self.sandbox_root:
            self.config.sandbox_root = self.sandbox_root
        if self._running and old_enabled != self.config.enabled:
            if self.config.enabled:
                self.start_bot()
            else:
                self.stop_bot()

    def start_bot(self):
        if self._running:
            return
        if not self.config.enabled:
            logger.warning("Bot is not enabled in configuration")
            return
        if not self.config.app_id or not (self.config.app_secret or self.config.bot_token):
            logger.warning("Bot AppID or AppSecret not configured")
            return

        self._platform = QQOfficialPlatform(self.config, self._event_bus)

        if self._on_message:
            self._platform.on_message(self._on_message)

        self._platform.on_event(self._handle_event)
        asyncio.run(self._platform.start())
        self._running = True

    def stop_bot(self):
        if self._platform:
            asyncio.run(self._platform.stop())
            self._platform = None
        self._running = False

    def _handle_event(self, event_type: str, data: dict):
        log_msg = f"[Bot Event] {event_type}"
        if self._on_bot_log:
            self._on_bot_log(log_msg)
        logger.debug(log_msg)

    def is_running(self) -> bool:
        return self._running and self._platform is not None and self._platform.is_running()

    def get_status(self) -> dict:
        return {
            "running": self.is_running(),
            "enabled": self.config.enabled,
            "protocol": self.config.protocol.value,
            "app_id": self.config.app_id[:8] + "..." if self.config.app_id else "",
            "ws_url": self.config.ws_url,
        }

    def send_file(self, channel_id: str, file_path: str,
                  content: str = "", msg_id: str = "",
                  event_type: str = "") -> bool:
        if not self._platform or not self._running:
            return False
        loop = self._platform._loop
        if not loop or loop.is_closed():
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._platform.send_file(channel_id, file_path, content, msg_id, event_type), loop
            )
            return future.result(timeout=30)
        except Exception as e:
            logger.error(f"Send file error: {e}")
            return False

    def send_message(self, channel_id: str, content: str,
                     msg_id: str = "", event_type: str = "") -> bool:
        if not self._platform or not self._running:
            logger.warning(f"Bot not running, cannot send to {channel_id}")
            return False
        loop = self._platform._loop
        if not loop or loop.is_closed():
            logger.error(f"Bot event loop not available (loop={loop})")
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._platform.send_message(channel_id, content, msg_id, event_type), loop
            )
            return future.result(timeout=10)
        except asyncio.TimeoutError:
            logger.error(f"Send message timeout (10s) to {channel_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to send message to {channel_id}: {e}")
            return False

    def cleanup(self):
        self.stop_bot()
