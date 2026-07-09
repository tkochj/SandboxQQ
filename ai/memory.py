import os
import json
import time
import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ConversationMemory:
    def __init__(self, max_history: int = 50, context_window: int = 32000,
                 context_mode: str = "truncation", persist_path: str = ""):
        self._histories: Dict[str, List[dict]] = {}
        self._max_history = max_history
        self._context_window = context_window
        self._context_mode = context_mode
        self._persist_path = persist_path
        self._dirty = False
        self._lock = threading.Lock()
        self._load()

    def configure(self, context_window: int = 32000, context_mode: str = "truncation"):
        self._context_window = context_window
        self._context_mode = context_mode

    _SECRET_PATTERNS = [
        ('"api_key":\\s*"[\\w\\-]+"', '"api_key": "**REDACTED**"'),
        ('"app_secret":\\s*"[^"]+"', '"app_secret": "**REDACTED**"'),
        ('"bot_token":\\s*"[^"]+"', '"bot_token": "**REDACTED**"'),
        ('"token":\\s*"[^"]+"', '"token": "**REDACTED**"'),
        ('"secret":\\s*"[^"]+"', '"secret": "**REDACTED**"'),
        ('github_pat_[\\w\\-]+', 'github_pat_**REDACTED**'),
        ('ghp_[\\w\\-]+', 'ghp_**REDACTED**'),
        ('sk-[\\w\\-]{10,}', 'sk-**REDACTED**'),
        ('Bearer\\s+[\\w\\-\\.]+', 'Bearer **REDACTED**'),
    ]

    def add_message(self, channel_id: str, role: str, content: str):
        if not channel_id:
            return
        import re
        safe = content
        for pattern, replacement in self._SECRET_PATTERNS:
            safe = re.sub(pattern, replacement, safe)
        with self._lock:
            if channel_id not in self._histories:
                self._histories[channel_id] = []
            self._histories[channel_id].append({
                "role": role,
                "content": safe,
                "time": time.time(),
            })
            self._dirty = True
            self._trim(channel_id)
        self._save()

    def get_history(self, channel_id: str, system_prompt: str = "") -> List[dict]:
        with self._lock:
            if channel_id not in self._histories:
                return []
            history = self._histories[channel_id]
        if not history:
            return []

        mode = self._context_mode

        if mode == "full":
            return [{"role": m["role"], "content": m["content"]} for m in history]

        if mode == "compression":
            if len(history) <= 10:
                return [{"role": m["role"], "content": m["content"]} for m in history]
            keep = history[:4] + history[-6:]
            return [{"role": m["role"], "content": m["content"]} for m in keep]

        total = len(system_prompt or "")
        result = []
        for msg in reversed(history):
            text = msg.get("content", "") or ""
            if total + len(text) > self._context_window and result:
                break
            total += len(text)
            result.insert(0, {"role": msg["role"], "content": text})
        return result

    def clear(self, channel_id: str = None):
        with self._lock:
            if channel_id:
                self._histories.pop(channel_id, None)
            else:
                self._histories.clear()
            self._dirty = True
        self._save()

    def _trim(self, channel_id: str):
        history = self._histories.get(channel_id)
        if history and len(history) > self._max_history:
            self._histories[channel_id] = history[-self._max_history:]

    def _save(self):
        if not self._persist_path:
            return
        with self._lock:
            if not self._dirty:
                return
            data = {k: v for k, v in self._histories.items()}
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Memory save failed: {e}")

    def _load(self):
        if not self._persist_path or not os.path.isfile(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._histories = data
                self._dirty = False
            logger.info(f"Memory loaded: {sum(len(v) for v in data.values())} msgs in {len(data)} sessions")
        except Exception as e:
            logger.warning(f"Memory load failed: {e}")
