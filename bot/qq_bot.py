import json
import os
import time
import asyncio
import logging
import threading
from typing import Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

import aiohttp
import botpy
from botpy.message import Message, GroupMessage, C2CMessage, DirectMessage
from botpy.types.message import Reference

from bot.base import Platform
from event_bus import EventBus
from message import MessageEvent

logger = logging.getLogger(__name__)


class BotProtocol(Enum):
    QQ_OFFICIAL = "qq_official"
    ONEBOT = "onebot"


@dataclass
class BotConfig:
    name: str = ""
    protocol: BotProtocol = BotProtocol.QQ_OFFICIAL
    app_id: str = ""
    app_secret: str = ""
    bot_token: str = ""
    ws_url: str = "wss://api.sgroup.qq.com/websocket"
    api_url: str = "https://api.sgroup.qq.com"
    sandbox_api_url: str = "https://sandbox.api.sgroup.qq.com"
    use_sandbox: bool = False
    onebot_ws_url: str = "ws://127.0.0.1:8080"
    onebot_http_url: str = "http://127.0.0.1:8080"
    intents: list = field(default_factory=lambda: [
        "GUILD_MESSAGES",
        "DIRECT_MESSAGE",
        "PUBLIC_GUILD_MESSAGES",
    ])
    enabled: bool = False
    sandbox_root: str = ""

    def get_intent_value(self) -> int:
        intent_map = {
            "GUILDS": 1 << 0,
            "GUILD_MEMBERS": 1 << 1,
            "GUILD_MESSAGES": 1 << 9,
            "GUILD_MESSAGE_REACTIONS": 1 << 10,
            "DIRECT_MESSAGE": 1 << 12,
            "OPEN_FORUM_EVENT": 1 << 18,
            "AUDIO_OR_LIVE_CHANNEL_MEMBER": 1 << 19,
            "PUBLIC_GUILD_MESSAGES": 1 << 25,
        }
        value = 0
        for intent in self.intents:
            if intent in intent_map:
                value |= intent_map[intent]
        return value

    def get_base_url(self) -> str:
        return self.sandbox_api_url if self.use_sandbox else self.api_url

    def to_dict(self):
        return {
            "name": self.name,
            "protocol": self.protocol.value,
            "app_id": self.app_id,
            "app_secret": self.app_secret,
            "bot_token": self.bot_token,
            "ws_url": self.ws_url,
            "api_url": self.api_url,
            "sandbox_api_url": self.sandbox_api_url,
            "use_sandbox": self.use_sandbox,
            "onebot_ws_url": self.onebot_ws_url,
            "onebot_http_url": self.onebot_http_url,
            "intents": self.intents,
            "enabled": self.enabled,
            "sandbox_root": self.sandbox_root,
        }

    @classmethod
    def from_dict(cls, data: dict):
        config = cls()
        config.name = data.get("name", data.get("app_id", "")[:8])
        config.protocol = BotProtocol(data.get("protocol", BotProtocol.QQ_OFFICIAL.value))
        config.app_id = data.get("app_id", "")
        config.app_secret = data.get("app_secret", "")
        config.bot_token = data.get("bot_token", "")
        config.ws_url = data.get("ws_url", config.ws_url)
        config.api_url = data.get("api_url", config.api_url)
        config.sandbox_api_url = data.get("sandbox_api_url", config.sandbox_api_url)
        config.use_sandbox = data.get("use_sandbox", False)
        config.onebot_ws_url = data.get("onebot_ws_url", config.onebot_ws_url)
        config.onebot_http_url = data.get("onebot_http_url", config.onebot_http_url)
        config.intents = data.get("intents", config.intents)
        config.enabled = data.get("enabled", False)
        config.sandbox_root = data.get("sandbox_root", "")
        return config


class _BotpyClient(botpy.Client):
    def __init__(self, platform: "QQOfficialPlatform", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._platform = platform

    async def on_ready(self):
        self._platform._ws_connected = True
        logger.info("QQ bot WebSocket connected (READY)")

    async def on_at_message_create(self, message: Message):
        self._platform._handle_botpy_msg(message, "AT_MESSAGE_CREATE")

    async def on_message_create(self, message: Message):
        self._platform._handle_botpy_msg(message, "MESSAGE_CREATE")

    async def on_direct_message_create(self, message: DirectMessage):
        self._platform._handle_botpy_msg(message, "DIRECT_MESSAGE_CREATE")

    async def on_group_at_message_create(self, message: GroupMessage):
        self._platform._handle_botpy_msg(message, "GROUP_AT_MESSAGE_CREATE")

    async def on_group_message_create(self, message: GroupMessage):
        # Catch-all for group messages — QQ API may skip on_group_at_message_create
        # when multiple users are @'d alongside the bot.
        app_id = self._platform.config.app_id
        if not app_id:
            return
        # Check various @ mention formats used by QQ API
        content = message.content or ""
        if app_id in content or f"<@{app_id}>" in content or f"<@!{app_id}>" in content:
            self._platform._handle_botpy_msg(message, "GROUP_AT_MESSAGE_CREATE")

    async def on_c2c_message_create(self, message: C2CMessage):
        self._platform._handle_botpy_msg(message, "C2C_MESSAGE_CREATE")


class QQOfficialPlatform(Platform):
    def __init__(self, config: BotConfig, event_bus: EventBus = None):
        super().__init__(config, event_bus)
        self.config = config
        self._thread: Optional[threading.Thread] = None
        self._ws_connected = False
        self._client: Optional[_BotpyClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def is_running(self) -> bool:
        return self._running and self._ws_connected

    @property
    def bot_id(self) -> str:
        return self.config.app_id

    def _handle_botpy_msg(self, msg, event_type: str):
        author = getattr(msg, "author", None)
        sender_id = ""
        sender_name = ""
        user_openid = ""
        if author:
            sender_id = str(getattr(author, "member_openid", None) or getattr(author, "user_openid", None) or getattr(author, "id", ""))
            sender_name = getattr(author, "username", "") or getattr(getattr(msg, "member", None), "nick", "") or ""
            user_openid = str(getattr(author, "user_openid", "") or getattr(author, "id", ""))

        channel_id = getattr(msg, "channel_id", "") or getattr(msg, "group_openid", "") or user_openid
        guild_id = getattr(msg, "guild_id", "")
        content = getattr(msg, "content", "")
        msg_id = getattr(msg, "id", "")
        attachments = getattr(msg, "attachments", []) or []

        event = MessageEvent(
            bot_id=self.bot_id,
            platform_name="qq_official",
            message_id=str(msg_id) if msg_id else "",
            sender_id=sender_id,
            sender_name=sender_name,
            channel_id=channel_id,
            guild_id=guild_id,
            content=content or "",
            msg_type=event_type,
            attachments=[{"type": "attachment", "url": getattr(a, "url", ""), "name": getattr(a, "filename", "")} for a in (attachments or [])],
        )
        self.commit_event(event)
        raw_dict = {
            "id": msg_id,
            "content": content,
            "author": {"id": sender_id, "username": sender_name},
            "channel_id": channel_id,
            "guild_id": guild_id,
            "t": event_type,
        }
        if self._on_message:
            try:
                self._on_message(raw_dict)
            except Exception as e:
                logger.error(f"Message handler error: {e}")

    async def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_botpy, daemon=True)
        self._thread.start()
        logger.info("QQ bot starting (botpy)...")

    def _run_botpy(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            intents = botpy.Intents(
                public_guild_messages=True,
                public_messages=True,
                direct_message=True,
            )
            self._client = _BotpyClient(
                platform=self,
                intents=intents,
                bot_log=False,
                timeout=20,
            )
            secret = self.config.app_secret or self.config.bot_token
            self._loop.run_until_complete(self._client.start(
                appid=self.config.app_id,
                secret=secret,
            ))
        except Exception as e:
            logger.error(f"botpy error: {e}")
        finally:
            self._ws_connected = False
            self._loop.close()
            self._loop = None

    async def stop(self):
        self._running = False
        self._ws_connected = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        logger.info("QQ bot stopped")

    async def send_message(self, channel_id: str, content: str,
                           msg_id: str = "", event_type: str = "") -> bool:
        if not self._client:
            logger.warning("Bot client not ready")
            return False
        import random
        try:
            kwargs = {"content": content, "msg_id": msg_id or None, "msg_seq": random.randint(1, 99999)}
            if "GROUP" in event_type:
                await self._client.api.post_group_message(
                    group_openid=channel_id, **kwargs)
            elif "C2C" in event_type or "DIRECT" in event_type:
                await self._client.api.post_c2c_message(
                    openid=channel_id, **kwargs)
            else:
                await self._client.api.post_message(
                    channel_id=channel_id, **kwargs)
            return True
        except Exception as e:
            logger.error(f"Send message error: {e}")
            return False

    async def send_file(self, channel_id: str, file_path: str,
                        content: str = "", msg_id: str = "",
                        event_type: str = "") -> bool:
        if not self._client:
            logger.warning("Bot client not ready")
            return False
        if not os.path.isfile(file_path):
            logger.warning(f"File not found: {file_path}")
            return False

        import base64
        ext = os.path.splitext(file_path)[1].lower()
        img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
        audio_exts = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}

        try:
            # Channel messages can use file_image directly
            if "GROUP" not in event_type and "C2C" not in event_type and "DIRECT" not in event_type:
                if ext in img_exts:
                    await self._client.api.post_message(
                        channel_id=channel_id, content=content,
                        file_image=file_path, msg_id=msg_id or None)
                    return True
                fname = os.path.basename(file_path)
                fsize = os.path.getsize(file_path)
                await self._client.api.post_message(
                    channel_id=channel_id,
                    content=f"{content}\n[文件: {fname} ({fsize/1024:.0f}KB)]",
                    msg_id=msg_id or None)
                return True

            # For group/C2C: upload file first, then send media message
            if ext in img_exts:
                file_type = 1
            elif ext in video_exts:
                file_type = 2
            elif ext in audio_exts:
                file_type = 3
            else:
                file_type = 4

            with open(file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode()

            from botpy.http import Route
            if "GROUP" in event_type:
                route = Route("POST", "/v2/groups/{group_openid}/files", group_openid=channel_id)
            else:
                route = Route("POST", "/v2/users/{openid}/files", openid=channel_id)

            upload_resp = await self._client.api._http.request(route, json={
                "file_type": file_type,
                "file_data": b64_data,
            })
            file_info = upload_resp.get("file_info", "") if isinstance(upload_resp, dict) else getattr(upload_resp, "file_info", "")

            if not file_info:
                logger.warning("File upload failed: no file_info")
                return False

            import random
            if "GROUP" in event_type:
                await self._client.api.post_group_message(
                    group_openid=channel_id, msg_type=7,
                    media={"file_info": file_info},
                    content=content or "", msg_id=msg_id or None,
                    msg_seq=random.randint(1, 99999))
            else:
                await self._client.api.post_c2c_message(
                    openid=channel_id, msg_type=7,
                    media={"file_info": file_info},
                    content=content or "", msg_id=msg_id or None,
                    msg_seq=random.randint(1, 99999))
            return True
        except Exception as e:
            logger.error(f"Send file error: {e}")
            return False
