# -*- coding: utf-8 -*-
"""
表情/梗图管理器插件
- AI 回复中检测情绪标记自动配图
- 支持命令管理图库
- 图片本地存储 + 可选云同步

用法:
  发送 /meme list - 查看图库
  发送 /meme add 分类 - 添加表情(随后发图)
  发送 /meme del 分类 名称 - 删除表情

AI 回复中包含 &&情绪&& 或 [情绪] 或 (情绪) 时自动配图
支持情绪: happy, sad, angry, love, surprise, fear, disgust, cool, cry, laugh, shy, awkward
"""
import os
import re
import json
import shutil
import logging
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MEMES_DIR = Path(__file__).resolve().parent / "meme_manager_data" / "memes"
CONFIG_PATH = Path(__file__).resolve().parent / "meme_manager_data" / "config.json"

EMOTION_KEYWORDS = {
    "happy": ["happy", "joy", "laugh", "哈哈", "开心", "快乐", "😊", "😂", "😄", "愉快"],
    "sad": ["sad", "cry", "伤心", "难过", "哭", "😢", "😭", "悲伤", "泪"],
    "angry": ["angry", "mad", "生气", "愤怒", "怒", "😠", "😡", "🔥"],
    "love": ["love", "heart", "爱", "喜欢", "❤️", "😍", "🥰", "亲"],
    "surprise": ["surprise", "shock", "惊讶", "震惊", "😱", "😮", "🤯", "吃惊"],
    "fear": ["fear", "scared", "害怕", "恐惧", "😨", "😰", "怕"],
    "disgust": ["disgust", "恶心", "讨厌", "🤢", "🤮", "嫌弃"],
    "cool": ["cool", "awesome", "帅", "酷", "😎", "👍", "nice", "厉害"],
    "cry": ["cry", "sob", "大哭", "😭"],
    "laugh": ["laugh", "rofl", "笑死", "🤣", "😂", "搞笑"],
    "shy": ["shy", "blush", "害羞", "😳", "🤭", "脸红"],
    "awkward": ["awkward", "尴尬", "😅", "🙃", "无语", "汗"],
}

DEFAULT_MEMES = {
    "happy": ["https://media.giphy.com/media/26BRzozg4TCBXv6QU/giphy.gif"],
    "sad": ["https://media.giphy.com/media/13GEqpi85CQk7S/giphy.gif"],
    "angry": ["https://media.giphy.com/media/3og0INyCmHlNylU9Sg/giphy.gif"],
    "love": ["https://media.giphy.com/media/l2QDM9Jnim1YVILXa/giphy.gif"],
    "surprise": ["https://media.giphy.com/media/26gJzV3sA3GQ3p0H6/giphy.gif"],
    "cool": ["https://media.giphy.com/media/26FPCXdkvDbHr1Kju/giphy.gif"],
    "laugh": ["https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif"],
    "cry": ["https://media.giphy.com/media/3o6Zt6eXqWQqKjXK0/giphy.gif"],
}


class Plugin:
    name = "表情管理器"
    description = "AI 回复中检测情绪自动配梗图，支持命令管理图库"
    version = "1.0"

    def __init__(self):
        self.memes = {}
        self._ensure_dirs()
        self._load_config()
        logger.info(f"表情管理器已初始化，{sum(len(v) for v in self.memes.values())} 个表情")

    def _ensure_dirs(self):
        MEMES_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.memes = json.load(f)
                return
            except Exception:
                pass
        self.memes = {k: list(v) for k, v in DEFAULT_MEMES.items()}
        self._save_config()

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.memes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存表情配置失败: {e}")

    def _detect_emotions(self, text: str) -> list:
        found = []
        # Direct markers: &&emotion&&, [emotion], (emotion)
        for pattern in [r"&&(\w+)&&", r"\[(\w+)\]", r"\((\w+)\)"]:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                word = m.group(1).lower()
                for emotion, keywords in EMOTION_KEYWORDS.items():
                    if word == emotion or word in keywords:
                        if emotion not in found:
                            found.append(emotion)
                        break
        # Loose matching: check text for emotion keywords
        for emotion, keywords in EMOTION_KEYWORDS.items():
            if emotion not in found:
                for kw in keywords:
                    if len(kw) > 1 and kw in text.lower():
                        found.append(emotion)
                        break
        return found[:3]  # Max 3 emotions

    async def on_message(self, content: str, sender: dict, channel: dict) -> Optional[str]:
        text = content.strip()
        if not text.startswith("/meme "):
            return None
        parts = text.split()
        cmd = parts[1] if len(parts) > 1 else ""
        if cmd == "list":
            cats = "\n".join([f"  {k}({len(v)}张)" for k, v in self.memes.items()])
            return f"📁 表情图库:\n{cats}\n发送 /meme add 分类 添加"
        elif cmd == "add" and len(parts) >= 3:
            category = parts[2]
            if category not in self.memes:
                self.memes[category] = []
                self._save_config()
            return f"请发送图片, 将添加到 [{category}]\n发送完成后回复 ok"
        elif cmd == "del" and len(parts) >= 4:
            category = parts[2]
            name = parts[3]
            if category in self.memes:
                self.memes[category] = [m for m in self.memes[category] if name not in m]
                self._save_config()
                return f"已删除 {category}/{name}"
        return "用法: /meme list | add 分类 | del 分类 名称"

    async def get_tool_definitions(self):
        emotions = ", ".join(EMOTION_KEYWORDS.keys())
        return [{
            "type": "function",
            "function": {
                "name": "send_meme",
                "description": f"发送一张情绪梗图。支持情绪: {emotions}。AI回复中包含 &&emotion&& 标记时会自动调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "emotion": {
                            "type": "string",
                            "description": f"情绪名称: {emotions}",
                            "enum": list(EMOTION_KEYWORDS.keys()),
                        },
                        "text": {"type": "string", "description": "附带文字"},
                    },
                    "required": ["emotion"],
                },
            },
        }]

    async def send_meme(self, emotion: str, text: str = "") -> str:
        emotion = emotion.lower()
        urls = self.memes.get(emotion, [])
        if not urls:
            return f"没有找到 [{emotion}] 的表情"
        url = random.choice(urls)
        result = f"[表情: {emotion}] {url}"
        if text:
            result = f"{text}\n{result}"
        return result
