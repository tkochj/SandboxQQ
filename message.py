import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class MessageEvent:
    platform_name: str = ""
    message_id: str = ""
    sender_id: str = ""
    sender_name: str = ""
    channel_id: str = ""
    guild_id: str = ""
    content: str = ""
    msg_type: str = ""
    attachments: list = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
    timestamp: float = 0.0
    reply_text: str = ""
    reply_file: str = ""
    is_stopped: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def set_reply(self, text: str):
        self.reply_text = text
        self.is_stopped = True

    def stop(self):
        self.is_stopped = True

    @classmethod
    def from_bot_data(cls, data: dict, platform: str = "qq_official"):
        sender_id = data.get("author", {}).get("id", "") or str(data.get("user_id", ""))
        sender_name = data.get("author", {}).get("username", "") or data.get("sender", {}).get("nickname", "")
        channel_id = data.get("channel_id", "") or data.get("group_id", "") or data.get("user_id", "") or data.get("group_openid", "")
        guild_id = data.get("guild_id", "")
        content = ""
        attachments = list(data.get("attachments", []))
        if "content" in data:
            content = data["content"]
        elif "message" in data:
            msg = data["message"]
            if isinstance(msg, list):
                for seg in msg:
                    stype = seg.get("type", "")
                    sdata = seg.get("data", {})
                    if stype == "text":
                        content += sdata.get("text", "")
                    elif stype in ("image", "video", "file", "audio"):
                        url = sdata.get("url", sdata.get("file", ""))
                        attachments.append({"type": stype, "url": url, "name": sdata.get("name", "")})
            else:
                content = str(msg)
        if not content.strip() and not attachments:
            content = "(media message)"
        event_type = data.get("t", "")
        return cls(
            platform_name=platform,
            message_id=data.get("id", str(time.time())),
            sender_id=sender_id,
            sender_name=sender_name,
            channel_id=channel_id,
            guild_id=guild_id,
            content=content,
            msg_type=event_type,
            attachments=attachments,
            raw_data=data,
        )
