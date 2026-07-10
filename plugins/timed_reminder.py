import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "reminders.json")

class Plugin:
    name = "定时提醒"
    description = "创建定时提醒任务，到时间自动发送提醒消息"
    version = "1.0"

    def __init__(self):
        self._reminders = []
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self._load()

    def on_load(self):
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        logger.info("定时提醒插件已启动")

    def _load(self):
        if not os.path.exists(DATA_FILE):
            self._save()
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                self._reminders = json.load(f)
            logger.info(f"已加载 {len(self._reminders)} 个提醒")
        except Exception as e:
            logger.warning(f"加载提醒失败: {e}")
            self._reminders = []

    def _save(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self._reminders, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存提醒失败: {e}")

    def _scheduler_loop(self):
        # Wait for bot_manager to become available
        for _ in range(10):
            from ai.plugins import _bot_manager as bm
            if bm is not None:
                break
            time.sleep(2)
        while self._running:
            try:
                self._check_reminders()
            except Exception as e:
                logger.warning(f"提醒检查错误: {e}")
            time.sleep(15)

    def _check_reminders(self):
        now = time.time()
        fired = []
        with self._lock:
            keep = []
            for r in self._reminders:
                rtype = r.get("type", "once")
                next_time = r.get("next_time", 0)
                if next_time > 0 and now >= next_time:
                    fired.append(r)
                    if rtype == "once":
                        continue
                    elif rtype == "daily":
                        r["next_time"] = next_time + 86400
                        keep.append(r)
                    elif rtype == "hourly":
                        r["next_time"] = next_time + 3600
                        keep.append(r)
                    elif rtype == "interval":
                        interval = r.get("interval", 3600)
                        r["next_time"] = next_time + interval
                        keep.append(r)
                else:
                    keep.append(r)
            self._reminders = keep
        if fired:
            self._save()
        for r in fired:
            self._send_reminder(r)

    def _send_reminder(self, reminder):
        try:
            from ai.plugins import _bot_manager
            if _bot_manager:
                bot_id = reminder.get("bot_id", "")
                channel_id = reminder.get("channel_id", "")
                content = reminder.get("content", "")
                if channel_id and content:
                    _bot_manager.send_message(
                        channel_id=channel_id, content=f"⏰ 提醒: {content}", bot_id=bot_id,
                    )
        except Exception as e:
            logger.error(f"发送提醒失败: {e}")

    async def get_tool_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_reminder",
                    "description": "创建定时提醒。支持一次性、每日、每小时、或自定义间隔提醒。到时间后会自动发送消息到当前对话。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "提醒内容"},
                            "type": {
                                "type": "string",
                                "enum": ["once", "daily", "hourly", "interval"],
                                "description": "提醒类型: once=一次性, daily=每天, hourly=每小时, interval=自定义间隔秒数",
                            },
                            "delay_seconds": {
                                "type": "integer",
                                "description": "延迟秒数（从现在开始多少秒后触发，用于一次性提醒或首次触发）",
                            },
                            "interval": {
                                "type": "integer",
                                "description": "间隔秒数（仅 interval 类型），如 3600=1小时",
                            },
                            "time_str": {
                                "type": "string",
                                "description": "指定触发时间（HH:MM 格式，用于 daily 类型），如 '14:30' 表示每天14:30",
                            },
                        },
                        "required": ["content", "type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_reminders",
                    "description": "列出所有已创建的定时提醒",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_reminder",
                    "description": "删除指定的定时提醒",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer", "description": "要删除的提醒序号（从0开始）"},
                        },
                        "required": ["index"],
                    },
                },
            },
        ]

    async def create_reminder(self, content: str, type: str = "once", delay_seconds: int = 60, interval: int = 3600, time_str: str = ""):
        if not content:
            return "错误: 提醒内容不能为空"
        now = time.time()
        next_time = 0
        if type == "once":
            next_time = now + delay_seconds
        elif type == "daily":
            if time_str:
                try:
                    parts = time_str.split(":")
                    target = datetime.now().replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
                    if target.timestamp() <= now:
                        target += timedelta(days=1)
                    next_time = target.timestamp()
                except:
                    next_time = now + delay_seconds
            else:
                next_time = now + delay_seconds
        elif type == "hourly":
            next_time = now + delay_seconds
        elif type == "interval":
            next_time = now + delay_seconds
        else:
            return f"错误: 未知提醒类型 {type}"

        with self._lock:
            self._reminders.append({
                "content": content,
                "type": type,
                "next_time": next_time,
                "interval": interval,
                "bot_id": getattr(self, '_current_bot_id', ''),
                "channel_id": getattr(self, '_current_channel_id', ''),
                "created_at": now,
            })
        self._save()
        trigger_str = datetime.fromtimestamp(next_time).strftime("%Y-%m-%d %H:%M:%S")
        return f"提醒已创建！将在 {trigger_str} 触发：{content}"

    async def list_reminders(self):
        with self._lock:
            if not self._reminders:
                return "暂无提醒"
            lines = []
            for i, r in enumerate(self._reminders):
                t = datetime.fromtimestamp(r["next_time"]).strftime("%m-%d %H:%M")
                lines.append(f"  [{i}] {r['content']} ({r['type']}, 下次: {t})")
            return f"当前提醒 ({len(lines)} 个):\n" + "\n".join(lines)

    async def delete_reminder(self, index: int):
        with self._lock:
            if index < 0 or index >= len(self._reminders):
                return f"错误: 序号 {index} 超出范围 (0-{len(self._reminders)-1})"
            r = self._reminders.pop(index)
        self._save()
        return f"已删除提醒: {r['content']}"
