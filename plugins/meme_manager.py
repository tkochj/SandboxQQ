# -*- coding: utf-8 -*-
"""
表情/梗图管理器
- AI 回复中检测情绪标记自动配本地梗图
- 支持命令管理图库
- 图片本地存储，通过 send_file 发送给用户

情绪标记: &&happy&& [sad] (angry) 等
命令:
  /meme list          - 查看图库
  /meme add 分类      - 添加表情(随后发图)
  /meme del 分类 名称  - 删除表情
"""
import os, re, json, shutil, logging, random, base64
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "meme_data"
MEMES_DIR = DATA_DIR / "images"
CONFIG_PATH = DATA_DIR / "config.json"

EMOTION_MAP = {
    "happy": ["happy", "joy", "laugh", "开心", "快乐", "哈哈", "😊", "😂", "😄"],
    "sad": ["sad", "cry", "伤心", "难过", "哭", "😢", "😭", "悲伤"],
    "angry": ["angry", "mad", "生气", "愤怒", "😠", "😡", "🔥"],
    "love": ["love", "heart", "爱", "喜欢", "❤️", "😍", "🥰"],
    "surprise": ["surprise", "shock", "惊讶", "震惊", "😱", "😮", "🤯"],
    "fear": ["fear", "scared", "害怕", "恐惧", "😨", "😰"],
    "disgust": ["disgust", "恶心", "讨厌", "🤢", "🤮"],
    "cool": ["cool", "awesome", "帅", "酷", "😎", "👍", "nice"],
    "laugh": ["laugh", "rofl", "笑死", "🤣", "😂", "搞笑"],
    "shy": ["shy", "blush", "害羞", "😳", "🤭"],
    "awkward": ["awkward", "尴尬", "😅", "🙃", "无语"],
}

class Plugin:
    name = "表情包管理器"
    description = "AI 回复中检测情绪标记自动配本地梗图，支持命令管理图库"
    version = "1.0"
    _last_file = ""

    def __init__(self):
        self.memes = {}  # {category: [filename, ...]}
        MEMES_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._load()
        self._ensure_defaults()
        logger.info(f"表情包管理器就绪: {sum(len(v) for v in self.memes.values())} 张")

    def _load(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.memes = json.load(f)
            except Exception:
                self.memes = {}

    def _save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.memes, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存失败: {e}")

    def _ensure_defaults(self):
        for emotion in EMOTION_MAP:
            if emotion not in self.memes:
                self.memes[emotion] = []
        self._save()

    def _detect_emotions(self, text: str) -> list:
        found = []
        for pattern in [r"&&(\w+)&&", r"\[(\w+)\]", r"\((\w+)\)"]:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                word = m.group(1).lower()
                for emo, keywords in EMOTION_MAP.items():
                    if word == emo or word in keywords:
                        if emo not in found:
                            found.append(emo)
        for emo, keywords in EMOTION_MAP.items():
            if emo not in found:
                for kw in keywords:
                    if len(kw) > 1 and kw in text.lower():
                        found.append(emo)
                        break
        return found[:2]

    async def on_message(self, content: str, sender: dict, channel: dict) -> Optional[str]:
        text = content.strip()
        if not text.startswith("/meme "):
            return None
        parts = text.split()
        cmd = parts[1] if len(parts) > 1 else ""
        if cmd == "list":
            lines = [f"📁 表情图库:"]
            for k, v in self.memes.items():
                lines.append(f"  {k}: {len(v)}张")
            return "\n".join(lines)
        elif cmd == "add" and len(parts) >= 3:
            cat = parts[2]
            if cat not in self.memes:
                self.memes[cat] = []
                self._save()
            return f"请发送图片到沙盒目录，然后使用 /meme save {cat} 文件名"
        elif cmd == "save" and len(parts) >= 4:
            cat = parts[2]
            fname = parts[3]
            src = Path(MEMES_DIR).parent.parent / fname
            if src.is_file():
                dst = MEMES_DIR / f"{cat}_{len(self.memes.get(cat,[]))}_{src.name}"
                shutil.copy2(src, dst)
                self.memes.setdefault(cat, []).append(dst.name)
                self._save()
                return f"已添加 {dst.name} 到 [{cat}]"
            return f"文件不存在: {fname}"
        elif cmd == "del" and len(parts) >= 4:
            cat = parts[2]
            name = parts[3]
            if cat in self.memes:
                self.memes[cat] = [m for m in self.memes[cat] if name not in m]
                self._save()
                return f"已删除"
        return "用法: /meme list | add 分类 | del 分类 名称"

    async def get_tool_definitions(self):
        emotions = ", ".join(EMOTION_MAP.keys())
        return [{
            "type": "function",
            "function": {
                "name": "send_meme",
                "description": f"发送一张表情梗图。AI回复中含 &&emotion&& 标记时会自动调用。支持: {emotions}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "emotion": {"type": "string", "description": f"情绪: {emotions}", "enum": list(EMOTION_MAP.keys())},
                        "text": {"type": "string", "description": "附带文字"},
                    },
                    "required": ["emotion"],
                },
            },
        }]

    async def send_meme(self, emotion: str, text: str = "") -> str:
        emotion = emotion.lower()
        files = self.memes.get(emotion, [])
        if not files:
            # Generate a simple colored image as placeholder
            return self._generate_placeholder(emotion, text)
        fname = random.choice(files)
        fpath = MEMES_DIR / fname
        if fpath.is_file():
            self._last_file = str(fpath)
            result = f"[{emotion}] 表情已准备发送"
            return f"{text}\n{result}" if text else result
        return self._generate_placeholder(emotion, text)

    def _generate_placeholder(self, emotion: str, text: str = "") -> str:
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (400, 300), (random.randint(30, 200), random.randint(30, 200), random.randint(30, 200)))
            draw = ImageDraw.Draw(img)
            draw.text((50, 120), f"[{emotion}]", fill="white")
            path = MEMES_DIR / f"_{emotion}_{random.randint(1000,9999)}.png"
            img.save(path)
            self._last_file = str(path)
            self.memes.setdefault(emotion, []).append(path.name)
            self._save()
            return f"{text}\n[生成占位表情: {emotion}]" if text else f"[生成占位表情: {emotion}]"
        except Exception as e:
            return f"[{emotion}] (无表情图)"

    def _download_default_pack(self):
        import httpx, asyncio, threading
        # GitHub meme pack categories and their image files
        pack = {
            "happy": "1739433254_1.png",
            "sad": "1739435062_1.jpg",
            "angry": "1739442498_1.jpg",
            "love": "1739438584_1.jpg",
            "surprise": "1739439476_1.jpg",
            "shy": "1739439660_1.jpg",
            "cool": "1739439919_1.jpg",
            "laugh": "1739434363_1.gif",
        }
        def download():
            import httpx
            base = "https://raw.githubusercontent.com/anka-afk/astrbot_plugin_meme_manager/main/memes"
            for cat, fname in pack.items():
                url = f"{base}/{cat}/{fname}"
                try:
                    resp = httpx.get(url, timeout=30)
                    if resp.status_code == 200:
                        dst = MEMES_DIR / f"{cat}_{fname}"
                        with open(dst, "wb") as f:
                            f.write(resp.content)
                        if cat not in self.memes:
                            self.memes[cat] = []
                        if dst.name not in self.memes[cat]:
                            self.memes[cat].append(dst.name)
                        logger.info(f"下载表情: {cat}/{fname}")
                except Exception as e:
                    logger.warning(f"下载失败 {cat}/{fname}: {e}")
            self._save()
        threading.Thread(target=download, daemon=True).start()

    def settings_widget(self):
        from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                       QListWidget, QListWidgetItem, QWidget, QMessageBox)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(f"表情目录: {MEMES_DIR}"))
        stats = {k: len(v) for k, v in self.memes.items()}
        layout.addWidget(QLabel(f"总计: {sum(stats.values())} 张表情"))
        self._meme_stat_list = QListWidget()
        for k, v in stats.items():
            self._meme_stat_list.addItem(QListWidgetItem(f"{k}: {v}张"))
        layout.addWidget(self._meme_stat_list)
        btn_row = QHBoxLayout()
        btn_open = QPushButton("打开目录")
        btn_open.clicked.connect(lambda: os.startfile(str(MEMES_DIR)))
        btn_row.addWidget(btn_open)
        btn_download = QPushButton("下载默认表情包")
        btn_download.clicked.connect(lambda: (self._download_default_pack(), QMessageBox.information(w, "提示", "开始下载表情包，请稍后刷新")))
        btn_row.addWidget(btn_download)
        btn_reset = QPushButton("清空")
        def reset_all():
            for emo in EMOTION_MAP:
                self.memes[emo] = []
            self._save()
            self._meme_stat_list.clear()
            for k, v in self.memes.items():
                self._meme_stat_list.addItem(QListWidgetItem(f"{k}: {len(v)}张"))
            QMessageBox.information(w, "提示", "已清空所有表情")
        btn_reset.clicked.connect(reset_all)
        btn_row.addWidget(btn_reset)
        layout.addLayout(btn_row)
        return w
