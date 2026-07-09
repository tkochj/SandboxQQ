import asyncio
import logging
import os
from typing import Callable, Optional

from pipeline.stage import Stage

logger = logging.getLogger(__name__)


class RespondStage(Stage):
    name = "respond"

    def __init__(self, send_func: Callable[[str, str, str, str, str], None],
                 send_file_func: Optional[Callable] = None,
                 log_func: Optional[Callable] = None):
        self._send = send_func
        self._send_file = send_file_func
        self._log = log_func

    async def process(self, event):
        yield
        if not event.is_stopped:
            return

        loop = asyncio.get_running_loop()
        bot_id = event.bot_id

        sent_file = False
        if event.reply_file and self._send_file:
            fpath = event.reply_file
            if os.path.isfile(fpath):
                try:
                    if self._log:
                        self._log("[Bot回复] 发送文件: %s" % fpath)
                    await loop.run_in_executor(
                        None, self._send_file, bot_id, event.channel_id, fpath,
                        event.reply_text, event.message_id, event.msg_type,
                    )
                    sent_file = True
                except Exception as e:
                    logger.error("Send file error: %s", e)

        if event.reply_text and not (sent_file and not event.reply_text.strip()):
            try:
                if self._log:
                    self._log("[Bot回复] 发给 %s: %s" % (event.sender_id, event.reply_text[:200]))
                await loop.run_in_executor(
                    None, self._send, bot_id, event.channel_id, event.reply_text,
                    event.message_id, event.msg_type,
                )
            except Exception as e:
                logger.error("RespondStage send error: %s", e)
