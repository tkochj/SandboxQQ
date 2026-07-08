import logging
from typing import Callable, List

from pipeline.stage import Stage

logger = logging.getLogger(__name__)


class AuthStage(Stage):
    name = "auth"

    def __init__(self, auth_check: Callable[[str], bool] = None):
        self._auth_check = auth_check

    def set_auth_check(self, check: Callable[[str], bool]):
        self._auth_check = check

    async def process(self, event):
        if self._auth_check and not self._auth_check(event.sender_id):
            logger.info(f"Blocked unauthorized user: {event.sender_id}")
            event.set_reply("你没有使用权限，请联系管理员添加。")
            yield
            return
        yield
