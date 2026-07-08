import logging
from typing import Optional

from pipeline.stage import Stage
from ai.plugins import PluginManager

logger = logging.getLogger(__name__)


class PluginStage(Stage):
    name = "plugin"

    def __init__(self, plugin_manager: Optional[PluginManager] = None):
        self._pm = plugin_manager or PluginManager()
        self._pm.load_all()

    async def process(self, event):
        yield
        if event.is_stopped:
            return
        sender = {"id": event.sender_id, "name": event.sender_name}
        channel = {"id": event.channel_id, "platform": event.platform_name}
        try:
            reply = await self._pm.on_message(event.content, sender, channel)
            if reply:
                event.set_reply(reply)
                if hasattr(self, "_log") and self._log:
                    self._log(f"[插件] 回复: {reply[:100]}")
        except Exception as e:
            logger.error(f"Plugin stage error: {e}")
