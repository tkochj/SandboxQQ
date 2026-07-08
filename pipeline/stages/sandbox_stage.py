import logging
from typing import Callable

from pipeline.stage import Stage

logger = logging.getLogger(__name__)


class SandboxCheckStage(Stage):
    name = "sandbox_check"

    def __init__(self, is_sandbox_running: Callable[[], bool]):
        self._is_running = is_sandbox_running

    async def process(self, event):
        if event.is_stopped:
            yield
            return
        if not self._is_running():
            event.set_reply("沙盒未启动，无法处理请求")
            yield
            return
        yield
