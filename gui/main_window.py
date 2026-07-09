import os
import sys
import json
import time
import math
import asyncio
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QTreeView,
    QSplitter, QMenuBar, QMenu, QStatusBar, QMessageBox,
    QLineEdit, QFormLayout, QGroupBox, QGridLayout,
    QListWidget, QListWidgetItem, QFrame, QApplication,
    QHeaderView, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QProgressBar, QScrollArea, QSizePolicy, QToolButton,
    QFileDialog, QCheckBox, QComboBox, QSpinBox,
    QDialog, QDialogButtonBox, QWidgetAction, QInputDialog,
)
from PyQt6.QtCore import (
    Qt, QTimer, QDir, QModelIndex, pyqtSignal, QObject,
    QSize, QPropertyAnimation, QEasingCurve, QRect,
)
from PyQt6.QtGui import (
    QAction, QIcon, QFont, QColor, QPalette, QPainter,
    QPixmap, QPen, QBrush, QLinearGradient, QRadialGradient,
    QPaintEvent, QFontDatabase, QActionGroup, QCursor,
    QShowEvent, QCloseEvent,
)

from sandbox.core import SandboxManager, SandboxConfig, SandboxState
from bot.manager import BotManager
from bot.qq_bot import BotConfig, BotProtocol
from bot.user_config import UserConfig, USER_CONFIG_FILE
from ai.config import AIConfig, ProviderConfig
from ai.provider import ProviderManager
from ai.chat import ChatSession, ChatMessage
from event_bus import EventBus
from pipeline import PipelineScheduler
from pipeline.stages import AuthStage, AIResponseStage, RespondStage, SandboxCheckStage
from ai.memory import ConversationMemory

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = str(APP_DIR / "sandbox_config.json")
BOT_CONFIG_FILE = str(APP_DIR / "bot_config.json")
AI_CONFIG_FILE = str(APP_DIR / "ai_config.json")

# ── 颜色主题 ──────────────────────────────────────────────
C_PRIMARY = "#6C5CE7"
C_PRIMARY_DARK = "#5A4BD1"
C_SUCCESS = "#00B894"
C_WARNING = "#FDCB6E"
C_DANGER = "#E17055"
C_INFO = "#74B9FF"
C_BG_DARK = "#1a1a2e"
C_BG_CARD = "#16213e"
C_BG_INPUT = "#0f3460"
C_TEXT = "#dfe6e9"
C_TEXT_DIM = "#b2bec3"
C_BORDER = "#2d3436"

STYLESHEET = f"""
QMainWindow {{
    background-color: {C_BG_DARK};
    color: {C_TEXT};
}}
QWidget {{
    color: {C_TEXT};
    font-size: 13px;
}}
QTabWidget::pane {{
    background-color: {C_BG_DARK};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QTabBar::tab {{
    background-color: {C_BG_CARD};
    color: {C_TEXT_DIM};
    padding: 10px 24px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background-color: {C_PRIMARY};
    color: white;
}}
QTabBar::tab:hover:!selected {{
    background-color: #1e2d50;
}}
QGroupBox {{
    background-color: {C_BG_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    margin-top: 16px;
    padding: 20px 16px 16px;
    font-weight: 600;
    color: {C_TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: {C_PRIMARY};
    font-weight: 700;
    font-size: 14px;
}}
QPushButton {{
    background-color: {C_PRIMARY};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {C_PRIMARY_DARK};
}}
QPushButton:pressed {{
    background-color: #4A3DB8;
}}
QPushButton:disabled {{
    background-color: #2d3436;
    color: #636e72;
}}
QPushButton[type="danger"] {{
    background-color: {C_DANGER};
}}
QPushButton[type="danger"]:hover {{
    background-color: #d63031;
}}
QPushButton[type="success"] {{
    background-color: {C_SUCCESS};
}}
QPushButton[type="success"]:hover {{
    background-color: #00a381;
}}
QLineEdit, QSpinBox, QComboBox {{
    background-color: {C_BG_INPUT};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {C_PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {C_BG_INPUT};
    color: {C_TEXT};
    selection-background-color: {C_PRIMARY};
}}
QTextEdit {{
    background-color: {C_BG_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}}
QTableWidget {{
    background-color: {C_BG_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    gridline-color: {C_BORDER};
}}
QTableWidget::item {{
    padding: 6px;
}}
QTableWidget::item:selected {{
    background-color: {C_PRIMARY};
}}
QHeaderView::section {{
    background-color: {C_BG_INPUT};
    color: {C_TEXT};
    padding: 8px;
    border: none;
    border-bottom: 2px solid {C_PRIMARY};
    font-weight: 600;
}}
QListWidget {{
    background-color: {C_BG_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background-color: {C_PRIMARY};
}}
QTreeView {{
    background-color: {C_BG_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
}}
QTreeView::item:selected {{
    background-color: {C_PRIMARY};
}}
QProgressBar {{
    background-color: {C_BG_INPUT};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: white;
    font-weight: 600;
    height: 8px;
}}
QProgressBar::chunk {{
    background-color: {C_PRIMARY};
    border-radius: 4px;
}}
QStatusBar {{
    background-color: {C_BG_CARD};
    color: {C_TEXT_DIM};
    border-top: 1px solid {C_BORDER};
}}
QMenuBar {{
    background-color: {C_BG_CARD};
    color: {C_TEXT};
    border-bottom: 1px solid {C_BORDER};
}}
QMenuBar::item:selected {{
    background-color: {C_PRIMARY};
}}
QMenu {{
    background-color: {C_BG_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
}}
QMenu::item:selected {{
    background-color: {C_PRIMARY};
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {C_BORDER};
}}
QCheckBox::indicator:checked {{
    background-color: {C_PRIMARY};
    border-color: {C_PRIMARY};
}}
QScrollBar:vertical {{
    background: {C_BG_DARK};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_PRIMARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""

# ── 辅助组件 ──────────────────────────────────────────────

class StatusCard(QFrame):
    def __init__(self, title, value="—", icon_text="", color=C_PRIMARY, parent=None):
        super().__init__(parent)
        self.setObjectName("statusCard")
        self.setStyleSheet(f"""
            #statusCard {{
                background-color: {C_BG_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 12px;
                padding: 16px;
                border-left: 4px solid {color};
            }}
        """)
        self.setMinimumWidth(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self.icon_label = QLabel(icon_text)
        self.icon_label.setStyleSheet(f"font-size: 24px; color: {color};")
        top.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px; font-weight: 500;")
        top.addWidget(self.title_label)
        top.addStretch()
        layout.addLayout(top)

        self.value_label = QLabel(str(value))
        self.value_label.setStyleSheet(f"color: {C_TEXT}; font-size: 26px; font-weight: 700;")
        layout.addWidget(self.value_label)

    def set_value(self, value, unit=""):
        self.value_label.setText(f"{value}{unit}")

    def set_color(self, color):
        self.setStyleSheet(f"""
            #statusCard {{
                background-color: {C_BG_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 12px;
                padding: 16px;
                border-left: 4px solid {color};
            }}
        """)
        self.icon_label.setStyleSheet(f"font-size: 24px; color: {color};")


class SectionTitle(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            font-size: 16px;
            font-weight: 700;
            color: {C_TEXT};
            padding: 4px 0;
            border-bottom: 2px solid {C_PRIMARY};
            margin-bottom: 8px;
        """)


class IconButton(QPushButton):
    def __init__(self, text, icon_text="", btn_type="default", parent=None):
        super().__init__(text, parent)
        self.setProperty("type", btn_type)
        if icon_text:
            self.setText(f"{icon_text}  {text}")
        if btn_type == "danger":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {C_DANGER};
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 22px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: #d63031; }}
                QPushButton:disabled {{ background-color: #2d3436; color: #636e72; }}
            """)
        elif btn_type == "success":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {C_SUCCESS};
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 22px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: #00a381; }}
                QPushButton:disabled {{ background-color: #2d3436; color: #636e72; }}
            """)
        elif btn_type == "outline":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {C_PRIMARY};
                    border: 2px solid {C_PRIMARY};
                    border-radius: 8px;
                    padding: 8px 20px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {C_PRIMARY};
                    color: white;
                }}
                QPushButton:disabled {{
                    border-color: #2d3436;
                    color: #636e72;
                }}
            """)


class LogSignal(QObject):
    new_log = pyqtSignal(str)


class ChatSignal(QObject):
    new_reply = pyqtSignal(str)


class ModelSignal(QObject):
    models_ready = pyqtSignal(object)
    fetch_error = pyqtSignal(str)


class ConfigSignal(QObject):
    config_requested = pyqtSignal()
    config_ready = pyqtSignal(object)


# ── 主窗口 ────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SandboxQQ")
        self.setMinimumSize(1200, 780)
        self.resize(1400, 860)
        self.setStyleSheet(STYLESHEET)

        self.sandbox = SandboxManager()
        self.bot_manager = BotManager()
        self.bot_instances: list[dict] = []
        self.ai_config = AIConfig()
        self._manual_url_edit = False
        self.chat_session: Optional[ChatSession] = None
        self._fetch_cancel: Optional[threading.Event] = None
        self._cached_ai_config: AIConfig = self.ai_config
        self._ai_config_lock = threading.Lock()
        self._config_event = threading.Event()
        self.config_signal = ConfigSignal()
        self.config_signal.config_requested.connect(self._on_config_requested)
        self.config_signal.config_ready.connect(self._on_config_ready)
        self._pending_config: Optional[AIConfig] = None
        self.log_signal = LogSignal()
        self.chat_signal = ChatSignal()
        self.model_signal = ModelSignal()

        self.event_bus = EventBus()
        self.provider_manager = ProviderManager()
        self._pipeline_initialized = False
        self._auth_enabled = False
        self._authorized_ids: list = []

        self._init_ui()
        self.chat_signal.new_reply.connect(self._on_chat_reply)
        self.model_signal.models_ready.connect(self._show_model_picker)
        self.model_signal.fetch_error.connect(self._on_fetch_error)

        self._connect_signals()
        self._load_configs()
        self._update_auth_cache()
        self._start_timers()
        self._init_pipeline()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_dashboard_tab()
        self._build_bot_tab()
        self._build_process_tab()
        self._build_files_tab()
        self._build_log_tab()
        self._build_ai_config_tab()
        self._build_ai_chat_tab()

        sb = QStatusBar()
        self.setStatusBar(sb)

        self.status_icon = QLabel("●")
        self.status_icon.setStyleSheet(f"color: {C_DANGER}; font-size: 14px; margin-right: 4px;")
        sb.addPermanentWidget(self.status_icon)

        self.status_text = QLabel("沙盒: 已停止  |  机器人: 未连接")
        self.status_text.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px;")
        sb.addPermanentWidget(self.status_text, 1)

        self.build_menu()

    # ═══════════════════════════════════════════════════════
    #  选项卡6: AI 配置
    # ═══════════════════════════════════════════════════════

    def _build_ai_config_tab(self):
        tab = QWidget()
        self.tabs.addTab(tab, "AI配置")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setSpacing(14)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("  AI 模型配置")
        header.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C_TEXT}; border-bottom: 2px solid {C_PRIMARY}; padding: 4px 0;")
        layout.addWidget(header)

        conn_box = QGroupBox("模型连接")
        form = QFormLayout(conn_box)
        form.setSpacing(10)

        prov_row = QHBoxLayout()
        self.ai_provider = QComboBox()
        self.ai_provider.setEditable(True)
        self.ai_provider.addItems(["openai", "deepseek", "google", "anthropic", "custom"])
        self.ai_provider.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 8px; min-width: 160px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        prov_row.addWidget(self.ai_provider)
        self.prov_btn_add = IconButton("＋", "", "outline")
        self.prov_btn_add.setFixedWidth(36)
        self.prov_btn_add.setToolTip("添加服务商")
        self.prov_btn_add.clicked.connect(self._add_provider)
        prov_row.addWidget(self.prov_btn_add)
        self.prov_btn_del = IconButton("－", "", "danger")
        self.prov_btn_del.setFixedWidth(36)
        self.prov_btn_del.setToolTip("删除服务商")
        self.prov_btn_del.clicked.connect(self._del_provider)
        prov_row.addWidget(self.prov_btn_del)
        prov_row.addStretch()
        form.addRow("提供商:", prov_row)
        self.ai_provider.currentTextChanged.connect(self._on_provider_changed)

        self.ai_api_key = QLineEdit()
        self.ai_api_key.setPlaceholderText("sk-...")
        self.ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self.ai_api_key)

        self.ai_api_url = QLineEdit("https://api.openai.com/v1")
        self.ai_api_url.textChanged.connect(lambda: setattr(self, '_manual_url_edit', True))
        form.addRow("API 地址:", self.ai_api_url)

        model_row = QHBoxLayout()
        self.ai_model = QLineEdit("gpt-4o")
        self.ai_model.setPlaceholderText("gpt-4o / deepseek-chat / ...")
        model_row.addWidget(self.ai_model)
        self.ai_btn_fetch_models = IconButton("获取模型列表", "🔄", "outline")
        self.ai_btn_fetch_models.clicked.connect(self._fetch_models)
        model_row.addWidget(self.ai_btn_fetch_models)
        form.addRow("模型名:", model_row)

        row1 = QHBoxLayout()
        self.ai_temp = QSpinBox()
        self.ai_temp.setRange(0, 200)
        self.ai_temp.setValue(70)
        self.ai_temp.setSuffix("%")
        row1.addWidget(QLabel("温度:"))
        row1.addWidget(self.ai_temp)
        self.ai_max_tokens = QSpinBox()
        self.ai_max_tokens.setRange(256, 128000)
        self.ai_max_tokens.setValue(4096)
        self.ai_max_tokens.setSingleStep(1024)
        row1.addWidget(QLabel("Max Tokens:"))
        row1.addWidget(self.ai_max_tokens)
        row1.addStretch()
        form.addRow("参数:", row1)

        layout.addWidget(conn_box)

        prompt_box = QGroupBox("系统提示词")
        prompt_layout = QVBoxLayout(prompt_box)
        self.ai_system_prompt = QTextEdit()
        self.ai_system_prompt.setPlainText(self.ai_config.system_prompt)
        self.ai_system_prompt.setMaximumHeight(100)
        prompt_layout.addWidget(self.ai_system_prompt)
        layout.addWidget(prompt_box)

        ctx_box = QGroupBox("上下文管理")
        ctx_form = QFormLayout(ctx_box)
        self.ai_context_mode = QComboBox()
        modes = [("截断", "truncation"), ("压缩", "compression"), ("完整", "full")]
        for label, val in modes:
            self.ai_context_mode.addItem(label, val)
        self.ai_context_mode.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 8px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        ctx_form.addRow("模式:", self.ai_context_mode)
        self.ai_ctx_window = QSpinBox()
        self.ai_ctx_window.setRange(4096, 128000)
        self.ai_ctx_window.setValue(32000)
        self.ai_ctx_window.setSingleStep(1024)
        ctx_form.addRow("窗口大小:", self.ai_ctx_window)
        layout.addWidget(ctx_box)

        think_box = QGroupBox("深度思考")
        think_form = QFormLayout(think_box)
        self.ai_enable_thinking = QCheckBox("启用深度思考 (先推理再回答)")
        think_form.addRow(self.ai_enable_thinking)
        self.ai_think_model = QLineEdit()
        self.ai_think_model.setPlaceholderText("如: o1-mini / deepseek-reasoner")
        think_form.addRow("思考模型:", self.ai_think_model)
        self.ai_think_budget = QSpinBox()
        self.ai_think_budget.setRange(256, 32768)
        self.ai_think_budget.setValue(2048)
        self.ai_think_budget.setSingleStep(256)
        think_form.addRow("思考预算(tokens):", self.ai_think_budget)
        layout.addWidget(think_box)

        search_box = QGroupBox("网络搜索")
        search_form = QFormLayout(search_box)
        self.ai_enable_search = QCheckBox("启用网络搜索能力")
        search_form.addRow(self.ai_enable_search)
        self.ai_search_provider = QComboBox()
        self.ai_search_provider.addItems(["duckduckgo"])
        self.ai_search_provider.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 8px; }}")
        search_form.addRow("搜索源:", self.ai_search_provider)
        layout.addWidget(search_box)

        vision_box = QGroupBox("图片识别 (Vision)")
        vision_form = QFormLayout(vision_box)
        self.ai_vision_model = QLineEdit()
        self.ai_vision_model.setPlaceholderText("留空使用主模型")
        vision_form.addRow("识图模型:", self.ai_vision_model)
        self.ai_vision_api_url = QLineEdit()
        self.ai_vision_api_url.setPlaceholderText("留空使用主API地址")
        vision_form.addRow("识图API:", self.ai_vision_api_url)
        self.ai_vision_api_key = QLineEdit()
        self.ai_vision_api_key.setPlaceholderText("留空使用主API Key")
        self.ai_vision_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        vision_form.addRow("识图Key:", self.ai_vision_api_key)
        layout.addWidget(vision_box)

        genimg_box = QGroupBox("图片生成")
        genimg_form = QFormLayout(genimg_box)
        self.ai_img_model = QLineEdit()
        self.ai_img_model.setPlaceholderText("如: dall-e-3")
        genimg_form.addRow("生图模型:", self.ai_img_model)
        self.ai_img_api_url = QLineEdit("https://api.openai.com/v1")
        genimg_form.addRow("生图API:", self.ai_img_api_url)
        self.ai_img_api_key = QLineEdit()
        self.ai_img_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        genimg_form.addRow("生图Key:", self.ai_img_api_key)
        layout.addWidget(genimg_box)

        genvid_box = QGroupBox("视频生成")
        genvid_form = QFormLayout(genvid_box)
        self.ai_vid_model = QLineEdit()
        self.ai_vid_model.setPlaceholderText("模型名")
        genvid_form.addRow("视频模型:", self.ai_vid_model)
        self.ai_vid_api_url = QLineEdit()
        genvid_form.addRow("视频API:", self.ai_vid_api_url)
        self.ai_vid_api_key = QLineEdit()
        self.ai_vid_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        genvid_form.addRow("视频Key:", self.ai_vid_api_key)
        layout.addWidget(genvid_box)

        perm_box = QGroupBox("沙盒权限 (逐工具控制)")
        perm_grid = QGridLayout(perm_box)
        self.perm_cb = {}
        tools_list = [
            ("execute_python", "Python代码执行", True),
            ("read_file", "读取文件", True),
            ("write_file", "写入文件", True),
            ("list_files", "列出目录", True),
            ("run_shell", "Shell命令", False),
        ]
        for i, (key, label, default) in enumerate(tools_list):
            cb = QCheckBox(label)
            cb.setChecked(default)
            self.perm_cb[key] = cb
            perm_grid.addWidget(cb, i // 2, i % 2)
        layout.addWidget(perm_box)

        tool_box = QGroupBox("工具选项")
        tool_layout = QVBoxLayout(tool_box)
        self.ai_enable_tools = QCheckBox("启用工具调用 (AI 可使用沙盒工具)")
        self.ai_enable_tools.setChecked(True)
        tool_layout.addWidget(self.ai_enable_tools)
        self.ai_max_rounds = QSpinBox()
        self.ai_max_rounds.setRange(1, 200)
        self.ai_max_rounds.setValue(50)
        rl = QHBoxLayout(); rl.addWidget(QLabel("最大工具轮次:"))
        rl.addWidget(self.ai_max_rounds); rl.addStretch()
        tool_layout.addLayout(rl)
        layout.addWidget(tool_box)

        skills_box = QGroupBox("Skills / 专业技能")
        skills_layout = QVBoxLayout(skills_box)
        self.skills_list = QListWidget()
        self.skills_list.setMaximumHeight(120)
        self.skills_list.setStyleSheet(f"QListWidget {{ background: {C_BG_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; }}")
        skills_layout.addWidget(self.skills_list)
        sk_btn_row = QHBoxLayout()
        self.skills_btn_add = IconButton("添加", "＋", "outline")
        self.skills_btn_add.clicked.connect(self._add_skill_dialog)
        self.skills_btn_del = IconButton("删除", "－", "danger")
        self.skills_btn_del.clicked.connect(self._del_skill)
        sk_btn_row.addWidget(self.skills_btn_add)
        sk_btn_row.addWidget(self.skills_btn_del)
        sk_btn_row.addStretch()
        skills_layout.addLayout(sk_btn_row)
        layout.addWidget(skills_box)

        plugins_box = QGroupBox("插件管理")
        plugins_layout = QVBoxLayout(plugins_box)
        self.plugins_list = QListWidget()
        self.plugins_list.setMaximumHeight(100)
        self.plugins_list.setStyleSheet(f"QListWidget {{ background: {C_BG_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; }}")
        plugins_layout.addWidget(self.plugins_list)
        pl_btn_row = QHBoxLayout()
        self.plugins_btn_add = IconButton("添加插件", "＋", "outline")
        self.plugins_btn_add.clicked.connect(self._add_plugin_dialog)
        self.plugins_btn_del = IconButton("删除", "－", "danger")
        self.plugins_btn_del.clicked.connect(self._del_plugin)
        pl_btn_row.addWidget(self.plugins_btn_add)
        pl_btn_row.addWidget(self.plugins_btn_del)
        pl_btn_row.addStretch()
        plugins_layout.addLayout(pl_btn_row)
        layout.addWidget(plugins_box)

        sub_box = QGroupBox("子Agent")
        sub_layout = QVBoxLayout(sub_box)
        self.sub_list = QListWidget()
        self.sub_list.setMaximumHeight(100)
        self.sub_list.setStyleSheet(f"QListWidget {{ background: {C_BG_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; }}")
        sub_layout.addWidget(self.sub_list)
        sub_btn_row = QHBoxLayout()
        self.sub_btn_add = IconButton("添加", "＋", "outline")
        self.sub_btn_add.clicked.connect(self._add_sub_agent_dialog)
        self.sub_btn_del = IconButton("删除", "－", "danger")
        self.sub_btn_del.clicked.connect(self._del_sub_agent)
        sub_btn_row.addWidget(self.sub_btn_add)
        sub_btn_row.addWidget(self.sub_btn_del)
        sub_btn_row.addStretch()
        sub_layout.addLayout(sub_btn_row)
        layout.addWidget(sub_box)

        prov_box = QGroupBox("多模型供应商")
        prov_layout = QVBoxLayout(prov_box)
        self.providers_list = QListWidget()
        self.providers_list.setMaximumHeight(120)
        self.providers_list.setStyleSheet(f"QListWidget {{ background: {C_BG_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; }}")
        prov_layout.addWidget(self.providers_list)
        prov_btn_row = QHBoxLayout()
        self.prov_btn_add = IconButton("添加供应商", "＋", "outline")
        self.prov_btn_add.clicked.connect(self._add_provider_dialog)
        self.prov_btn_del = IconButton("删除", "－", "danger")
        self.prov_btn_del.clicked.connect(self._del_provider_cfg)
        prov_btn_row.addWidget(self.prov_btn_add)
        prov_btn_row.addWidget(self.prov_btn_del)
        prov_btn_row.addStretch()
        prov_layout.addLayout(prov_btn_row)
        layout.addWidget(prov_box)

        plugin_box = QGroupBox("插件管理")
        plugin_layout = QVBoxLayout(plugin_box)
        self.plugin_list_display = QListWidget()
        self.plugin_list_display.setMaximumHeight(120)
        self.plugin_list_display.setStyleSheet(f"QListWidget {{ background: {C_BG_CARD}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; }}")
        self.plugin_list_display.itemDoubleClicked.connect(self._open_plugin_settings)
        plugin_layout.addWidget(self.plugin_list_display)
        plugin_btn_row = QHBoxLayout()
        plugin_refresh_btn = IconButton("刷新", "🔄", "outline")
        plugin_refresh_btn.clicked.connect(self._refresh_plugin_list)
        plugin_btn_row.addWidget(plugin_refresh_btn)
        plugin_new_btn = IconButton("新建插件", "＋", "outline")
        plugin_new_btn.clicked.connect(self._new_plugin)
        plugin_btn_row.addWidget(plugin_new_btn)
        plugin_set_btn = IconButton("设置", "⚙", "outline")
        plugin_set_btn.clicked.connect(self._open_plugin_settings)
        plugin_btn_row.addWidget(plugin_set_btn)
        plugin_open_btn = IconButton("打开目录", "📂", "outline")
        plugin_open_btn.clicked.connect(self._open_plugin_folder)
        plugin_btn_row.addWidget(plugin_open_btn)
        plugin_btn_row.addStretch()
        plugin_layout.addLayout(plugin_btn_row)
        layout.addWidget(plugin_box)

        btn_row = QHBoxLayout()
        self.ai_btn_save = IconButton("保存配置", "💾")
        self.ai_btn_save.clicked.connect(self._save_ai_config)
        btn_row.addWidget(self.ai_btn_save)
        self.ai_btn_test = IconButton("测试连接", "🔍", "outline")
        self.ai_btn_test.clicked.connect(self._test_ai_connection)
        btn_row.addWidget(self.ai_btn_test)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.ai_test_result = QLabel("")
        self.ai_test_result.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px; padding: 4px;")
        layout.addWidget(self.ai_test_result)
        layout.addStretch()

        tab.setLayout(QVBoxLayout())
        tab.layout().setContentsMargins(0, 0, 0, 0)
        tab.layout().addWidget(scroll)

    # ═══════════════════════════════════════════════════════
    #  选项卡7: AI 对话
    # ═══════════════════════════════════════════════════════

    def _build_ai_chat_tab(self):
        self.chat_tab = QWidget()
        self.tabs.addTab(self.chat_tab, "AI对话")

        layout = QVBoxLayout(self.chat_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_bar = QWidget()
        header_bar.setStyleSheet(f"background: {C_BG_CARD}; border-bottom: 1px solid {C_BORDER};")
        hbar = QHBoxLayout(header_bar)
        hbar.setContentsMargins(12, 6, 12, 6)

        self.chat_status = QLabel("● AI 未就绪")
        self.chat_status.setStyleSheet(f"color: {C_DANGER}; font-weight: 600; font-size: 13px;")
        hbar.addWidget(self.chat_status)
        hbar.addStretch()

        self.chat_provider = QComboBox()
        self.chat_provider.addItem("默认")
        self.chat_provider.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px 12px; min-width: 120px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        hbar.addWidget(QLabel("模型:"))
        hbar.addWidget(self.chat_provider)

        self.chat_sub_agent = QComboBox()
        self.chat_sub_agent.addItem("主Agent")
        self.chat_sub_agent.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px 12px; min-width: 140px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        hbar.addWidget(QLabel("目标:"))
        hbar.addWidget(self.chat_sub_agent)

        self.chat_btn_clear = IconButton("清空对话", "🗑", "outline")
        self.chat_btn_clear.clicked.connect(self._clear_chat)
        hbar.addWidget(self.chat_btn_clear)

        layout.addWidget(header_bar)

        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        self.chat_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.chat_container = QWidget()
        self.chat_container.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch()

        self.chat_area.setWidget(self.chat_container)
        layout.addWidget(self.chat_area, 1)

        input_bar = QWidget()
        input_bar.setStyleSheet(f"background: {C_BG_CARD}; border-top: 1px solid {C_BORDER};")
        inp_layout = QHBoxLayout(input_bar)
        inp_layout.setContentsMargins(12, 10, 12, 10)

        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("输入消息，AI 将使用沙盒工具处理你的任务...")
        self.chat_input.setMaximumHeight(80)
        self.chat_input.setStyleSheet(f"""
            QTextEdit {{
                background: {C_BG_INPUT};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 14px;
            }}
            QTextEdit:focus {{ border-color: {C_PRIMARY}; }}
        """)
        inp_layout.addWidget(self.chat_input, 1)

        self.chat_btn_send = QPushButton("发送")
        self.chat_btn_send.setStyleSheet(f"""
            QPushButton {{
                background: {C_PRIMARY}; color: white; border: none;
                border-radius: 10px; padding: 10px 28px; font-weight: 700; font-size: 14px;
            }}
            QPushButton:hover {{ background: {C_PRIMARY_DARK}; }}
            QPushButton:disabled {{ background: #2d3436; color: #636e72; }}
        """)
        self.chat_btn_send.clicked.connect(self._send_chat_message)
        inp_layout.addWidget(self.chat_btn_send)

        layout.addWidget(input_bar)

    def build_menu(self):
        mb = self.menuBar()
        mb.setStyleSheet(f"""
            QMenuBar {{
                background-color: {C_BG_CARD};
                color: {C_TEXT};
                border-bottom: 1px solid {C_BORDER};
                padding: 2px;
            }}
            QMenuBar::item {{ padding: 6px 16px; border-radius: 4px; }}
            QMenuBar::item:selected {{ background-color: {C_PRIMARY}; }}
            QMenu {{
                background-color: {C_BG_CARD};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{ padding: 8px 32px 8px 16px; border-radius: 4px; }}
            QMenu::item:selected {{ background-color: {C_PRIMARY}; }}
            QMenu::separator {{ height: 1px; background: {C_BORDER}; margin: 4px 8px; }}
        """)

        fm = mb.addMenu("文件")
        a_save = QAction("保存配置", self)
        a_save.triggered.connect(self._save_configs)
        fm.addAction(a_save)
        a_load = QAction("加载配置", self)
        a_load.triggered.connect(self._load_configs)
        fm.addAction(a_load)
        fm.addSeparator()
        a_exit = QAction("退出", self)
        a_exit.triggered.connect(self.close)
        fm.addAction(a_exit)

        vm = mb.addMenu("视图")
        a_dash = QAction("仪表盘", self)
        a_dash.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        vm.addAction(a_dash)
        a_bot = QAction("QQBot配置", self)
        a_bot.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        vm.addAction(a_bot)
        a_proc = QAction("进程监控", self)
        a_proc.triggered.connect(lambda: self.tabs.setCurrentIndex(2))
        vm.addAction(a_proc)
        a_files = QAction("文件浏览器", self)
        a_files.triggered.connect(lambda: self.tabs.setCurrentIndex(3))
        vm.addAction(a_files)
        a_log = QAction("日志", self)
        a_log.triggered.connect(lambda: self.tabs.setCurrentIndex(4))
        vm.addAction(a_log)
        vm.addSeparator()
        a_ai_cfg = QAction("AI 配置", self)
        a_ai_cfg.triggered.connect(lambda: self.tabs.setCurrentIndex(5))
        vm.addAction(a_ai_cfg)
        a_ai_chat = QAction("AI 对话", self)
        a_ai_chat.triggered.connect(lambda: self.tabs.setCurrentIndex(6))
        vm.addAction(a_ai_chat)

        hm = mb.addMenu("帮助")
        a_about = QAction("关于 SandboxQQ", self)
        a_about.triggered.connect(self._show_about)
        hm.addAction(a_about)

    # ═══════════════════════════════════════════════════════
    #  选项卡1: 仪表盘
    # ═══════════════════════════════════════════════════════

    def _build_dashboard_tab(self):
        tab = self.tabs.findChild(QWidget, "dashboardTab")
        if not tab:
            tab = QWidget()
            tab.setObjectName("dashboardTab")
            self.tabs.insertTab(0, tab, "仪表盘")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setSpacing(16)
        layout.setContentsMargins(8, 8, 8, 8)

        # 标题
        header = QLabel("  SandboxQQ 仪表盘")
        header.setStyleSheet(f"""
            font-size: 22px;
            font-weight: 700;
            color: {C_TEXT};
            padding: 8px 0;
            border-bottom: 2px solid {C_PRIMARY};
        """)
        layout.addWidget(header)

        # 状态卡片行
        card_row = QHBoxLayout()
        card_row.setSpacing(12)

        self.card_state = StatusCard("沙盒状态", "已停止", "■", C_DANGER)
        self.card_state.setMinimumWidth(160)
        card_row.addWidget(self.card_state)

        self.card_uptime = StatusCard("运行时间", "00:00:00", "⏱", C_INFO)
        card_row.addWidget(self.card_uptime)

        self.card_processes = StatusCard("活动进程", "0", "⚙", C_PRIMARY)
        card_row.addWidget(self.card_processes)

        self.card_memory = StatusCard("内存使用", "0 MB", "💾", C_WARNING)
        card_row.addWidget(self.card_memory)

        self.card_bot = StatusCard("机器人状态", "未连接", "🤖", C_DANGER)
        card_row.addWidget(self.card_bot)

        layout.addLayout(card_row)

        # 沙盒控制区
        ctrl_box = QGroupBox("沙盒控制")
        ctrl_grid = QGridLayout(ctrl_box)
        ctrl_grid.setSpacing(12)

        ctrl_grid.addWidget(QLabel("沙盒根目录:"), 0, 0)
        self.dash_root_edit = QLineEdit()
        self.dash_root_edit.setPlaceholderText("选择一个文件夹作为沙盒根目录...")
        self.dash_root_edit.setReadOnly(True)
        ctrl_grid.addWidget(self.dash_root_edit, 0, 1)

        self.dash_btn_select = IconButton("浏览...", "📁", "outline")
        self.dash_btn_select.clicked.connect(self._select_sandbox_dir)
        ctrl_grid.addWidget(self.dash_btn_select, 0, 2)

        ctrl_grid.addWidget(QLabel("最大进程数:"), 1, 0)
        self.dash_spin_procs = QSpinBox()
        self.dash_spin_procs.setRange(1, 999)
        self.dash_spin_procs.setValue(10)
        self.dash_spin_procs.setStyleSheet(f"""
            QSpinBox {{
                background-color: {C_BG_INPUT};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        ctrl_grid.addWidget(self.dash_spin_procs, 1, 1)

        ctrl_grid.addWidget(QLabel("内存限制 (MB):"), 2, 0)
        self.dash_spin_mem = QSpinBox()
        self.dash_spin_mem.setRange(64, 32768)
        self.dash_spin_mem.setValue(512)
        self.dash_spin_mem.setSingleStep(64)
        self.dash_spin_mem.setStyleSheet(self.dash_spin_procs.styleSheet())
        ctrl_grid.addWidget(self.dash_spin_mem, 2, 1)

        btn_row = QHBoxLayout()
        self.dash_btn_start = IconButton("启动沙盒", "▶", "success")
        self.dash_btn_start.clicked.connect(self._start_sandbox)
        btn_row.addWidget(self.dash_btn_start)

        self.dash_btn_stop = IconButton("停止沙盒", "⏹", "danger")
        self.dash_btn_stop.clicked.connect(self._stop_sandbox)
        self.dash_btn_stop.setEnabled(False)
        btn_row.addWidget(self.dash_btn_stop)

        self.dash_btn_restart = IconButton("重启沙盒", "🔄", "outline")
        self.dash_btn_restart.clicked.connect(self._restart_sandbox)
        self.dash_btn_restart.setEnabled(False)
        btn_row.addWidget(self.dash_btn_restart)

        btn_row.addStretch()
        self.dash_btn_save = IconButton("保存配置", "💾", "success")
        self.dash_btn_save.clicked.connect(self._save_configs)
        btn_row.addWidget(self.dash_btn_save)
        ctrl_grid.addLayout(btn_row, 3, 0, 1, 3)

        layout.addWidget(ctrl_box)

        # 隔离配置
        isolation_box = QGroupBox("隔离选项")
        iso_layout = QGridLayout(isolation_box)
        iso_layout.setSpacing(8)

        self.chk_file_iso = QCheckBox("文件系统隔离")
        self.chk_file_iso.setChecked(True)
        self.chk_file_iso.setStyleSheet(f"color: {C_TEXT};")
        iso_layout.addWidget(self.chk_file_iso, 0, 0)

        self.chk_net_iso = QCheckBox("网络隔离")
        self.chk_net_iso.setChecked(True)
        iso_layout.addWidget(self.chk_net_iso, 0, 1)

        self.chk_proc_iso = QCheckBox("进程隔离 (AppContainer)")
        self.chk_proc_iso.setChecked(True)
        self.chk_proc_iso.stateChanged.connect(lambda s: self.chk_proc_iso.setChecked(True) if s == 0 else None)
        iso_layout.addWidget(self.chk_proc_iso, 0, 2)

        layout.addWidget(isolation_box)

        # 文件操作统计
        stats_box = QGroupBox("沙盒统计")
        stats_grid = QGridLayout(stats_box)

        self.stat_file_blocked = StatusCard("文件操作拦截", "0 次", "🛑", C_DANGER)
        self.stat_file_blocked.setMinimumWidth(0)
        stats_grid.addWidget(self.stat_file_blocked, 0, 0)

        self.stat_net_blocked = StatusCard("网络连接拦截", "0 次", "🚫", C_DANGER)
        self.stat_net_blocked.setMinimumWidth(0)
        stats_grid.addWidget(self.stat_net_blocked, 0, 1)

        layout.addWidget(stats_box)
        layout.addStretch()

        # Replace the dashboard tab
        old_idx = 0
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).objectName() == "dashboardTab":
                old_idx = i
                break
        self.tabs.removeTab(old_idx)
        self.tabs.insertTab(0, scroll, "仪表盘")

    # ═══════════════════════════════════════════════════════
    #  选项卡2: 机器人配置
    # ═══════════════════════════════════════════════════════

    def _build_bot_tab(self):
        tab = QWidget()
        tab.setObjectName("botTab")
        self.tabs.addTab(tab, "🤖 QQBot")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setSpacing(16)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("  QQ 机器人连接配置")
        header.setStyleSheet(f"""
            font-size: 20px; font-weight: 700;
            color: {C_TEXT}; padding: 8px 0;
            border-bottom: 2px solid {C_PRIMARY};
        """)
        layout.addWidget(header)

        # 多机器人实例管理
        instance_box = QGroupBox("机器人实例")
        instance_layout = QVBoxLayout(instance_box)

        instance_top = QHBoxLayout()
        instance_top.addWidget(QLabel("同时运行多个 QQ 机器人："))
        instance_top.addStretch()
        self.bot_add_btn = IconButton("＋ 添加机器人", "➕", "outline")
        self.bot_add_btn.clicked.connect(self._add_bot_instance)
        instance_top.addWidget(self.bot_add_btn)
        self.bot_del_btn = IconButton("删除选中", "🗑", "danger")
        self.bot_del_btn.clicked.connect(self._del_bot_instance)
        instance_top.addWidget(self.bot_del_btn)
        self.bot_start_all_btn = IconButton("全部启动", "▶", "success")
        self.bot_start_all_btn.clicked.connect(self._start_all_bots)
        instance_top.addWidget(self.bot_start_all_btn)
        self.bot_stop_all_btn = IconButton("全部停止", "⏹", "danger")
        self.bot_stop_all_btn.clicked.connect(self._stop_all_bots)
        instance_top.addWidget(self.bot_stop_all_btn)
        instance_layout.addLayout(instance_top)

        self.bot_table = QTableWidget(0, 4)
        self.bot_table.setHorizontalHeaderLabels(["名称", "AppID", "状态", "操作"])
        self.bot_table.horizontalHeader().setStretchLastSection(False)
        self.bot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.bot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.bot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.bot_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.bot_table.verticalHeader().setVisible(False)
        self.bot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bot_table.setMinimumHeight(120)
        self.bot_table.setMaximumHeight(200)
        self.bot_table.setStyleSheet(f"""
            QTableWidget {{ background: {C_BG_INPUT}; border: 1px solid {C_BORDER}; border-radius: 6px; color: {C_TEXT}; }}
            QTableWidget::item {{ padding: 4px; }}
            QHeaderView::section {{ background: {C_BG_DARK}; color: {C_TEXT}; border: 1px solid {C_BORDER}; padding: 4px; }}
        """)
        self.bot_table.itemSelectionChanged.connect(self._on_bot_selection_changed)
        instance_layout.addWidget(self.bot_table)

        layout.addWidget(instance_box)

        # QQ官方协议
        official_box = QGroupBox("编辑选中机器人")
        off_form = QFormLayout(official_box)
        off_form.setSpacing(8)
        off_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.bot_name = QLineEdit()
        self.bot_name.setPlaceholderText("给机器人起个名字")
        off_form.addRow("名称:", self.bot_name)

        proto_row = QHBoxLayout()
        self.bot_proto_combo = QComboBox()
        self.bot_proto_combo.addItems(["QQ官方机器人", "OneBot 协议"])
        self.bot_proto_combo.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px 10px; min-width: 140px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        proto_row.addWidget(self.bot_proto_combo)
        self.bot_use_sandbox = QCheckBox("沙箱环境")
        self.bot_use_sandbox.setStyleSheet(f"color: {C_TEXT};")
        proto_row.addWidget(self.bot_use_sandbox)
        proto_row.addStretch()
        off_form.addRow("协议:", proto_row)

        self.bot_appid = QLineEdit()
        self.bot_appid.setPlaceholderText("Bot AppID")
        off_form.addRow("AppID:", self.bot_appid)

        self.bot_appsecret = QLineEdit()
        self.bot_appsecret.setPlaceholderText("AppSecret")
        self.bot_appsecret.setEchoMode(QLineEdit.EchoMode.Password)
        off_form.addRow("AppSecret:", self.bot_appsecret)

        self.bot_token = QLineEdit()
        self.bot_token.setPlaceholderText("Bot Token (旧, 留空)")
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        off_form.addRow("Token(旧):", self.bot_token)

        self.bot_ws_url = QLineEdit("wss://api.sgroup.qq.com/websocket")
        off_form.addRow("WebSocket:", self.bot_ws_url)

        self.bot_api_url = QLineEdit("https://api.sgroup.qq.com")
        off_form.addRow("API 地址:", self.bot_api_url)

        self.bot_sandbox_api_url = QLineEdit("https://sandbox.api.sgroup.qq.com")
        off_form.addRow("沙箱API:", self.bot_sandbox_api_url)

        # OneBot fields
        self.bot_onebot_ws = QLineEdit("ws://127.0.0.1:8080")
        off_form.addRow("OneBot WS:", self.bot_onebot_ws)

        self.bot_onebot_http = QLineEdit("http://127.0.0.1:8080")
        off_form.addRow("OneBot HTTP:", self.bot_onebot_http)

        save_btn = IconButton("💾 保存更改", "💾", "primary")
        save_btn.clicked.connect(self._save_bot_instance)
        off_form.addRow("", save_btn)

        layout.addWidget(official_box)

        # AI 覆盖配置（每个机器人可独立配置）
        ai_box = QGroupBox("AI 覆盖配置（留空则使用全局 AI 设置）")
        ai_form = QFormLayout(ai_box)
        ai_form.setSpacing(8)
        ai_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.bot_ai_provider = QComboBox()
        self.bot_ai_provider.addItem("（使用全局默认）", "")
        self.bot_ai_provider.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px 10px; min-width: 140px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        ai_form.addRow("AI 提供者:", self.bot_ai_provider)

        self.bot_ai_model = QLineEdit()
        self.bot_ai_model.setPlaceholderText("留空则使用提供者默认模型")
        ai_form.addRow("模型:", self.bot_ai_model)

        self.bot_ai_system_prompt = QTextEdit()
        self.bot_ai_system_prompt.setPlaceholderText("留空则使用全局系统提示词")
        self.bot_ai_system_prompt.setMaximumHeight(100)
        self.bot_ai_system_prompt.setStyleSheet(f"background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px;")
        ai_form.addRow("系统提示词:", self.bot_ai_system_prompt)

        self.bot_ai_enable_tools = QCheckBox("启用工具调用")
        self.bot_ai_enable_tools.setTristate(True)
        self.bot_ai_enable_tools.setCheckState(Qt.CheckState.PartiallyChecked)
        self.bot_ai_enable_tools.setToolTip("半选=继承全局设置，勾选=强制启用工具，不勾选=强制禁用工具")
        self.bot_ai_enable_tools.setStyleSheet(f"color: {C_TEXT};")
        ai_form.addRow("", self.bot_ai_enable_tools)

        layout.addWidget(ai_box)

        # 用户权限管理
        auth_box = QGroupBox("用户权限管理")
        auth_layout = QVBoxLayout(auth_box)
        self.auth_enabled_cb = QCheckBox("启用用户权限验证（未授权的用户无法使用沙盒功能）")
        self.auth_enabled_cb.setStyleSheet(f"color: {C_TEXT}; font-size: 13px;")
        self.auth_enabled_cb.stateChanged.connect(self._update_auth_cache)
        auth_layout.addWidget(self.auth_enabled_cb)

        id_row = QHBoxLayout()
        self.auth_user_list = QListWidget()
        self.auth_user_list.setMaximumHeight(120)
        self.auth_user_list.setStyleSheet(f"""
            QListWidget {{ background: {C_BG_INPUT}; border: 1px solid {C_BORDER};
                border-radius: 6px; color: {C_TEXT}; }}
        """)
        id_row.addWidget(self.auth_user_list)

        id_btn_col = QVBoxLayout()
        self.auth_btn_add = IconButton("添加用户", "➕", "outline")
        self.auth_btn_add.clicked.connect(self._add_auth_user)
        id_btn_col.addWidget(self.auth_btn_add)
        self.auth_btn_remove = IconButton("移除选中", "➖", "outline")
        self.auth_btn_remove.clicked.connect(self._remove_auth_user)
        id_btn_col.addWidget(self.auth_btn_remove)
        id_btn_col.addStretch()
        id_row.addLayout(id_btn_col)
        auth_layout.addLayout(id_row)
        layout.addWidget(auth_box)

        # 消息测试
        test_box = QGroupBox("消息发送测试")
        test_form = QFormLayout(test_box)
        self.bot_test_channel = QLineEdit()
        self.bot_test_channel.setPlaceholderText("频道ID / 群号")
        test_form.addRow("目标ID:", self.bot_test_channel)
        self.bot_test_msg = QLineEdit()
        self.bot_test_msg.setPlaceholderText("输入文字消息...")
        test_form.addRow("文字内容:", self.bot_test_msg)

        send_row = QHBoxLayout()
        self.bot_btn_test = IconButton("发送文字", "📨")
        self.bot_btn_test.clicked.connect(lambda: self._bot_send("text"))
        send_row.addWidget(self.bot_btn_test)

        self.bot_btn_img = IconButton("发送图片", "🖼", "outline")
        self.bot_btn_img.clicked.connect(lambda: self._bot_send("image"))
        send_row.addWidget(self.bot_btn_img)

        self.bot_btn_file = IconButton("发送文件", "📎", "outline")
        self.bot_btn_file.clicked.connect(lambda: self._bot_send("file"))
        send_row.addWidget(self.bot_btn_file)

        self.bot_btn_video = IconButton("发送视频", "🎬", "outline")
        self.bot_btn_video.clicked.connect(lambda: self._bot_send("video"))
        send_row.addWidget(self.bot_btn_video)

        send_row.addStretch()
        test_form.addRow("发送:", send_row)

        layout.addWidget(test_box)
        layout.addStretch()

        tab.setLayout(QVBoxLayout())
        tab.layout().setContentsMargins(0, 0, 0, 0)
        tab.layout().addWidget(scroll)

    # ═══════════════════════════════════════════════════════
    #  选项卡3: 进程监控
    # ═══════════════════════════════════════════════════════

    def _build_process_tab(self):
        tab = QWidget()
        tab.setObjectName("procTab")
        self.tabs.addTab(tab, "⚙ 进程")

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel("  沙盒进程监控")
        header.setStyleSheet(f"""
            font-size: 18px; font-weight: 700;
            color: {C_TEXT}; padding: 4px 0;
            border-bottom: 2px solid {C_PRIMARY};
        """)
        layout.addWidget(header)

        self.proc_table = QTableWidget()
        self.proc_table.setColumnCount(5)
        self.proc_table.setHorizontalHeaderLabels(["PID", "进程名", "命令行", "状态", "操作"])
        self.proc_table.horizontalHeader().setStretchLastSection(True)
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.proc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.proc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.proc_table.setAlternatingRowColors(True)
        self.proc_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {C_BG_CARD};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                alternate-background-color: #1a2744;
            }}
        """)
        layout.addWidget(self.proc_table)

        btn_row = QHBoxLayout()
        self.proc_btn_refresh = IconButton("刷新", "🔄", "outline")
        self.proc_btn_refresh.clicked.connect(self._refresh_processes)
        btn_row.addWidget(self.proc_btn_refresh)

        self.proc_btn_kill = IconButton("终止选中", "✕", "danger")
        self.proc_btn_kill.clicked.connect(self._kill_selected_process)
        btn_row.addWidget(self.proc_btn_kill)

        self.proc_btn_killall = IconButton("终止全部", "✕✕", "danger")
        self.proc_btn_killall.clicked.connect(self._kill_all_processes)
        btn_row.addWidget(self.proc_btn_killall)

        self.proc_count_label = QLabel("进程数: 0")
        self.proc_count_label.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 13px;")
        btn_row.addWidget(self.proc_count_label)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ═══════════════════════════════════════════════════════
    #  选项卡4: 文件浏览器
    # ═══════════════════════════════════════════════════════

    def _build_files_tab(self):
        tab = QWidget()
        tab.setObjectName("filesTab")
        self.tabs.addTab(tab, "📁 文件")

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel("  沙盒文件浏览器")
        header.setStyleSheet(f"""
            font-size: 18px; font-weight: 700;
            color: {C_TEXT}; padding: 4px 0;
            border-bottom: 2px solid {C_PRIMARY};
        """)
        layout.addWidget(header)

        path_row = QHBoxLayout()
        self.files_path_label = QLabel("沙盒根目录: 未设置")
        self.files_path_label.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 13px;")
        path_row.addWidget(self.files_path_label)
        path_row.addStretch()

        self.files_btn_goto = IconButton("打开沙盒目录", "📂", "outline")
        self.files_btn_goto.clicked.connect(self._open_sandbox_folder)
        path_row.addWidget(self.files_btn_goto)

        self.files_btn_refresh = IconButton("刷新", "🔄", "outline")
        self.files_btn_refresh.clicked.connect(self._refresh_files)
        path_row.addWidget(self.files_btn_refresh)
        layout.addLayout(path_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 树形视图
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 4, 0)
        tree_layout.addWidget(QLabel("目录树"))
        self.files_tree = QTreeView()
        self.files_tree.setStyleSheet(f"""
            QTreeView {{
                background-color: {C_BG_CARD};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
            }}
            QTreeView::item:selected {{
                background-color: {C_PRIMARY};
            }}
            QTreeView::item:hover {{
                background-color: #1e2d50;
            }}
        """)
        self.file_model = None
        tree_layout.addWidget(self.files_tree)
        splitter.addWidget(tree_container)

        # 文件列表
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(4, 0, 0, 0)
        list_layout.addWidget(QLabel("文件列表"))
        self.files_list = QTableWidget()
        self.files_list.setColumnCount(3)
        self.files_list.setHorizontalHeaderLabels(["文件名", "大小", "修改时间"])
        self.files_list.horizontalHeader().setStretchLastSection(True)
        self.files_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_list.setStyleSheet(f"""
            QTableWidget {{
                background-color: {C_BG_CARD};
                color: {C_TEXT};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
            }}
        """)
        list_layout.addWidget(self.files_list)
        splitter.addWidget(list_container)

        splitter.setSizes([350, 550])
        layout.addWidget(splitter)

    # ═══════════════════════════════════════════════════════
    #  选项卡5: 日志
    # ═══════════════════════════════════════════════════════

    def _build_log_tab(self):
        tab = QWidget()
        tab.setObjectName("logTab")
        self.tabs.addTab(tab, "📋 日志")

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel("  运行日志")
        header.setStyleSheet(f"""
            font-size: 18px; font-weight: 700;
            color: {C_TEXT}; padding: 4px 0;
            border-bottom: 2px solid {C_PRIMARY};
        """)
        layout.addWidget(header)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: #0a0a1a;
                color: #00ff88;
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                line-height: 1.5;
            }}
        """)
        layout.addWidget(self.log_output)

        log_btn_row = QHBoxLayout()
        self.log_btn_clear = IconButton("清空日志", "🗑", "outline")
        self.log_btn_clear.clicked.connect(self.log_output.clear)
        log_btn_row.addWidget(self.log_btn_clear)

        self.log_btn_save = IconButton("导出日志", "💾", "outline")
        self.log_btn_save.clicked.connect(self._save_log)
        log_btn_row.addWidget(self.log_btn_save)
        log_btn_row.addStretch()

        self.log_count_label = QLabel("0 条日志")
        self.log_count_label.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 12px;")
        log_btn_row.addWidget(self.log_count_label)
        layout.addLayout(log_btn_row)

    # ── 信号连接 ──────────────────────────────────────────

    def _connect_signals(self):
        self.log_signal.new_log.connect(self._append_log)
        self.sandbox.on_state_change(self._on_sandbox_state_change)
        self.sandbox.on_error(self._on_sandbox_error)

    def _update_auth_cache(self):
        self._auth_enabled = self.auth_enabled_cb.isChecked()
        self._authorized_ids = [
            self.auth_user_list.item(i).text()
            for i in range(self.auth_user_list.count())
        ]

    def _on_sandbox_state_change(self, old_state, new_state):
        self._update_dashboard()

    def _on_sandbox_error(self, message):
        self._log(f"[错误] {message}", "error")
        QMessageBox.critical(self, "沙盒错误", message)

    def _start_timers(self):
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_dashboard)
        self.status_timer.start(1500)

        self.proc_timer = QTimer()
        self.proc_timer.timeout.connect(self._refresh_processes)
        self.proc_timer.start(3000)

    # ── 操作 ──────────────────────────────────────────────

    def _select_sandbox_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择沙盒根目录",
            os.path.expanduser("~"),
            QFileDialog.Option.ShowDirsOnly
        )
        if dir_path:
            self.dash_root_edit.setText(dir_path)
            self.sandbox.config.root_dir = dir_path
            self.bot_manager.sandbox_root = dir_path
            self._log(f"选择沙盒目录: {dir_path}")

    def _start_sandbox(self):
        root = self.dash_root_edit.text()
        if not root:
            QMessageBox.warning(self, "提示", "请先选择沙盒根目录")
            return

        self.sandbox.config.active_process_limit = self.dash_spin_procs.value()
        self.sandbox.config.memory_limit_mb = self.dash_spin_mem.value()
        self.sandbox.config.enable_file_isolation = self.chk_file_iso.isChecked()
        self.sandbox.config.enable_network_isolation = self.chk_net_iso.isChecked()
        self.sandbox.config.enable_process_isolation = self.chk_proc_iso.isChecked()  # always True, checkbox is locked

        if self.sandbox.start(root):
            if self.sandbox.fs_sandbox:
                self.sandbox.fs_sandbox.add_allowed_write_dir(str(APP_DIR))
            self.event_bus.start()
            self._log(f"沙盒已启动 | 目录: {root}")
            self.dash_btn_start.setEnabled(False)
            self.dash_btn_stop.setEnabled(True)
            self.dash_btn_restart.setEnabled(True)
            self._refresh_files()
        else:
            QMessageBox.critical(self, "错误", "沙盒启动失败，请查看日志")

    def _stop_sandbox(self):
        self.event_bus.stop()
        self.bot_manager.stop_all()
        self.sandbox.stop()
        self._log("沙盒已停止")
        self.dash_btn_start.setEnabled(True)
        self.dash_btn_stop.setEnabled(False)
        self.dash_btn_restart.setEnabled(False)
        self.proc_table.setRowCount(0)

    def _restart_sandbox(self):
        self._log("正在重启沙盒...")
        root = self.sandbox.config.root_dir
        self._stop_sandbox()
        if root:
            self.dash_root_edit.setText(root)
            self._start_sandbox()

    def _refresh_bot_table(self):
        self.bot_table.setRowCount(len(self.bot_instances))
        for i, inst in enumerate(self.bot_instances):
            name_item = QTableWidgetItem(inst.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, i)
            self.bot_table.setItem(i, 0, name_item)
            self.bot_table.setItem(i, 1, QTableWidgetItem(inst.get("app_id", "")))

            bot_id = inst.get("bot_id", "")
            if bot_id and self.bot_manager.is_running(bot_id):
                status_text = "✅ 已连接"
                status_color = C_SUCCESS
            elif bot_id and self.bot_manager.get_platform(bot_id) is not None:
                status_text = "🔄 启动中"
                status_color = C_WARNING
            else:
                status_text = "⏹ 已停止"
                status_color = C_TEXT_DIM

            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(status_color))
            self.bot_table.setItem(i, 2, status_item)

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(4)
            bot_id = inst.get("bot_id", "")
            if bot_id and self.bot_manager.is_running(bot_id):
                stop_btn = QPushButton("停止")
                stop_btn.setStyleSheet(f"QPushButton {{ background: {C_DANGER}; color: white; border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; }} QPushButton:hover {{ background: #c0392b; }}")
                stop_btn.clicked.connect(lambda checked, bid=bot_id: self._stop_single_bot(bid))
                action_layout.addWidget(stop_btn)
            else:
                start_btn = QPushButton("启动")
                start_btn.setStyleSheet(f"QPushButton {{ background: {C_SUCCESS}; color: white; border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; }} QPushButton:hover {{ background: #27ae60; }}")
                start_btn.clicked.connect(lambda checked, idx=i: self._start_single_bot(idx))
                action_layout.addWidget(start_btn)
            action_layout.addStretch()
            self.bot_table.setCellWidget(i, 3, action_widget)
        self.bot_table.resizeRowsToContents()

    def _start_single_bot(self, idx: int):
        if idx < 0 or idx >= len(self.bot_instances):
            return
        inst = self.bot_instances[idx]
        config = BotConfig.from_dict(inst)
        if not config.app_id or not (config.app_secret or config.bot_token):
            QMessageBox.warning(self, "提示", f"机器人 '{config.name}' 缺少 AppID 或 AppSecret")
            return
        bot_id = config.app_id
        inst["bot_id"] = bot_id
        self.bot_manager.configure(config.to_dict(), bot_id=bot_id)
        self.bot_manager.on_message(self._on_bot_message)
        self.bot_manager.start_bot(bot_id)
        self._log(f"正在启动机器人: {config.name} ({bot_id})")
        self._refresh_bot_table()
        QTimer.singleShot(3000, self._refresh_bot_table)

    def _stop_single_bot(self, bot_id: str):
        self.bot_manager.stop_bot(bot_id)
        self._log(f"已停止机器人: {bot_id}")
        self._refresh_bot_table()

    def _start_all_bots(self):
        for i in range(len(self.bot_instances)):
            inst = self.bot_instances[i]
            bot_id = inst.get("bot_id", "")
            if not bot_id or not self.bot_manager.is_running(bot_id):
                self._start_single_bot(i)
        self._log("已请求启动所有机器人")

    def _stop_all_bots(self):
        for inst in self.bot_instances:
            bot_id = inst.get("bot_id", "")
            if bot_id and self.bot_manager.is_running(bot_id):
                self.bot_manager.stop_bot(bot_id)
        self._log("已停止所有机器人")
        self._refresh_bot_table()

    def _on_bot_selection_changed(self):
        row = self.bot_table.currentRow()
        if row < 0 or row >= len(self.bot_instances):
            return
        inst = self.bot_instances[row]
        cfg = BotConfig.from_dict(inst)
        self._apply_bot_config_to_ui(cfg)
        self._apply_ai_overrides_to_ui(inst.get("ai_overrides", {}))

    def _add_bot_instance(self):
        cfg = self._get_bot_config()
        if not cfg.name or not cfg.app_id:
            QMessageBox.warning(self, "提示", "请先填写名称和 AppID")
            return
        data = cfg.to_dict()
        data["ai_overrides"] = self._read_ai_overrides_from_ui()
        data["bot_id"] = ""
        self.bot_instances.append(data)
        self._refresh_bot_table()
        self._save_bot_configs()
        self._log(f"已添加机器人实例: {cfg.name}")

    def _del_bot_instance(self):
        row = self.bot_table.currentRow()
        if row < 0 or row >= len(self.bot_instances):
            QMessageBox.warning(self, "提示", "请先在表格中选中要删除的机器人")
            return
        inst = self.bot_instances[row]
        bot_id = inst.get("bot_id", "")
        if bot_id and self.bot_manager.is_running(bot_id):
            self.bot_manager.stop_bot(bot_id)
        removed = self.bot_instances.pop(row)
        self._refresh_bot_table()
        self._save_bot_configs()
        self._log(f"已删除机器人实例: {removed.get('name', '')}")

    def _save_bot_instance(self):
        row = self.bot_table.currentRow()
        if row < 0 or row >= len(self.bot_instances):
            QMessageBox.warning(self, "提示", "请先在表格中选中要保存的机器人")
            return
        cfg = self._get_bot_config()
        old_bot_id = self.bot_instances[row].get("bot_id", "")
        data = cfg.to_dict()
        data["ai_overrides"] = self._read_ai_overrides_from_ui()
        if old_bot_id and old_bot_id != cfg.app_id:
            if self.bot_manager.is_running(old_bot_id):
                self.bot_manager.stop_bot(old_bot_id)
            data["bot_id"] = ""
        else:
            data["bot_id"] = old_bot_id
        self.bot_instances[row] = data
        self._refresh_bot_table()
        self._save_bot_configs()
        self._log(f"已保存机器人配置: {cfg.name}")

    def _bot_send(self, msg_type: str):
        row = self.bot_table.currentRow()
        if row < 0 or row >= len(self.bot_instances):
            QMessageBox.warning(self, "提示", "请先在表格中选中要使用的机器人")
            return
        inst = self.bot_instances[row]
        bot_id = inst.get("bot_id", "")
        if not bot_id or not self.bot_manager.is_running(bot_id):
            QMessageBox.warning(self, "提示", "所选机器人未在运行")
            return

        channel = self.bot_test_channel.text().strip()
        if not channel:
            QMessageBox.warning(self, "提示", "请填写目标ID")
            return

        if msg_type == "text":
            msg = self.bot_test_msg.text().strip()
            if not msg:
                QMessageBox.warning(self, "提示", "请填写文字内容")
                return
            ok = self.bot_manager.send_message(channel, msg, bot_id=bot_id)
            self._log(f"发送文字 -> {channel}: {msg[:50]}", "success" if ok else "error")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, f"选择{msg_type}文件", "",
                {"image":"图片 (*.png *.jpg *.jpeg *.gif *.webp)", "file":"所有文件 (*.*)", "video":"视频 (*.mp4 *.avi *.mov *.mkv)"}.get(msg_type, "所有文件 (*.*)")
            )
            if not path:
                return
            size = os.path.getsize(path)
            if msg_type == "image":
                ok = self.bot_manager.send_image(channel, path, self.bot_test_msg.text().strip(), bot_id=bot_id)
            elif msg_type == "video":
                ok = self.bot_manager.send_message(channel, f"[视频] {os.path.basename(path)}", bot_id=bot_id)
            else:
                ok = self.bot_manager.send_message(channel, f"[文件] {os.path.basename(path)} ({size/1024:.0f}KB)", bot_id=bot_id)
            self._log(f"发送{msg_type} -> {channel}: {os.path.basename(path)}", "success" if ok else "error")

        if ok:
            QMessageBox.information(self, "成功", f"{msg_type}消息发送成功")
        else:
            QMessageBox.warning(self, "失败", f"{msg_type}消息发送失败，请检查连接")


    def _get_bot_config(self) -> BotConfig:
        config = BotConfig()
        config.name = self.bot_name.text().strip() or f"Bot-{self.bot_appid.text().strip()}"
        config.protocol = BotProtocol.QQ_OFFICIAL if self.bot_proto_combo.currentIndex() == 0 else BotProtocol.ONEBOT
        config.app_id = self.bot_appid.text().strip()
        config.app_secret = self.bot_appsecret.text().strip()
        config.bot_token = self.bot_token.text().strip()
        config.ws_url = self.bot_ws_url.text().strip()
        config.api_url = self.bot_api_url.text().strip()
        config.sandbox_api_url = self.bot_sandbox_api_url.text().strip()
        config.use_sandbox = self.bot_use_sandbox.isChecked()
        config.onebot_ws_url = self.bot_onebot_ws.text().strip()
        config.onebot_http_url = self.bot_onebot_http.text().strip()
        config.enabled = True
        return config

    def _apply_bot_config_to_ui(self, cfg: BotConfig):
        self.bot_name.setText(cfg.name)
        self.bot_appid.setText(cfg.app_id)
        self.bot_appsecret.setText(cfg.app_secret)
        self.bot_token.setText(cfg.bot_token)
        self.bot_ws_url.setText(cfg.ws_url)
        self.bot_api_url.setText(cfg.api_url)
        self.bot_sandbox_api_url.setText(cfg.sandbox_api_url)
        self.bot_use_sandbox.setChecked(cfg.use_sandbox)
        self.bot_onebot_ws.setText(cfg.onebot_ws_url)
        self.bot_onebot_http.setText(cfg.onebot_http_url)
        self.bot_proto_combo.setCurrentIndex(0 if cfg.protocol == BotProtocol.QQ_OFFICIAL else 1)

    def _refresh_bot_ai_provider_list(self):
        self.bot_ai_provider.clear()
        self.bot_ai_provider.addItem("（使用全局默认）", "")
        cfg = getattr(self, '_cached_ai_config', None)
        if cfg:
            for p in cfg.providers:
                if p.api_key:
                    self.bot_ai_provider.addItem(p.display_name(), p.name)

    def _apply_ai_overrides_to_ui(self, overrides: dict):
        provider_name = overrides.get("provider", "")
        idx = self.bot_ai_provider.findData(provider_name)
        self.bot_ai_provider.setCurrentIndex(idx if idx >= 0 else 0)
        self.bot_ai_model.setText(overrides.get("model", ""))
        self.bot_ai_system_prompt.setPlainText(overrides.get("system_prompt", ""))
        et = overrides.get("enable_tools")
        if et is None:
            self.bot_ai_enable_tools.setCheckState(Qt.CheckState.PartiallyChecked)
        elif et:
            self.bot_ai_enable_tools.setCheckState(Qt.CheckState.Checked)
        else:
            self.bot_ai_enable_tools.setCheckState(Qt.CheckState.Unchecked)

    def _read_ai_overrides_from_ui(self) -> dict:
        overrides = {
            "provider": self.bot_ai_provider.currentData() or "",
            "model": self.bot_ai_model.text().strip(),
            "system_prompt": self.bot_ai_system_prompt.toPlainText().strip(),
        }
        state = self.bot_ai_enable_tools.checkState()
        if state == Qt.CheckState.Checked:
            overrides["enable_tools"] = True
        elif state == Qt.CheckState.Unchecked:
            overrides["enable_tools"] = False
        return overrides

    def _save_bot_configs(self):
        bots_data = {"bots": self.bot_instances}
        with open(BOT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(bots_data, f, ensure_ascii=False, indent=2)
        root = getattr(self.sandbox.config, 'root_dir', None) if hasattr(self, 'sandbox') else None
        if root:
            alt = os.path.join(root, "bot_config.json")
            with open(alt, "w", encoding="utf-8") as f:
                json.dump(bots_data, f, ensure_ascii=False, indent=2)

    def _add_auth_user(self):
        user_id, ok = QInputDialog.getText(self, "添加授权用户", "输入用户ID:")
        if ok and user_id.strip():
            existing = [self.auth_user_list.item(i).text() for i in range(self.auth_user_list.count())]
            if user_id.strip() not in existing:
                self.auth_user_list.addItem(user_id.strip())
                self._update_auth_cache()
                self._log(f"已添加授权用户: {user_id.strip()}")

    def _remove_auth_user(self):
        item = self.auth_user_list.currentItem()
        if item:
            self.auth_user_list.takeItem(self.auth_user_list.row(item))
            self._update_auth_cache()
            self._log(f"已移除授权用户: {item.text()}")

    def _on_bot_message(self, data: dict):
        user_id = data.get("author", {}).get("id", "") or str(data.get("user_id", ""))
        content = data.get("content", "")
        if not content and "message" in data:
            msg = data["message"]
            if isinstance(msg, list):
                content = " ".join(seg.get("data", {}).get("text", "") for seg in msg if seg.get("type") == "text")
            else:
                content = str(msg)
        self._log(f"[Bot消息] 用户{user_id}: {content[:100]}")

    def _refresh_processes(self):
        if self.sandbox.state != SandboxState.RUNNING:
            return
        procs = self.sandbox.proc_sandbox.list_processes() if self.sandbox.proc_sandbox else []
        self.proc_table.setRowCount(len(procs))
        for i, p in enumerate(procs):
            self.proc_table.setItem(i, 0, QTableWidgetItem(str(p["pid"])))
            self.proc_table.setItem(i, 1, QTableWidgetItem(p["name"]))
            self.proc_table.setItem(i, 2, QTableWidgetItem(p["command"][:60]))
            self.proc_table.setItem(i, 3, QTableWidgetItem(p["status"]))
            kill_btn = QPushButton("终止")
            kill_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {C_DANGER};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 12px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background-color: #d63031; }}
            """)
            kill_btn.clicked.connect(lambda checked, pid=p["pid"]: self._kill_process(pid))
            self.proc_table.setCellWidget(i, 4, kill_btn)
        self.proc_count_label.setText(f"进程数: {len(procs)}")

    def _kill_selected_process(self):
        row = self.proc_table.currentRow()
        if row >= 0:
            item = self.proc_table.item(row, 0)
            if item:
                self._kill_process(int(item.text()))

    def _kill_process(self, pid):
        if self.sandbox.proc_sandbox:
            self.sandbox.proc_sandbox.kill(pid)
            self._log(f"已终止进程 PID: {pid}")
            self._refresh_processes()

    def _kill_all_processes(self):
        if self.sandbox.proc_sandbox:
            self.sandbox.proc_sandbox.kill_all()
            self._log("已终止全部进程")
            self._refresh_processes()

    def _refresh_files(self):
        root = self.sandbox.config.root_dir
        if not root or not os.path.isdir(root):
            return

        self.files_path_label.setText(f"沙盒根目录: {root}")

        if not self.file_model:
            from PyQt6.QtGui import QFileSystemModel
            self.file_model = QFileSystemModel()
            self.files_tree.setModel(self.file_model)
        self.file_model.setRootPath(root)
        self.files_tree.setRootIndex(self.file_model.index(root))

        # Collapse all columns except first
        for c in range(1, self.file_model.columnCount()):
            self.files_tree.setColumnHidden(c, True)

        # Populate table list
        try:
            entries = []
            for entry in os.scandir(root):
                try:
                    stat = entry.stat()
                    size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    entries.append((entry.name, size, mtime, entry.is_dir()))
                except Exception:
                    pass

            entries.sort(key=lambda x: (not x[3], x[0].lower()))
            self.files_list.setRowCount(len(entries))
            for i, (name, size, mtime, is_dir) in enumerate(entries):
                display_name = f"📁 {name}" if is_dir else f"📄 {name}"
                self.files_list.setItem(i, 0, QTableWidgetItem(display_name))
                if is_dir:
                    self.files_list.setItem(i, 1, QTableWidgetItem("<DIR>"))
                else:
                    size_str = self._format_size(size)
                    self.files_list.setItem(i, 1, QTableWidgetItem(size_str))
                self.files_list.setItem(i, 2, QTableWidgetItem(mtime))
        except Exception as e:
            self._log(f"文件浏览错误: {e}", "error")

    def _format_size(self, size):
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _open_sandbox_folder(self):
        root = self.sandbox.config.root_dir
        if root and os.path.isdir(root):
            os.startfile(root)

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", "sandbox_log.txt", "文本文件 (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_output.toPlainText())
            self._log(f"日志已导出: {path}")

    # ── 界面更新 ──────────────────────────────────────────

    def _update_dashboard(self):
        status = self.sandbox.get_status()
        state = status.get("state", SandboxState.STOPPED)

        # 状态卡片
        if state == SandboxState.RUNNING:
            self.card_state.set_value("运行中")
            self.card_state.set_color(C_SUCCESS)
            self.status_icon.setStyleSheet(f"color: {C_SUCCESS}; font-size: 14px;")
        elif state == SandboxState.ERROR:
            self.card_state.set_value("错误")
            self.card_state.set_color(C_DANGER)
            self.status_icon.setStyleSheet(f"color: {C_DANGER}; font-size: 14px;")
        else:
            self.card_state.set_value("已停止")
            self.card_state.set_color(C_DANGER)
            self.status_icon.setStyleSheet(f"color: {C_DANGER}; font-size: 14px;")

        uptime = status.get("uptime_seconds", 0)
        self.card_uptime.set_value(
            f"{uptime // 3600:02d}:{(uptime % 3600) // 60:02d}:{uptime % 60:02d}"
        )

        stats = status.get("stats", {})
        self.card_processes.set_value(stats.get("active_processes", 0))
        mem = stats.get("memory_usage_mb", 0)
        self.card_memory.set_value(f"{mem:.0f}" if mem else "0", " MB")

        # 机器人状态
        bot_running = self.bot_manager.is_running()
        self.card_bot.set_value("已连接" if bot_running else "未连接")
        self.card_bot.set_color(C_SUCCESS if bot_running else C_DANGER)

        # 统计
        if self.sandbox.fs_sandbox:
            fs_stats = self.sandbox.fs_sandbox.get_stats()
            self.stat_file_blocked.set_value(f"{fs_stats.get('blocked_count', 0)}", " 次")
        if self.sandbox.net_sandbox:
            net_stats = self.sandbox.net_sandbox.get_stats()
            self.stat_net_blocked.set_value(f"{net_stats.get('blocked_count', 0)}", " 次")

        # 状态栏
        bot_text = "已连接" if bot_running else "未连接"
        state_text = "运行中" if state == SandboxState.RUNNING else "已停止" if state == SandboxState.STOPPED else state
        self.status_text.setText(f"沙盒: {state_text}  |  机器人: {bot_text}")

        # 按钮状态
        is_running = state == SandboxState.RUNNING
        self.dash_btn_start.setEnabled(not is_running and bool(self.sandbox.config.root_dir))
        self.dash_btn_stop.setEnabled(is_running)
        self.dash_btn_restart.setEnabled(is_running)

        self._update_sub_agent_list()
        self._update_ai_chat_status()

        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── 日志 ──────────────────────────────────────────────

    def _append_log(self, text):
        self.log_output.append(text)
        self._log_count = getattr(self, '_log_count', 0) + 1
        self.log_count_label.setText(f"{self._log_count} 条日志")

    def _log(self, message, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        colors = {"info": C_TEXT, "warn": C_WARNING, "error": C_DANGER, "success": C_SUCCESS}
        color = colors.get(level, C_TEXT)
        html = f'<span style="color: {C_TEXT_DIM}">[{ts}]</span> <span style="color: {color}">{message}</span>'
        self.log_signal.new_log.emit(html)
        getattr(logger, level if level in ("info", "warn", "error") else "info")(message)

    # ── 管道 / EventBus ───────────────────────────────────

    def _init_pipeline(self):
        if self._pipeline_initialized:
            return
        self._pipeline_initialized = True

        auth_stage = AuthStage(
            auth_check=lambda uid: not self._auth_enabled or uid in self._authorized_ids
        )
        sandbox_stage = SandboxCheckStage(
            is_sandbox_running=lambda: self.sandbox.state == SandboxState.RUNNING
        )
        mem_path = os.path.join(APP_DIR, "conversation_memory.json")
        self.conv_memory = ConversationMemory(persist_path=mem_path)
        send_func = lambda bot_id, cid, msg, mid="", etype="": self.bot_manager.send_message(cid, msg, mid, etype, bot_id=bot_id)
        ai_stage = AIResponseStage(
            provider_manager=self.provider_manager,
            get_config=lambda bot_id="": self._get_pipeline_ai_config(bot_id),
            get_sandbox_root=lambda: self.sandbox.config.root_dir or "",
            memory=self.conv_memory,
            log_func=lambda msg: self._log(msg, "info"),
            sandbox_manager=self.sandbox,
        )
        send_file_func = lambda bot_id, cid, path, text, mid, etype: self.bot_manager.send_file(cid, path, text, mid, etype, bot_id=bot_id)
        respond_stage = RespondStage(
            send_func=send_func,
            send_file_func=send_file_func,
            log_func=lambda msg: self._log(msg, "success"),
        )
        self.pipeline = PipelineScheduler([auth_stage, sandbox_stage, ai_stage, respond_stage])
        self.chat_provider.currentIndexChanged.connect(self._on_chat_provider_changed)
        self.event_bus.set_pipeline(self.pipeline)
        self.bot_manager.set_event_bus(self.event_bus)
        self._log("事件总线 + 消息管道已初始化")

    def _refresh_plugin_list(self):
        self.plugin_list_display.clear()
        from ai.plugins import PluginManager, PLUGIN_DIR
        pm = PluginManager()
        pm.load_all()
        for p in pm.get_all():
            name = getattr(p, 'name', p.__class__.__name__)
            desc = getattr(p, 'description', '')
            item = QListWidgetItem(f"{name} - {desc[:50]}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.plugin_list_display.addItem(item)
        self._log(f"已加载 {self.plugin_list_display.count()} 个插件")

    def _new_plugin(self):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "新建插件", "插件名称(英文):")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_")
        from ai.plugins import PLUGIN_DIR
        plugin_file = PLUGIN_DIR / f"{name}.py"
        if plugin_file.exists():
            QMessageBox.warning(self, "提示", "该插件已存在")
            return
        template = f"""# -*- coding: utf-8 -*-
\"\"\"
{name} - 自定义插件
\"\"\"
import logging
logger = logging.getLogger(__name__)

class Plugin:
    name = "{name}"
    description = "自定义插件"
    version = "1.0"

    async def on_message(self, content, sender, channel):
        # 在此处理消息，返回字符串则作为回复
        # sender = {{"id": "...", "name": "..."}}
        # channel = {{"id": "...", "platform": "..."}}
        return None

    async def get_tool_definitions(self):
        # 返回工具定义列表，格式:
        # [{{"type": "function", "function": {{"name": "...", ...}}}}]
        return []

    async def settings_widget(self):
        # 返回设置面板 (PyQt6 QWidget)，None 表示使用默认设置
        return None
"""
        plugin_file.write_text(template, encoding="utf-8")
        self._refresh_plugin_list()
        self._log(f"已创建插件: {name}")

    def _open_plugin_folder(self):
        from ai.plugins import PLUGIN_DIR
        os.startfile(str(PLUGIN_DIR))

    def _open_plugin_settings(self):
        item = self.plugin_list_display.currentItem()
        if not item:
            return
        plugin = item.data(Qt.ItemDataRole.UserRole)
        if not plugin:
            return
        # Check if plugin has settings_widget
        sw = getattr(plugin, "settings_widget", None)
        if sw:
            try:
                widget = sw()
                if widget:
                    from PyQt6.QtWidgets import QDialog, QVBoxLayout
                    dlg = QDialog(self)
                    dlg.setWindowTitle(f"{getattr(plugin, 'name', '插件')} 设置")
                    dlg.setMinimumSize(400, 300)
                    layout = QVBoxLayout(dlg)
                    layout.addWidget(widget)
                    from PyQt6.QtWidgets import QDialogButtonBox
                    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
                    btns.rejected.connect(dlg.reject)
                    btns.accepted.connect(dlg.accept)
                    layout.addWidget(btns)
                    dlg.exec()
                    return
            except Exception as e:
                self._log(f"插件设置出错: {e}")
        self._log(f"{getattr(plugin, 'name', '插件')}: 无独立设置面板")

    def _on_chat_provider_changed(self, idx: int):
        self._log(f"[切换] 下拉框索引变化: {idx}, 文本: {self.chat_provider.currentText()}")
        name = self.chat_provider.currentText() if idx > 0 else ""
        if not name:
            self._log("[切换] 已切换到默认模型")
            return
        found = False
        for i in range(self.providers_list.count()):
            item = self.providers_list.item(i)
            if not item:
                continue
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("name") == name:
                from ai.config import ProviderConfig
                pc = ProviderConfig.from_dict(data)
                self._log(f"[切换] 找到供应商: {pc.name} ({pc.model})")
                self.ai_provider.setCurrentText(pc.provider)
                self.ai_api_key.setText(pc.api_key)
                self.ai_api_url.setText(pc.api_url)
                self.ai_model.setText(pc.model)
                self.ai_temp.setValue(int(pc.temperature * 100))
                self.ai_max_tokens.setValue(pc.max_tokens)
                # Update cached config
                cfg = self._get_ai_config_from_ui()
                cfg.active_provider = name
                self._cached_ai_config = cfg
                self._update_ai_chat_status()
                self._log(f"[切换] 完成: {pc.name} ({pc.model})")
                found = True
                break
        if not found:
            self._log(f"[切换] 未找到供应商: {name}，供应商列表共 {self.providers_list.count()} 项")

    def _update_ai_chat_status(self):
        cfg = self._cached_ai_config
        ready = False
        if cfg:
            pc = cfg.get_active_provider_config()
            ready = bool(pc and pc.api_key)
        if ready:
            self.chat_status.setStyleSheet(f"color: {C_SUCCESS}; font-weight: 600; font-size: 13px;")
            self.chat_status.setText("● AI 就绪")
        else:
            self.chat_status.setStyleSheet(f"color: {C_DANGER}; font-weight: 600; font-size: 13px;")
            self.chat_status.setText("● AI 未就绪")

    def _get_pipeline_ai_config(self, bot_id: str = ""):
        with self._ai_config_lock:
            cfg = self._cached_ai_config
        if not bot_id:
            return cfg
        # Merge per-bot AI overrides
        for inst in self.bot_instances:
            if inst.get("bot_id") == bot_id or inst.get("app_id") == bot_id:
                overrides = inst.get("ai_overrides", {})
                if not overrides:
                    return cfg
                import copy
                merged = copy.deepcopy(cfg)
                provider_name = overrides.get("provider", "")
                model = overrides.get("model", "")
                system_prompt = overrides.get("system_prompt", "")
                if provider_name:
                    for p in merged.providers:
                        if p.name == provider_name and p.api_key:
                            merged.active_provider = provider_name
                            break
                if model:
                    pc = merged.get_active_provider_config()
                    pc.model = model
                    # also update the matching provider in the list
                    for p in merged.providers:
                        if p.name == merged.active_provider:
                            p.model = model
                            break
                if system_prompt:
                    pc = merged.get_active_provider_config()
                    pc.system_prompt = system_prompt
                    for p in merged.providers:
                        if p.name == merged.active_provider:
                            p.system_prompt = system_prompt
                            break
                et = overrides.get("enable_tools")
                if et is not None:
                    merged.enable_tools = et
                    pc = merged.get_active_provider_config()
                    pc.enable_tools = et
                return merged
        return cfg

    # ── AI 方法 ───────────────────────────────────────────

    def _get_ai_config_from_ui(self) -> AIConfig:
        from ai.skills import SkillsManager
        from ai.plugins import PluginManager
        from ai.config import SkillConfig, PluginConfig, SubAgentConfig, ToolPermissions
        cfg = AIConfig()
        cfg.provider = self.ai_provider.currentText()
        cfg.api_key = self.ai_api_key.text().strip()
        cfg.api_url = self.ai_api_url.text().strip()
        cfg.model = self.ai_model.text().strip()
        cfg.temperature = self.ai_temp.value() / 100
        cfg.max_tokens = self.ai_max_tokens.value()
        cfg.system_prompt = self.ai_system_prompt.toPlainText()
        cfg.enable_tools = self.ai_enable_tools.isChecked()
        cfg.max_tool_rounds = self.ai_max_rounds.value()
        cfg.context_mode = self.ai_context_mode.currentData() or self.ai_context_mode.currentText()
        cfg.context_window = self.ai_ctx_window.value()
        cfg.enable_thinking = self.ai_enable_thinking.isChecked()
        cfg.thinking_model = self.ai_think_model.text().strip()
        cfg.thinking_budget = self.ai_think_budget.value()
        cfg.enable_web_search = self.ai_enable_search.isChecked()
        cfg.search_provider = self.ai_search_provider.currentText()
        tp = ToolPermissions()
        for key, cb in self.perm_cb.items():
            setattr(tp, key, cb.isChecked())
        cfg.tool_permissions = tp
        cfg.skills = []
        for i in range(self.skills_list.count()):
            item = self.skills_list.item(i)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data:
                    cfg.skills.append(SkillConfig.from_dict(data))
        cfg.plugins = []
        for i in range(self.plugins_list.count()):
            item = self.plugins_list.item(i)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data:
                    cfg.plugins.append(PluginConfig.from_dict(data))
        cfg.sub_agents = []
        for i in range(self.sub_list.count()):
            item = self.sub_list.item(i)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data:
                    cfg.sub_agents.append(SubAgentConfig.from_dict(data))
        cfg.providers = []
        for i in range(self.providers_list.count()):
            item = self.providers_list.item(i)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data:
                    cfg.providers.append(ProviderConfig.from_dict(data))
        cfg.active_provider = self.chat_provider.currentText() if self.chat_provider.currentIndex() > 0 else "default"
        cfg.vision_model = self.ai_vision_model.text().strip()
        cfg.vision_api_url = self.ai_vision_api_url.text().strip()
        cfg.vision_api_key = self.ai_vision_api_key.text().strip()
        cfg.image_gen_model = self.ai_img_model.text().strip()
        cfg.image_gen_api_url = self.ai_img_api_url.text().strip()
        cfg.image_gen_api_key = self.ai_img_api_key.text().strip()
        cfg.video_gen_model = self.ai_vid_model.text().strip()
        cfg.video_gen_api_url = self.ai_vid_api_url.text().strip()
        cfg.video_gen_api_key = self.ai_vid_api_key.text().strip()
        return cfg

    def _apply_ai_config_to_ui(self, cfg: AIConfig):
        idx = self.ai_provider.findText(cfg.provider)
        if idx >= 0: self.ai_provider.setCurrentIndex(idx)
        self.ai_api_key.setText(cfg.api_key)
        self.ai_api_url.setText(cfg.api_url)
        self.ai_model.setText(cfg.model)
        self.ai_temp.setValue(int(cfg.temperature * 100))
        self.ai_max_tokens.setValue(cfg.max_tokens)
        self.ai_system_prompt.setPlainText(cfg.system_prompt)
        self.ai_enable_tools.setChecked(cfg.enable_tools)
        self.ai_max_rounds.setValue(cfg.max_tool_rounds)
        cm_idx = self.ai_context_mode.findData(cfg.context_mode)
        if cm_idx < 0:
            cm_idx = self.ai_context_mode.findText(cfg.context_mode)
        if cm_idx >= 0: self.ai_context_mode.setCurrentIndex(cm_idx)
        self.ai_ctx_window.setValue(cfg.context_window)
        self.ai_enable_thinking.setChecked(cfg.enable_thinking)
        self.ai_think_model.setText(cfg.thinking_model)
        self.ai_think_budget.setValue(cfg.thinking_budget)
        self.ai_enable_search.setChecked(cfg.enable_web_search)
        sp_idx = self.ai_search_provider.findText(cfg.search_provider)
        if sp_idx >= 0: self.ai_search_provider.setCurrentIndex(sp_idx)
        for key, cb in self.perm_cb.items():
            cb.setChecked(getattr(cfg.tool_permissions, key, True))
        self.ai_vision_model.setText(cfg.vision_model)
        self.ai_vision_api_url.setText(cfg.vision_api_url)
        self.ai_vision_api_key.setText(cfg.vision_api_key)
        self.ai_img_model.setText(cfg.image_gen_model)
        self.ai_img_api_url.setText(cfg.image_gen_api_url)
        self.ai_img_api_key.setText(cfg.image_gen_api_key)
        self.ai_vid_model.setText(cfg.video_gen_model)
        self.ai_vid_api_url.setText(cfg.video_gen_api_url)
        self.ai_vid_api_key.setText(cfg.video_gen_api_key)
        self.skills_list.clear()
        for s in cfg.skills:
            item = QListWidgetItem(s.name)
            item.setData(Qt.ItemDataRole.UserRole, s.to_dict())
            item.setCheckState(Qt.CheckState.Checked if s.enabled else Qt.CheckState.Unchecked)
            self.skills_list.addItem(item)
        self.plugins_list.clear()
        for p in cfg.plugins:
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.to_dict())
            item.setCheckState(Qt.CheckState.Checked if p.enabled else Qt.CheckState.Unchecked)
            self.plugins_list.addItem(item)
        self.sub_list.clear()
        for s in cfg.sub_agents:
            item = QListWidgetItem(s.name)
            item.setData(Qt.ItemDataRole.UserRole, s.to_dict())
            item.setCheckState(Qt.CheckState.Checked if s.enabled else Qt.CheckState.Unchecked)
            self.sub_list.addItem(item)
        self.providers_list.clear()
        self.chat_provider.clear()
        self.chat_provider.addItem("默认")
        for p in cfg.providers:
            item = QListWidgetItem(p.display_name())
            item.setData(Qt.ItemDataRole.UserRole, p.to_dict())
            self.providers_list.addItem(item)
            self.chat_provider.addItem(p.name)
        if cfg.active_provider:
            idx = self.chat_provider.findText(cfg.active_provider)
            if idx >= 0: self.chat_provider.setCurrentIndex(idx)

    def _fetch_models(self):
        if getattr(self, '_fetch_cancel', None) is not None and not self._fetch_cancel.is_set():
            self._fetch_cancel.set()
            self._fetch_cancel = None
            self.ai_btn_fetch_models.setText("获取模型列表")
            self._log("已取消获取模型")
            return

        api_url = self.ai_api_url.text().strip().rstrip("/")
        api_key = self.ai_api_key.text().strip()
        if not api_key or not api_url:
            QMessageBox.warning(self, "提示", "请先填写 API Key 和 API 地址")
            return

        self._fetch_cancel = threading.Event()
        self.ai_btn_fetch_models.setText("取消")
        self._log(f"正在获取模型列表: {api_url}/models")
        threading.Thread(target=self._do_fetch_models, args=(api_url, api_key), daemon=True).start()

    COMMON_MODELS = {
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "google": ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-pro"],
        "anthropic": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
    }

    def _do_fetch_models(self, api_url: str, api_key: str):
        import httpx
        cancel = self._fetch_cancel
        try:
            url = f"{api_url}/models"
            with httpx.Client(timeout=httpx.Timeout(15)) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            if cancel and cancel.is_set():
                return
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                if models:
                    self.model_signal.models_ready.emit(models)
                    return
            self.model_signal.fetch_error.emit(f"API 返回错误: {resp.status_code}")
        except httpx.ConnectError:
            if not cancel or not cancel.is_set():
                self.model_signal.fetch_error.emit("无法连接 API 服务器，请检查网络和 API 地址")
        except httpx.TimeoutException:
            if not cancel or not cancel.is_set():
                self.model_signal.fetch_error.emit("请求超时，请检查 API 地址是否正确")
        except Exception as e:
            if not cancel or not cancel.is_set():
                err = str(e)
                if "not support" in err or "image" in err.lower():
                    self.model_signal.fetch_error.emit("该 API 不支持获取模型列表")
                else:
                    self.model_signal.fetch_error.emit(f"获取失败: {err[:100]}")
        finally:
            self._fetch_cancel = None

    def _show_model_picker(self, models: list):
        from PyQt6.QtWidgets import QDialog, QListWidget, QVBoxLayout, QDialogButtonBox, QComboBox
        dlg = QDialog(self)
        dlg.setWindowTitle("选择模型"); dlg.setMinimumSize(420, 520)
        dl = QVBoxLayout(dlg)
        target_label = QLabel("填入目标字段:")
        target_label.setStyleSheet(f"color: {C_TEXT}; font-weight: 600;")
        dl.addWidget(target_label)
        target_cb = QComboBox()
        target_cb.addItems(["对话模型 (Chat)", "识图模型 (Vision)", "生图模型 (Image Gen)", "视频模型 (Video Gen)"])
        target_cb.setStyleSheet(f"QComboBox {{ background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 6px; }} QComboBox QAbstractItemView {{ background: {C_BG_INPUT}; color: {C_TEXT}; selection-background: {C_PRIMARY}; }}")
        dl.addWidget(target_cb)
        search = QLineEdit()
        search.setPlaceholderText("搜索模型...")
        search.setStyleSheet(f"background: {C_BG_INPUT}; color: {C_TEXT}; border: 1px solid {C_BORDER}; border-radius: 6px; padding: 8px;")
        dl.addWidget(search)
        lw = QListWidget()
        lw.setStyleSheet(f"QListWidget {{ background: {C_BG_INPUT}; border: 1px solid {C_BORDER}; border-radius: 6px; color: {C_TEXT}; }} QListWidget::item:selected {{ background: {C_PRIMARY}; }}")
        for m in models:
            lw.addItem(m)
        dl.addWidget(lw)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dl.addWidget(btns)

        def filter_models(text):
            for i in range(lw.count()):
                lw.item(i).setHidden(text.lower() not in lw.item(i).text().lower())
        search.textChanged.connect(filter_models)

        # Ensure list items are selectable
        lw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected_item = lw.currentItem()
            if selected_item:
                selected = selected_item.text()
                target_idx = target_cb.currentIndex()
                if target_idx == 0:
                    self.ai_model.setText(selected)
                elif target_idx == 1:
                    self.ai_vision_model.setText(selected)
                elif target_idx == 2:
                    self.ai_img_model.setText(selected)
                elif target_idx == 3:
                    self.ai_vid_model.setText(selected)
                self._log(f"已选择模型 [{target_cb.currentText()}]: {selected}")
        self.ai_btn_fetch_models.setText("获取模型列表")

    def _on_fetch_error(self, msg: str):
        self.ai_btn_fetch_models.setText("获取模型列表")
        self.ai_test_result.setText(msg)

    def _safe_get_ai_config(self) -> AIConfig:
        if threading.current_thread() is threading.main_thread():
            return self._get_ai_config_from_ui()
        self._config_event.clear()
        self.config_signal.config_requested.emit()
        self._config_event.wait(timeout=5)
        return self._pending_config or self._cached_ai_config

    def _on_config_requested(self):
        self._pending_config = self._get_ai_config_from_ui()
        self.config_signal.config_ready.emit(self._pending_config)

    def _on_config_ready(self, config: AIConfig):
        self._config_event.set()

    def _on_provider_changed(self, name: str):
        known = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com",
            "google": "https://generativelanguage.googleapis.com/v1beta/openai",
            "anthropic": "https://api.anthropic.com/v1",
        }
        if name.lower() in known and not self._manual_url_edit:
            self.ai_api_url.setText(known[name.lower()])

    def _add_provider(self):
        text, ok = QInputDialog.getText(self, "添加服务商", "输入服务商名称:")
        if ok and text.strip():
            if self.ai_provider.findText(text.strip()) < 0:
                self.ai_provider.addItem(text.strip())
            self.ai_provider.setCurrentText(text.strip())

    def _del_provider(self):
        idx = self.ai_provider.currentIndex()
        if idx >= 0:
            name = self.ai_provider.currentText()
            if name.lower() in ("openai", "deepseek", "google", "anthropic"):
                QMessageBox.information(self, "提示", f"内置服务商 '{name}' 不可删除")
                return
            self.ai_provider.removeItem(idx)

    def _save_ai_config(self):
        self.ai_config = self._get_ai_config_from_ui()
        self._cached_ai_config = self.ai_config
        self._refresh_bot_ai_provider_list()
        self.ai_config.save(AI_CONFIG_FILE)
        if self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "ai_config.json")
            self.ai_config.save(alt)
        self._log("AI 配置已保存", "success")

    def _add_skill_dialog(self):
        dlg = QDialog(self); dlg.setWindowTitle("添加 Skill"); dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        name_edit = QLineEdit(); name_edit.setPlaceholderText("技能名称")
        form.addRow("名称:", name_edit)
        desc_edit = QLineEdit(); desc_edit.setPlaceholderText("简短描述")
        form.addRow("描述:", desc_edit)
        prompt_edit = QTextEdit(); prompt_edit.setPlaceholderText("系统提示词..."); prompt_edit.setMaximumHeight(120)
        form.addRow("提示词:", prompt_edit)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            from ai.config import SkillConfig
            sc = SkillConfig(name=name_edit.text(), description=desc_edit.text(), system_prompt=prompt_edit.toPlainText())
            item = QListWidgetItem(sc.name)
            item.setData(Qt.ItemDataRole.UserRole, sc.to_dict())
            item.setCheckState(Qt.CheckState.Checked)
            self.skills_list.addItem(item)

    def _del_skill(self):
        for item in self.skills_list.selectedItems():
            self.skills_list.takeItem(self.skills_list.row(item))

    def _add_plugin_dialog(self):
        dlg = QDialog(self); dlg.setWindowTitle("添加插件"); dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        name_edit = QLineEdit(); name_edit.setPlaceholderText("插件名称")
        form.addRow("名称:", name_edit)
        desc_edit = QLineEdit(); desc_edit.setPlaceholderText("简短描述")
        form.addRow("描述:", desc_edit)
        path_edit = QLineEdit(); path_edit.setPlaceholderText("插件脚本路径(.py)")
        brow_btn = QPushButton("浏览")
        def browse_plugin(): 
            p = QFileDialog.getOpenFileName(dlg, "选择插件脚本", "", "Python (*.py)")[0]
            if p: path_edit.setText(p)
        brow_btn.clicked.connect(browse_plugin)
        ph = QHBoxLayout(); ph.addWidget(path_edit); ph.addWidget(brow_btn)
        form.addRow("脚本:", ph)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            from ai.config import PluginConfig
            pc = PluginConfig(name=name_edit.text(), description=desc_edit.text(), script_path=path_edit.text())
            item = QListWidgetItem(pc.name)
            item.setData(Qt.ItemDataRole.UserRole, pc.to_dict())
            item.setCheckState(Qt.CheckState.Checked)
            self.plugins_list.addItem(item)

    def _del_plugin(self):
        for item in self.plugins_list.selectedItems():
            self.plugins_list.takeItem(self.plugins_list.row(item))

    def _add_sub_agent_dialog(self):
        dlg = QDialog(self); dlg.setWindowTitle("添加子Agent"); dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        name_edit = QLineEdit(); name_edit.setPlaceholderText("子Agent名称(如: code-reviewer)")
        form.addRow("名称:", name_edit)
        model_edit = QLineEdit(); model_edit.setPlaceholderText("模型名(留空用主模型)")
        form.addRow("模型:", model_edit)
        temp_spin = QSpinBox(); temp_spin.setRange(0,200); temp_spin.setValue(70)
        form.addRow("温度:", temp_spin)
        prompt_edit = QTextEdit(); prompt_edit.setPlaceholderText("系统提示词..."); prompt_edit.setMaximumHeight(100)
        form.addRow("提示词:", prompt_edit)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            from ai.config import SubAgentConfig
            sc = SubAgentConfig(name=name_edit.text(), model=model_edit.text(),
                                system_prompt=prompt_edit.toPlainText(), temperature=temp_spin.value()/100)
            item = QListWidgetItem(sc.name)
            item.setData(Qt.ItemDataRole.UserRole, sc.to_dict())
            item.setCheckState(Qt.CheckState.Checked)
            self.sub_list.addItem(item)

    def _del_sub_agent(self):
        for item in self.sub_list.selectedItems():
            self.sub_list.takeItem(self.sub_list.row(item))

    def _add_provider_dialog(self):
        dlg = QDialog(self); dlg.setWindowTitle("添加供应商"); dlg.setMinimumWidth(550)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        name_edit = QLineEdit(); name_edit.setPlaceholderText("如: deepseek-pro")
        form.addRow("名称:", name_edit)
        prov_edit = QComboBox(); prov_edit.addItems(["openai", "deepseek", "google", "anthropic", "custom"])
        prov_edit.setEditable(True)
        form.addRow("提供商:", prov_edit)
        key_edit = QLineEdit(); key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", key_edit)
        url_edit = QLineEdit("https://api.openai.com/v1")
        form.addRow("API 地址:", url_edit)

        model_row = QHBoxLayout()
        model_edit = QLineEdit("gpt-4o")
        model_row.addWidget(model_edit)
        btn_fetch = QPushButton("获取模型")
        btn_fetch.setStyleSheet(f"background:{C_PRIMARY};color:white;border:none;border-radius:4px;padding:4px 10px;")
        model_row.addWidget(btn_fetch)
        form.addRow("模型名:", model_row)

        def do_fetch():
            u = url_edit.text().strip().rstrip("/")
            k = key_edit.text().strip()
            if not u or not k:
                return
            import httpx
            btn_fetch.setEnabled(False)
            btn_fetch.setText("获取中...")
            try:
                resp = httpx.get(f"{u}/models", headers={"Authorization": f"Bearer {k}"}, timeout=15)
                if resp.status_code == 200:
                    models = [m["id"] for m in resp.json().get("data", [])]
                    if models:
                        from PyQt6.QtWidgets import QInputDialog
                        m, ok = QInputDialog.getItem(dlg, "选择模型", "模型:", models, False)
                        if ok and m:
                            model_edit.setText(m)
                    else:
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.information(dlg, "提示", "API 返回模型列表为空")
                else:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.information(dlg, "提示", f"API 返回错误: HTTP {resp.status_code}")
            except httpx.ConnectError:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(dlg, "提示", "连接失败，请检查网络和 API 地址")
            except httpx.TimeoutException:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(dlg, "提示", "请求超时")
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(dlg, "提示", f"错误: {str(e)[:50]}")
            finally:
                btn_fetch.setEnabled(True)
                btn_fetch.setText("获取模型")
        btn_fetch.clicked.connect(do_fetch)

        temp_spin = QSpinBox(); temp_spin.setRange(0,200); temp_spin.setValue(70)
        form.addRow("温度:", temp_spin)
        tokens_spin = QSpinBox(); tokens_spin.setRange(256, 128000); tokens_spin.setValue(4096); tokens_spin.setSingleStep(1024)
        form.addRow("Max Tokens:", tokens_spin)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pc = ProviderConfig(
                name=name_edit.text(),
                provider=prov_edit.currentText(),
                api_key=key_edit.text().strip(),
                api_url=url_edit.text().strip(),
                model=model_edit.text().strip(),
                temperature=temp_spin.value() / 100,
                max_tokens=tokens_spin.value(),
            )
            if not pc.name or not pc.api_key:
                return
            item = QListWidgetItem(pc.display_name())
            item.setData(Qt.ItemDataRole.UserRole, pc.to_dict())
            self.providers_list.addItem(item)
            self.chat_provider.addItem(pc.name)

    def _del_provider_cfg(self):
        for item in self.providers_list.selectedItems():
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                idx = self.chat_provider.findText(data["name"])
                if idx >= 0: self.chat_provider.removeItem(idx)
            self.providers_list.takeItem(self.providers_list.row(item))

    async def _test_ai_connection_async(self):
        cfg = self._get_ai_config_from_ui()
        if not cfg.api_key:
            return "错误: 未填写 API Key"
        provider = self.provider_manager.get_or_create(cfg)
        try:
            from ai.base import LLMResponse
            resp = await provider.chat([
                {"role": "system", "content": "你是一个测试助手"},
                {"role": "user", "content": "回复'连接成功'四个字"},
            ])
            return f"连接成功! 回复: {resp.content[:100]}"
        except Exception as e:
            return f"连接失败: {e}"

    def _test_ai_connection(self):
        self.ai_test_result.setText("测试中...")
        self.ai_test_result.setStyleSheet(f"color: {C_WARNING}; font-size: 12px;")
        self.ai_btn_test.setEnabled(False)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._test_ai_connection_async())
            color = C_SUCCESS if "成功" in result else C_DANGER
            self.ai_test_result.setText(result)
            self.ai_test_result.setStyleSheet(f"color: {color}; font-size: 12px; padding: 4px;")
            if "成功" in result:
                self._log(f"AI 连接测试: {result[:80]}", "success")
        except Exception as e:
            self.ai_test_result.setText(f"测试异常: {e}")
            self.ai_test_result.setStyleSheet(f"color: {C_DANGER}; font-size: 12px;")
        finally:
            loop.close()
            self.ai_btn_test.setEnabled(True)

    def _ensure_chat_session(self, config: Optional[AIConfig] = None):
        if self.chat_session and self.chat_session.agent.provider.config.api_key:
            return
        if config:
            self.ai_config = config
        else:
            self.ai_config = self._safe_get_ai_config()
        if not self.ai_config.api_key:
            return
        self.chat_session = ChatSession(self.ai_config)
        self.chat_session.on_new_message(self._on_chat_message)
        if self.sandbox.config.root_dir:
            self.chat_session.set_sandbox_root(self.sandbox.config.root_dir)
        self.chat_session.agent.on_tool(self._on_ai_tool_call)

    def _on_chat_message(self, msg: ChatMessage):
        if msg.role == "user":
            color = C_INFO
        elif msg.role == "assistant":
            color = C_SUCCESS
        else:
            color = C_WARNING
        html = (
            f'<div style="margin: 4px 0;">'
            f'<span style="color: {C_TEXT_DIM}; font-size: 11px;">[{msg.time_str()}]</span> '
            f'<span style="color: {color}; font-weight: 600;">[{msg.role}]</span> '
            f'<span style="color: {C_TEXT};">{msg.content[:200]}</span>'
            f'</div>'
        )
        self.log_signal.new_log.emit(html)

    def _on_ai_tool_call(self, name: str, args: dict):
        if "_result" not in name:
            self._log(f"AI 调用工具: {name}", "info")
        else:
            result = args.get("result", "") if isinstance(args, dict) else str(args)
            self._log(f"工具结果: {str(result)[:100]}", "success")

    def _clear_chat(self):
        if self.chat_session:
            self.chat_session.clear()
        count = self.chat_layout.count()
        if count <= 1:
            return
        last_w = self.chat_layout.itemAt(count - 1).widget()
        for i in reversed(range(count - 1)):
            w = self.chat_layout.itemAt(i).widget()
            if w and w != last_w:
                w.deleteLater()
        self._log("对话已清空")

    def _update_sub_agent_list(self):
        self.chat_sub_agent.clear()
        self.chat_sub_agent.addItem("主Agent")
        for s in self.ai_config.sub_agents:
            if s.enabled and s.name:
                self.chat_sub_agent.addItem(f"@{s.name}")

    def _send_chat_message(self):
        text = self.chat_input.toPlainText().strip()
        if not text:
            return

        if self.sandbox.state != SandboxState.RUNNING:
            QMessageBox.warning(self, "提示", "请先启动沙盒再使用 AI")
            return

        target = self.chat_sub_agent.currentText()
        if target and not target.startswith("主"):
            text = f"/{target[1:]} {text}"

        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.chat_btn_send.setEnabled(False)
        self.chat_status.setStyleSheet(f"color: {C_WARNING}; font-weight: 600;")
        self.chat_status.setText("● AI 思考中...")

        self._add_chat_bubble("user", text)
        self._log(f"[用户] {text[:100]}")
        cached_config = self._get_ai_config_from_ui()
        self._cached_ai_config = cached_config
        cached_config.active_provider = self.chat_provider.currentText() if self.chat_provider.currentIndex() > 0 else "default"
        thread = threading.Thread(target=self._run_ai_reply, args=(text, cached_config), daemon=True)
        thread.start()

    def _run_ai_reply(self, text: str, cached_config: AIConfig):
        self._ensure_chat_session(cached_config)
        if self.sandbox.config.root_dir:
            self.chat_session.set_sandbox_root(self.sandbox.config.root_dir)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            reply = loop.run_until_complete(self.chat_session.send(text))
            self.chat_signal.new_reply.emit(reply)
        except Exception as e:
            self.chat_signal.new_reply.emit(f"错误: {e}")
        finally:
            loop.close()

    def _add_chat_bubble(self, role: str, content: str):
        bubble = QFrame()
        is_user = role == "user"
        bubble.setStyleSheet(f"""
            QFrame {{
                background: {'#2d1b69' if is_user else C_BG_CARD};
                border: 1px solid {C_BORDER};
                border-radius: 12px;
                padding: 12px 16px;
                margin: 2px 0;
            }}
        """)
        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(12, 8, 12, 8)
        b_layout.setSpacing(4)

        role_label = QLabel("你" if is_user else "AI")
        role_label.setStyleSheet(f"color: {C_INFO if is_user else C_SUCCESS}; font-weight: 700; font-size: 12px; border: none;")
        b_layout.addWidget(role_label)

        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"color: {C_TEXT}; font-size: 13px; border: none;")
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        b_layout.addWidget(content_label)

        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)

        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _scroll_chat_to_bottom(self):
        self.chat_area.verticalScrollBar().setValue(
            self.chat_area.verticalScrollBar().maximum()
        )

    def _on_chat_reply(self, reply: str):
        self.chat_input.setEnabled(True)
        self.chat_btn_send.setEnabled(True)
        self.chat_status.setStyleSheet(f"color: {C_SUCCESS}; font-weight: 600;")
        self.chat_status.setText("● AI 就绪")
        self._add_chat_bubble("assistant", reply)
        self._log(f"[AI] {reply[:200]}")

    # ── 配置持久化 ────────────────────────────────────────

    def _save_user_config(self):
        cfg = UserConfig()
        cfg.auth_enabled = self.auth_enabled_cb.isChecked()
        cfg.authorized_ids = [self.auth_user_list.item(i).text() for i in range(self.auth_user_list.count())]
        cfg.save()
        if self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "user_config.json")
            cfg.save(alt)

    def _load_user_config(self):
        path = USER_CONFIG_FILE
        if not os.path.exists(path) and self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "user_config.json")
            if os.path.exists(alt):
                path = alt
        cfg = UserConfig.load(path)
        self.auth_enabled_cb.setChecked(cfg.auth_enabled)
        self.auth_user_list.clear()
        for uid in cfg.authorized_ids:
            self.auth_user_list.addItem(uid)
        self._update_auth_cache()

    def _save_configs(self):
        self.sandbox.config.save(CONFIG_FILE)
        if self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "sandbox_config.json")
            self.sandbox.config.save(alt)
        self._save_bot_configs()
        self._save_user_config()
        self._save_ai_config()
        self._log("配置已保存", "success")

    def _load_configs(self):
        sandbox_path = CONFIG_FILE
        if not os.path.exists(sandbox_path) and self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "sandbox_config.json")
            if os.path.exists(alt):
                sandbox_path = alt
        if os.path.exists(sandbox_path):
            self.sandbox.config = SandboxConfig.load(sandbox_path)
            self.dash_root_edit.setText(self.sandbox.config.root_dir)
            self.dash_spin_procs.setValue(self.sandbox.config.active_process_limit)
            self.dash_spin_mem.setValue(self.sandbox.config.memory_limit_mb)
            self.chk_file_iso.setChecked(self.sandbox.config.enable_file_isolation)
            self.chk_net_iso.setChecked(self.sandbox.config.enable_network_isolation)
            self.chk_proc_iso.setChecked(self.sandbox.config.enable_process_isolation)
            self._log("沙盒配置文件已加载")

        bot_path = BOT_CONFIG_FILE
        if not os.path.exists(bot_path) and self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "bot_config.json")
            if os.path.exists(alt):
                bot_path = alt
        if os.path.exists(bot_path):
            with open(bot_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "bots" in data:
                self.bot_instances = data["bots"]
            elif isinstance(data, list):
                self.bot_instances = data
            else:
                self.bot_instances = [data]
            self._refresh_bot_table()
            if self.bot_instances:
                cfg = BotConfig.from_dict(self.bot_instances[0])
                self._apply_bot_config_to_ui(cfg)
                self._apply_ai_overrides_to_ui(self.bot_instances[0].get("ai_overrides", {}))
            self._log("Bot配置文件已加载")

        ai_path = AI_CONFIG_FILE
        if not os.path.exists(ai_path) and self.sandbox.config.root_dir:
            alt = os.path.join(self.sandbox.config.root_dir, "ai_config.json")
            if os.path.exists(alt):
                ai_path = alt
        if os.path.exists(ai_path):
            loaded = AIConfig.load(ai_path)
            if not loaded.skills:
                from ai.skills import BUILTIN_SKILLS
                loaded.skills = list(BUILTIN_SKILLS)
            self.ai_config = loaded
            self._cached_ai_config = loaded
            self._apply_ai_config_to_ui(loaded)
            self._log("AI配置文件已加载")
            self._refresh_bot_ai_provider_list()

        self._load_user_config()
        self._refresh_plugin_list()

    def _show_about(self):
        QMessageBox.about(self, "关于 SandboxQQ",
            "<h2>SandboxQQ v1.0</h2>"
            "<p>基于 PyQt6 的 Windows 沙盒化 QQBot 运行环境</p>"
            "<p>功能特点:</p>"
            "<ul>"
            "<li>🔒 Windows Job Object 进程隔离</li>"
            "<li>📁 文件系统访问限制</li>"
            "<li>🌐 网络连接白名单控制</li>"
            "<li>🤖 QQ 官方机器人 / OneBot 双协议</li>"
            "<li>📊 实时可视化监控仪表盘</li>"
            "</ul>"
            "<p>类似 AstrBot Agent Sandbox 的本地可视化实现</p>"
        )

    def closeEvent(self, event):
        self.status_timer.stop()
        self.proc_timer.stop()
        self._save_configs()
        self.event_bus.stop()
        self.bot_manager.cleanup()
        self.sandbox.stop()
        if hasattr(self, 'conv_memory') and self.conv_memory:
            self.conv_memory._dirty = True
            self.conv_memory._save()
        self._log("SandboxQQ 已退出")
        event.accept()
