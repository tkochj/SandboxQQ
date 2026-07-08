import logging
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any

from message import MessageEvent

logger = logging.getLogger(__name__)


class Platform(ABC):
    def __init__(self, config: Any, event_bus=None):
        self.config = config
        self._event_bus = event_bus
        self._on_message: Optional[Callable] = None
        self._on_event: Optional[Callable] = None
        self._running = False

    def on_message(self, callback: Callable):
        self._on_message = callback

    def on_event(self, callback: Callable):
        self._on_event = callback

    def commit_event(self, event: MessageEvent):
        if self._event_bus is not None:
            self._event_bus.publish(event)

    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

    @abstractmethod
    async def send_message(self, channel_id: str, content: str,
                           msg_id: str = "", event_type: str = "") -> bool:
        ...

    def is_running(self) -> bool:
        return self._running
