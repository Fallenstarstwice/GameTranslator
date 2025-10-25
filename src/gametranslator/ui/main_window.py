"""
Main window UI for GameTranslator.
"""

import logging
import os
import requests
from PIL import Image
from PySide6.QtGui import QCloseEvent, QPixmap, QImage, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton,
    QLabel, QTextEdit, QHBoxLayout, QComboBox,
    QTabWidget, QMessageBox, QLineEdit, QGroupBox,
    QFormLayout, QCheckBox, QSpinBox, QProgressBar, QScrollArea
)
from PySide6.QtCore import Qt, QRect, QThread, Signal, QObject, QEvent
from PySide6.QtGui import QGuiApplication
from typing import Optional

from src.gametranslator.config.settings import settings
from src.gametranslator.core.screen_capture import ScreenCapture
from src.gametranslator.core.ocr import OCREngine
from src.gametranslator.core.translator import get_translator
from src.gametranslator.ui.floating_window import FloatingWindow
from src.gametranslator.ui.screen_selector import ScreenSelector
from src.gametranslator.ui.vocabulary_view import VocabularyView
from src.gametranslator.ui.hotkey_manager import HotkeyManager
from src.gametranslator.core.vocabulary_db import VocabularyDB
from src.gametranslator.core.translation_worker import TranslationWorker
from src.gametranslator.config.llm_provider_manager import LLMProviderManager
from src.gametranslator.config.embedding_provider_manager import EmbeddingProviderManager
from PySide6.QtWidgets import QInputDialog


log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()

        # Apply modern stylesheet
        theme = str(settings.get("ui", "theme", "dark"))
        self.apply_stylesheet(theme)

        # Force update hotkeys in config file to new defaults.
        # This acts as a one-time migration for existing users.
        settings.set("hotkeys", "capture", "alt+q")
        settings.set("hotkeys", "translate", "alt+w")
        
        # Initialize components
        self.ocr_engine = OCREngine()
        self.translator = get_translator()
        self.floating_window = FloatingWindow()
        self.vocabulary_db = VocabularyDB(db_path="db/vocabulary")
        self.llm_provider_manager = LLMProviderManager()
        self.embedding_provider_manager = EmbeddingProviderManager()
        self.selector = None
        self.api_test_thread = None
        self.llm_test_thread = None
        self.embedding_test_thread = None
        self.translation_worker = None
        self.last_selection_rect = None
        self.current_screenshot = None # To hold the full-screen capture

        # Settings change tracking
        self._settings_dirty = False
        self._loading_settings = False
        self._blocking_tab_change = False
        self._last_tab_index = 0
        
        # Set up UI
        self.setWindowTitle("GameTranslator")
        self.setMinimumSize(800, 600)
        
        # Create central widget with tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Create main tab
        self.main_tab = QWidget()
        self.main_layout = QVBoxLayout(self.main_tab)
        self.tabs.addTab(self.main_tab, "翻译")
        
        # Create vocabulary tab
        self.vocabulary_view = VocabularyView(self.vocabulary_db)
        self.tabs.addTab(self.vocabulary_view, "词汇本")
        
        # Create settings tab
        self.create_settings_tab()
        self.settings_tab_index = self.tabs.addTab(self.settings_tab, "设置")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        # Create UI components in main tab
        self.create_main_translation_tab()
        self.create_status_bar()
        
        # Initialize hotkey manager
        self.hotkey_manager = HotkeyManager(self)
        
        # Connect signals
        self.connect_signals()
        
        # Load current settings to UI
        self.load_settings_to_ui()

        # Set initial visibility of API settings
        self.on_service_changed(self.api_service.currentText())

        # Initial population of collections for floating window
        self.on_collections_changed()
        self.update_rag_vocab_list()

        # Disable wheel scroll on all combo boxes to prevent accidental changes
        for combo in self.findChildren(QComboBox):
            combo.installEventFilter(self)



    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """
        Filters out all wheel events on QComboBoxes to prevent accidental
        value changes, passing the scroll to the parent widget.
        """
        if event.type() == QEvent.Type.Wheel and isinstance(watched, QComboBox):
            # Always ignore wheel events for QComboBoxes.
            # The event is propagated to the parent, e.g., a QScrollArea.
            event.ignore()
            return True # Mark as handled
        return super().eventFilter(watched, event)

    def apply_stylesheet(self, theme_name: str = "dark"):
        """Loads and applies the QSS stylesheet for the given theme."""
        if not theme_name:  # Can happen if the combo is cleared
            theme_name = "dark"
        style_file = f"{theme_name.lower()}_theme.qss"
        try:
            style_path = os.path.join(os.path.dirname(__file__), "styles", style_file)
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            log.info(f"Applied {theme_name} theme.")
        except FileNotFoundError:
            log.warning(f"Stylesheet '{style_file}' not found. Defaulting to dark theme.")
            if theme_name != "dark":
                self.apply_stylesheet("dark")  # Fallback
        except Exception as e:
            log.error(f"Error applying stylesheet: {e}", exc_info=True)

    def create_main_translation_tab(self):
        """Creates the main translation tab with a modernized layout."""
        # --- Top Action Bar ---
        action_bar_widget = QWidget()
        action_bar_layout = QHBoxLayout(action_bar_widget)
        action_bar_layout.setContentsMargins(0, 0, 0, 0)
        action_bar_layout.setSpacing(10)

        self.capture_button = QPushButton(" 截取屏幕翻译")
        self.capture_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "camera.svg")))
        self.capture_button.setToolTip("快捷键: Alt+Q")
        
        self.translate_button = QPushButton(" 翻译文本")
        self.translate_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "globe.svg")))
        self.translate_button.setToolTip("快捷键: Alt+W")

        action_bar_layout.addWidget(self.capture_button)
        action_bar_layout.addWidget(self.translate_button)
        action_bar_layout.addStretch()
        
        self.main_layout.addWidget(action_bar_widget)

        # --- Text Areas (Side-by-Side) ---
        text_areas_widget = QWidget()
        text_areas_layout = QHBoxLayout(text_areas_widget)
        text_areas_layout.setContentsMargins(0, 10, 0, 0)
        text_areas_layout.setSpacing(10)

        # Left side: Source text
        source_widget = QWidget()
        source_layout = QVBoxLayout(source_widget)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(QLabel("识别文本:"))
        self.source_text = QTextEdit()
        source_layout.addWidget(self.source_text)

        # OCR language selection
        ocr_layout = QHBoxLayout()
        ocr_layout.addWidget(QLabel("OCR语言:"))
        self.ocr_language = QComboBox()
        self.ocr_language.addItems(["eng", "jpn", "chi_sim", "chi_tra", "kor"])
        ocr_layout.addWidget(self.ocr_language)
        ocr_layout.addStretch()
        source_layout.addLayout(ocr_layout)

        # Right side: Translated text
        translated_widget = QWidget()
        translated_layout = QVBoxLayout(translated_widget)
        translated_layout.setContentsMargins(0, 0, 0, 0)
        translated_layout.addWidget(QLabel("翻译结果:"))
        self.translated_text = QTextEdit()
        translated_layout.addWidget(self.translated_text)
        
        # Target language selection
        target_lang_layout = QHBoxLayout()
        target_lang_layout.addWidget(QLabel("目标语言:"))
        self.target_language = QComboBox()
        self.target_language.addItems(["zh-CN", "en", "ja", "ko", "fr", "de"])
        target_lang_layout.addWidget(self.target_language)
        target_lang_layout.addStretch()
        translated_layout.addLayout(target_lang_layout)

        text_areas_layout.addWidget(source_widget)
        text_areas_layout.addWidget(translated_widget)
        self.main_layout.addWidget(text_areas_widget)

        # --- Bottom Action Bar ---
        bottom_bar_widget = QWidget()
        bottom_bar_layout = QHBoxLayout(bottom_bar_widget)
        bottom_bar_layout.setContentsMargins(0, 10, 0, 0)

        self.toggle_floating = QPushButton(" 隐藏悬浮窗")
        self.toggle_floating.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "eye.svg")))
        self.add_to_vocab = QPushButton(" 添加到词汇本")
        self.add_to_vocab.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "plus-square.svg")))
        self.add_to_vocab.clicked.connect(self.add_to_vocabulary)

        bottom_bar_layout.addStretch()
        bottom_bar_layout.addWidget(self.toggle_floating)
        bottom_bar_layout.addWidget(self.add_to_vocab)
        
        self.main_layout.addWidget(bottom_bar_widget)
    
    def create_settings_tab(self):
        """Create settings tab with API configuration."""
        self.settings_tab = QWidget()
        tab_layout = QVBoxLayout(self.settings_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        # Create a scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("settingsScrollArea")
        tab_layout.addWidget(scroll_area)

        # Create a container widget for all the settings content
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setSpacing(15)  # Add vertical spacing between group boxes
        scroll_area.setWidget(settings_container)
        
        # --- Service Selection Group ---
        api_group = QGroupBox("翻译服务")
        api_layout = QFormLayout(api_group)
        self.api_service = QComboBox()
        self.api_service.addItems(["microsoft", "llm", "google", "baidu"])
        self.api_service.currentTextChanged.connect(self.on_service_changed)
        api_layout.addRow("翻译服务:", self.api_service)
        settings_layout.addWidget(api_group)

        # --- Microsoft Translator Settings Group ---
        self.ms_api_group = QGroupBox("微软翻译设置")
        ms_api_layout = QFormLayout(self.ms_api_group)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("请输入您的微软API密钥")
        ms_api_layout.addRow("API密钥:", self.api_key_input)
        
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("如: eastasia, westus2")
        ms_api_layout.addRow("区域:", self.region_input)
        
        ms_test_layout = QHBoxLayout()
        self.test_api_button = QPushButton(" 测试微软API")
        self.test_api_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "zap.svg")))
        self.test_api_button.clicked.connect(self.test_api_connection)
        ms_test_layout.addWidget(self.test_api_button)
        
        self.api_status_label = QLabel("未测试")
        ms_test_layout.addWidget(self.api_status_label)
        
        self.api_test_progress = QProgressBar()
        self.api_test_progress.setVisible(False)
        ms_test_layout.addWidget(self.api_test_progress)
        ms_api_layout.addRow("连接状态:", ms_test_layout)
        settings_layout.addWidget(self.ms_api_group)

        # --- Embedding Settings Group ---
        self.embedding_api_group = QGroupBox("词汇本 Embedding 设置")
        embedding_api_layout = QFormLayout(self.embedding_api_group)

        # Provider template management
        self.embedding_provider_combo = QComboBox()
        self.embedding_provider_combo.addItems(self.embedding_provider_manager.get_provider_names())
        self.embedding_provider_combo.currentTextChanged.connect(self.on_embedding_provider_changed)
        embedding_api_layout.addRow("服务商:", self.embedding_provider_combo)

        embedding_buttons_layout = QHBoxLayout()
        self.save_embedding_template_button = QPushButton(" 另存为新模板...")
        self.save_embedding_template_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "file-plus.svg")))
        self.save_embedding_template_button.clicked.connect(self.save_as_new_embedding_template)
        embedding_buttons_layout.addWidget(self.save_embedding_template_button)

        self.delete_embedding_template_button = QPushButton(" 删除当前模板")
        self.delete_embedding_template_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "trash-2.svg")))
        self.delete_embedding_template_button.clicked.connect(self.delete_current_embedding_template)
        embedding_buttons_layout.addWidget(self.delete_embedding_template_button)
        embedding_buttons_layout.addStretch()
        embedding_api_layout.addRow("", embedding_buttons_layout)

        self.embedding_api_key_input = QLineEdit()
        self.embedding_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.embedding_api_key_input.setPlaceholderText("请输入您的Embedding API密钥")
        embedding_api_layout.addRow("API密钥:", self.embedding_api_key_input)
        
        self.embedding_base_url_input = QLineEdit()
        self.embedding_base_url_input.setPlaceholderText("例如: https://api.openai.com/v1")
        embedding_api_layout.addRow("API Base URL:", self.embedding_base_url_input)

        self.embedding_model_combo = QComboBox()
        self.embedding_model_combo.setEditable(True)
        embedding_api_layout.addRow("模型名称:", self.embedding_model_combo)
        
        # Embedding Test button and status
        embedding_test_layout = QHBoxLayout()
        self.embedding_test_api_button = QPushButton(" 测试Embedding连接")
        self.embedding_test_api_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "zap.svg")))
        self.embedding_test_api_button.clicked.connect(self.test_embedding_connection)
        embedding_test_layout.addWidget(self.embedding_test_api_button)

        self.embedding_api_status_label = QLabel("未测试")
        embedding_test_layout.addWidget(self.embedding_api_status_label)

        self.embedding_api_test_progress = QProgressBar()
        self.embedding_api_test_progress.setVisible(False)
        embedding_test_layout.addWidget(self.embedding_api_test_progress)
        embedding_api_layout.addRow("连接状态:", embedding_test_layout)
        
        settings_layout.addWidget(self.embedding_api_group)

        # --- LLM API Settings Group ---
        self.llm_api_group = QGroupBox("大模型(LLM)设置")
        llm_api_layout = QFormLayout(self.llm_api_group)
        
        # Provider template management
        self.llm_provider_combo = QComboBox()
        self.llm_provider_combo.addItems(self.llm_provider_manager.get_provider_names())
        self.llm_provider_combo.currentTextChanged.connect(self.on_llm_provider_changed)
        llm_api_layout.addRow("服务商:", self.llm_provider_combo)

        llm_buttons_layout = QHBoxLayout()
        self.save_llm_template_button = QPushButton(" 另存为新模板...")
        self.save_llm_template_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "file-plus.svg")))
        self.save_llm_template_button.clicked.connect(self.save_as_new_llm_template)
        llm_buttons_layout.addWidget(self.save_llm_template_button)

        self.delete_llm_template_button = QPushButton(" 删除当前模板")
        self.delete_llm_template_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "trash-2.svg")))
        self.delete_llm_template_button.clicked.connect(self.delete_current_llm_template)
        llm_buttons_layout.addWidget(self.delete_llm_template_button)
        llm_buttons_layout.addStretch()
        llm_api_layout.addRow("", llm_buttons_layout)

        self.llm_api_key_input = QLineEdit()
        self.llm_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_api_key_input.setPlaceholderText("请输入您的LLM API密钥")
        llm_api_layout.addRow("LLM API密钥:", self.llm_api_key_input)
        
        self.llm_base_url_input = QLineEdit()
        self.llm_base_url_input.setPlaceholderText("例如: https://api.openai.com/v1")
        llm_api_layout.addRow("API Base URL:", self.llm_base_url_input)

        self.llm_model_combo = QComboBox()
        self.llm_model_combo.setEditable(True)
        llm_api_layout.addRow("模型名称:", self.llm_model_combo)

        self.llm_rag_vocab_combo = QComboBox()
        llm_api_layout.addRow("RAG词汇本:", self.llm_rag_vocab_combo)
        self.llm_rag_vocab_combo.currentTextChanged.connect(self.on_rag_vocab_changed)
        llm_rag_hint = QLabel("启用RAG需先配置Embedding服务")
        llm_api_layout.addRow("提示:", llm_rag_hint)

        # LLM Test button and status
        llm_test_layout = QHBoxLayout()
        self.llm_test_api_button = QPushButton(" 测试LLM连接")
        self.llm_test_api_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "zap.svg")))
        self.llm_test_api_button.clicked.connect(self.test_llm_connection)
        llm_test_layout.addWidget(self.llm_test_api_button)

        self.llm_api_status_label = QLabel("未测试")
        llm_test_layout.addWidget(self.llm_api_status_label)

        self.llm_api_test_progress = QProgressBar()
        self.llm_api_test_progress.setVisible(False)
        llm_test_layout.addWidget(self.llm_api_test_progress)
        llm_api_layout.addRow("连接状态:", llm_test_layout)
        settings_layout.addWidget(self.llm_api_group)
        try:
            settings_layout.removeWidget(self.llm_api_group)
            settings_layout.removeWidget(self.embedding_api_group)
            settings_layout.addWidget(self.llm_api_group)
            settings_layout.addWidget(self.embedding_api_group)
        except Exception:
            pass
        
        # Language Settings Group
        lang_group = QGroupBox("语言设置")
        lang_layout = QFormLayout(lang_group)
        
        # Source language
        self.source_lang_combo = QComboBox()
        self.source_lang_combo.addItems(["auto", "en", "zh-CN", "ja", "ko", "fr", "de", "es"])
        self.source_lang_combo.setCurrentText(str(settings.get("translation", "source_language", "auto")))
        lang_layout.addRow("源语言:", self.source_lang_combo)
        
        # Target language
        self.target_lang_combo = QComboBox()
        self.target_lang_combo.addItems(["zh-CN", "en", "ja", "ko", "fr", "de", "es"])
        self.target_lang_combo.setCurrentText(str(settings.get("translation", "target_language", "zh-CN")))
        lang_layout.addRow("目标语言:", self.target_lang_combo)
        
        settings_layout.addWidget(lang_group)
        
        # OCR Settings Group
        ocr_group = QGroupBox("OCR设置")
        ocr_layout = QFormLayout(ocr_group)
        
        # OCR Language
        self.ocr_lang_combo = QComboBox()
        self.ocr_lang_combo.addItems(["eng", "jpn", "chi_sim", "chi_tra", "kor", "fra", "deu", "spa"])
        self.ocr_lang_combo.setCurrentText(str(settings.get("ocr", "language", "eng")))
        ocr_layout.addRow("OCR语言:", self.ocr_lang_combo)
        
        # Tesseract path (optional)
        self.tesseract_path_input = QLineEdit()
        self.tesseract_path_input.setText(str(settings.get("ocr", "tesseract_path", "") or ""))
        self.tesseract_path_input.setPlaceholderText("留空自动检测")
        ocr_layout.addRow("Tesseract路径:", self.tesseract_path_input)
        
        settings_layout.addWidget(ocr_group)
        
        # UI Settings Group
        ui_group = QGroupBox("界面设置")
        ui_layout = QFormLayout(ui_group)
        
        # Theme
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(str(settings.get("ui", "theme", "dark")))
        self.theme_combo.currentTextChanged.connect(self.apply_stylesheet)
        ui_layout.addRow("主题:", self.theme_combo)
        
        # Floating window opacity
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(10, 100)
        self.opacity_spin.setSuffix("%")
        try:
            opacity_setting = settings.get("ui", "floating_window_opacity", 0.8)
            if isinstance(opacity_setting, (int, float, str)):
                self.opacity_spin.setValue(int(float(opacity_setting) * 100))
            else:
                self.opacity_spin.setValue(80)
        except (ValueError, TypeError):
            self.opacity_spin.setValue(80)
        ui_layout.addRow("悬浮窗透明度:", self.opacity_spin)
        
        settings_layout.addWidget(ui_group)
        
        # Hotkey Settings Group
        hotkey_group = QGroupBox("快捷键设置")
        hotkey_layout = QFormLayout(hotkey_group)
        
        self.capture_hotkey_input = QLineEdit()
        self.capture_hotkey_input.setText(str(settings.get("hotkeys", "capture", "alt+q")))
        hotkey_layout.addRow("截图快捷键:", self.capture_hotkey_input)
        
        self.translate_hotkey_input = QLineEdit()
        self.translate_hotkey_input.setText(str(settings.get("hotkeys", "translate", "alt+w")))
        hotkey_layout.addRow("翻译快捷键:", self.translate_hotkey_input)
        
        self.toggle_hotkey_input = QLineEdit()
        self.toggle_hotkey_input.setText(str(settings.get("hotkeys", "toggle_window", "ctrl+shift+space")))
        hotkey_layout.addRow("切换悬浮窗:", self.toggle_hotkey_input)

        self.save_vocab_hotkey_input = QLineEdit()
        self.save_vocab_hotkey_input.setText(str(settings.get("hotkeys", "save_vocabulary", "ctrl+s")))
        hotkey_layout.addRow("保存修改 (词汇本):", self.save_vocab_hotkey_input)
        
        settings_layout.addWidget(hotkey_group)
        
        # Save and Reset buttons
        buttons_layout = QHBoxLayout()
        
        self.save_settings_button = QPushButton(" 保存设置")
        self.save_settings_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "save.svg")))
        self.save_settings_button.clicked.connect(self.save_settings)
        buttons_layout.addWidget(self.save_settings_button)
        
        self.reset_settings_button = QPushButton(" 重置为默认")
        self.reset_settings_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "refresh-cw.svg")))
        self.reset_settings_button.clicked.connect(self.reset_settings)
        buttons_layout.addWidget(self.reset_settings_button)
        
        # API Help button
        self.api_help_button = QPushButton(" 获取API密钥帮助")
        self.api_help_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "help-circle.svg")))
        self.api_help_button.clicked.connect(self.show_api_help)
        buttons_layout.addWidget(self.api_help_button)
        
        settings_layout.addLayout(buttons_layout)
        
        # Add stretch to push everything to top
        settings_layout.addStretch()

        # Track changes in Settings to detect unsaved modifications
        for widget in self.settings_tab.findChildren(QLineEdit):
            widget.textChanged.connect(self.mark_settings_dirty)
        for widget in self.settings_tab.findChildren(QComboBox):
            widget.currentIndexChanged.connect(self.mark_settings_dirty)
            widget.currentTextChanged.connect(self.mark_settings_dirty)
        for widget in self.settings_tab.findChildren(QSpinBox):
            widget.valueChanged.connect(self.mark_settings_dirty)
        for widget in self.settings_tab.findChildren(QCheckBox):
            widget.stateChanged.connect(self.mark_settings_dirty)

    def on_service_changed(self, service: str):
        """Shows/hides API setting fields based on the selected service."""
        is_microsoft = (service == "microsoft")
        is_llm = (service == "llm")
        
        if hasattr(self, 'ms_api_group'):
            self.ms_api_group.setVisible(is_microsoft)
        
        if hasattr(self, 'llm_api_group'):
            self.llm_api_group.setVisible(is_llm)

    def on_llm_provider_changed(self, provider_name: str):
        """Updates LLM setting fields based on the selected provider template."""
        provider = self.llm_provider_manager.get_provider_by_name(provider_name)
        if not provider:
            # If the saved provider is not found (e.g., deleted), fall back to "custom".
            # This prevents a crash and provides a stable state.
            self.llm_provider_combo.setCurrentText("自定义...")
            # The signal will fire again for "自定义...", so we just return here.
            return

        is_custom = provider.get("id") == "custom"
        
        # Update UI fields
        self.llm_base_url_input.setText(provider.get("base_url", ""))
        self.llm_model_combo.clear()
        self.llm_model_combo.addItems(provider.get("models", []))
        
        # Set UI element states
        self.llm_base_url_input.setReadOnly(not is_custom)
        self.save_llm_template_button.setEnabled(is_custom)
        self.delete_llm_template_button.setEnabled(provider.get("deletable", False))

    def on_embedding_provider_changed(self, provider_name: str):
        """Updates Embedding setting fields based on the selected provider template."""
        provider = self.embedding_provider_manager.get_provider_by_name(provider_name)
        if not provider:
            self.embedding_provider_combo.setCurrentText("自定义...")
            return

        is_custom = provider.get("id") == "custom"
        
        self.embedding_base_url_input.setText(provider.get("base_url", ""))
        self.embedding_model_combo.clear()
        self.embedding_model_combo.addItems(provider.get("models", []))
        
        self.embedding_base_url_input.setReadOnly(not is_custom)
        self.save_embedding_template_button.setEnabled(is_custom)
        self.delete_embedding_template_button.setEnabled(provider.get("deletable", False))

    def save_as_new_embedding_template(self):
        """Saves the current custom Embedding settings as a new template."""
        text, ok = QInputDialog.getText(self, "保存新Embedding模板", "请输入新模板的名称:")
        if ok and text:
            base_url = self.embedding_base_url_input.text().strip()
            current_model = self.embedding_model_combo.currentText().strip()
            models = [current_model] if current_model else []

            if self.embedding_provider_manager.add_provider(text, base_url, models):
                self.embedding_provider_combo.blockSignals(True)
                self.embedding_provider_combo.clear()
                self.embedding_provider_combo.addItems(self.embedding_provider_manager.get_provider_names())
                self.embedding_provider_combo.setCurrentText(text)
                self.embedding_provider_combo.blockSignals(False)
                self.on_embedding_provider_changed(text)
                QMessageBox.information(self, "成功", f"Embedding模板 '{text}' 已保存。")
            else:
                QMessageBox.warning(self, "错误", f"无法保存模板，名称 '{text}' 可能已存在。")

    def delete_current_embedding_template(self):
        """Deletes the currently selected Embedding provider template."""
        provider_name = self.embedding_provider_combo.currentText()
        provider = self.embedding_provider_manager.get_provider_by_name(provider_name)

        if not provider or not provider.get("deletable"):
            QMessageBox.warning(self, "操作无效", "无法删除此模板。")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"您确定要删除Embedding模板 '{provider_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.embedding_provider_manager.delete_provider(provider["id"]):
                self.embedding_provider_combo.clear()
                self.embedding_provider_combo.addItems(self.embedding_provider_manager.get_provider_names())
                self.embedding_provider_combo.setCurrentText("自定义...")
                QMessageBox.information(self, "成功", f"Embedding模板 '{provider_name}' 已删除。")
            else:
                QMessageBox.warning(self, "错误", "删除Embedding模板时发生错误。")

    def save_as_new_llm_template(self):
        """Saves the current custom LLM settings as a new template."""
        text, ok = QInputDialog.getText(self, "保存新模板", "请输入新模板的名称:")
        if ok and text:
            base_url = self.llm_base_url_input.text().strip()
            # Get current text from editable combobox, even if not in list
            current_model = self.llm_model_combo.currentText().strip()
            models = [current_model] if current_model else []

            if self.llm_provider_manager.add_provider(text, base_url, models):
                # Refresh provider list and select the new one
                self.llm_provider_combo.blockSignals(True)
                self.llm_provider_combo.clear()
                self.llm_provider_combo.addItems(self.llm_provider_manager.get_provider_names())
                self.llm_provider_combo.setCurrentText(text)
                self.llm_provider_combo.blockSignals(False)
                # Manually trigger update for the new provider
                self.on_llm_provider_changed(text)
                QMessageBox.information(self, "成功", f"模板 '{text}' 已保存。")
            else:
                QMessageBox.warning(self, "错误", f"无法保存模板，名称 '{text}' 可能已存在。")

    def delete_current_llm_template(self):
        """Deletes the currently selected LLM provider template."""
        provider_name = self.llm_provider_combo.currentText()
        provider = self.llm_provider_manager.get_provider_by_name(provider_name)

        if not provider or not provider.get("deletable"):
            QMessageBox.warning(self, "操作无效", "无法删除此模板。")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"您确定要删除模板 '{provider_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.llm_provider_manager.delete_provider(provider["id"]):
                # Refresh provider list and switch to "custom"
                self.llm_provider_combo.clear()
                self.llm_provider_combo.addItems(self.llm_provider_manager.get_provider_names())
                self.llm_provider_combo.setCurrentText("自定义...")
                QMessageBox.information(self, "成功", f"模板 '{provider_name}' 已删除。")
            else:
                QMessageBox.warning(self, "错误", "删除模板时发生错误。")
    
    def create_status_bar(self):
        """Create status bar."""
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("就绪")
    
    def connect_signals(self):
        """Connect UI signals to slots."""
        # Button signals
        self.capture_button.clicked.connect(self.capture_screen)
        self.translate_button.clicked.connect(self.translate_text)
        # The button in the UI just hides the window. The hotkey can still toggle.
        self.toggle_floating.clicked.connect(self.floating_window.hide)
        
        # Combobox signals
        self.ocr_language.currentTextChanged.connect(self.update_ocr_language)
        self.target_language.currentTextChanged.connect(self.update_target_language)
        
        # Hotkey signals
        self.hotkey_manager.capture_triggered.connect(self.capture_screen)
        self.hotkey_manager.translate_triggered.connect(self.translate_text)
        self.hotkey_manager.toggle_window_triggered.connect(self.toggle_floating_window)

        # Vocabulary view signals
        self.vocabulary_view.collections_changed.connect(self.on_collections_changed)
        self.vocabulary_view.collections_changed.connect(self.update_rag_vocab_list)
        self.vocabulary_view.manual_add_requested.connect(self.on_manual_add_requested)
        self.vocabulary_view.embedding_config_requested.connect(self.on_embedding_config_requested)

        # Floating window signals
        self.floating_window.add_to_vocabulary_requested.connect(self.add_floating_to_vocabulary)
    
    def capture_screen(self):
        """
        Captures the entire screen and presents a selection overlay without losing focus
        on other applications, such as games in borderless fullscreen mode.
        """
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("全屏截图已捕获，请选择区域...")

        try:
            # 1. Capture the entire screen in the background. This returns a PIL Image.
            # This is the crucial first step to avoid focus-related issues.
            self.current_screenshot = ScreenCapture.capture_screen()
            if self.current_screenshot is None:
                raise ValueError("截图失败，未能获取图像。")

            # 2. Convert the PIL Image to a QPixmap for display in a Qt widget.
            # This conversion is necessary to integrate with the PySide6 UI.
            img = self.current_screenshot.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimage = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            screenshot_pixmap = QPixmap.fromImage(qimage)

            # 3. Create the selector widget, passing the screenshot to it.
            # The selector will display this pixmap as a "frozen" image of the screen.
            self.selector = ScreenSelector(screenshot_pixmap)
            self.selector.selection_complete.connect(self.process_screen_selection)
            
            # 4. Show the selector overlay.
            self.selector.show()
            
        except Exception as e:
            if status_bar:
                status_bar.showMessage(f"截屏错误: {str(e)}")
            log.error(f"Screen capture error: {e}", exc_info=True)
    
    def process_screen_selection(self, rect: QRect):
        """
        Processes the selected QRect from the ScreenSelector, crops the original
        full-screen capture, and initiates the translation process.
        """
        try:
            if not self.current_screenshot:
                log.error("process_screen_selection called but no screenshot is available.")
                return

            self.last_selection_rect = rect
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("正在识别文本...")

            # Adjust for High-DPI displays. The QRect from the selector is in logical
            # pixels, while the screenshot from pyautogui is in physical pixels.
            screen = self.selector.screen() if self.selector else QGuiApplication.primaryScreen()
            pixel_ratio = screen.devicePixelRatio() if screen else 1.0

            # Define the crop box in physical pixels for the PIL image.
            crop_box = (
                int(rect.x() * pixel_ratio),
                int(rect.y() * pixel_ratio),
                int((rect.x() + rect.width()) * pixel_ratio),
                int((rect.y() + rect.height()) * pixel_ratio)
            )

            # Crop the original full-screen PIL image using the calculated box.
            cropped_screenshot = self.current_screenshot.crop(crop_box)

            # Clear the reference to the large screenshot to free up memory.
            self.current_screenshot = None

            # Start the background translation process with the cropped image.
            self.start_translation(screenshot=cropped_screenshot)
                
        except Exception as e:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"处理截图时出错: {str(e)}")
            log.error(f"Screen selection processing error: {e}", exc_info=True)
            # Ensure the screenshot is cleared even on error
            self.current_screenshot = None
    
    def translate_text(self):
        """Translate the text currently in the source_text box."""
        source_text = self.source_text.toPlainText()
        if not source_text.strip():
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("没有文本可翻译")
            return
        
        # Start the background translation process
        self.start_translation(text_to_translate=source_text)
    
    def toggle_floating_window(self):
        """Toggle floating translation window."""
        if self.floating_window.isVisible():
            self.floating_window.hide()
            self.toggle_floating.setText("显示悬浮窗")
        else:
            if self.last_selection_rect is not None:
                self.floating_window.show_at(self.last_selection_rect)
            else:
                self.floating_window.show()  # Fallback to just showing it
            self.toggle_floating.setText("隐藏悬浮窗")
    
    def update_ocr_language(self, language):
        """Update OCR language setting."""
        self.ocr_engine.set_language(language)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage(f"OCR语言设置为 {language}")
    
    def update_target_language(self, language):
        """Update target language setting."""
        settings.set("translation", "target_language", language)
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage(f"目标语言设置为 {language}")
    
    def add_to_vocabulary(self):
        """Add current translation from the main window to the vocabulary book."""
        source_text = self.source_text.toPlainText().strip()
        translated_text = self.translated_text.toPlainText().strip()
        self.add_text_to_vocabulary(source_text, translated_text)

    def add_floating_to_vocabulary(self, collection_name: str, source_text: str, translated_text: str):
        """Add translation from the floating window to the specified vocabulary book."""
        self.add_text_to_vocabulary(source_text, translated_text, collection_name=collection_name)

    def add_text_to_vocabulary(self, source_text: str, translated_text: str, collection_name: Optional[str] = None):
        """Generic method to add text pair to a specific vocabulary book."""
        if not source_text or not translated_text:
            QMessageBox.warning(self, "无法添加", "没有可添加到词汇本的原文或译文。")
            return

        # If no collection is specified (e.g., from main window button), use the one from the vocab view
        if not collection_name:
            collection_name = self.vocabulary_view.current_collection_name
        
        if not collection_name:
            QMessageBox.warning(self, "无词汇本", "请先在“词汇本”标签页中选择或创建一个词汇本。")
            return

        try:
            # Configure embedding provider before adding
            api_key = self.embedding_api_key_input.text().strip()
            base_url = self.embedding_base_url_input.text().strip()
            model = self.embedding_model_combo.currentText().strip()

            if not all([api_key, base_url, model]):
                QMessageBox.warning(self, "Embedding配置不完整", "请在“设置”中完整填写Embedding服务的API密钥、Base URL和模型。")
                return

            self.vocabulary_db.configure_embedding_provider(
                api_key=api_key,
                base_url=base_url,
                model=model
            )
            
            # Add to the selected vocabulary collection
            self.vocabulary_db.add_entry(
                collection_name=collection_name,
                original_text=source_text,
                translation=translated_text,
                metadata={
                    "source_lang": settings.get("translation", "source_language", "auto"),
                    "target_lang": self.target_language.currentText()
                }
            )
            
            # Refresh vocabulary view if it's showing the collection we added to
            if self.vocabulary_view.current_collection_name == collection_name:
                self.vocabulary_view.load_entries()
            
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"已添加到词汇本 '{collection_name}'", 5000)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加到词汇本时出错: {e}")
            log.error(f"Error adding to vocabulary: {e}", exc_info=True)
    
    def test_api_connection(self):
        """Test API connection with current settings."""
        api_key = self.api_key_input.text().strip()
        region = self.region_input.text().strip()
        service = self.api_service.currentText()
        
        if not api_key:
            self.api_status_label.setText("❌ 请输入API密钥")
            return
        
        # Show progress
        self.api_test_progress.setVisible(True)
        self.api_test_progress.setRange(0, 0)  # Indeterminate progress
        self.test_api_button.setEnabled(False)
        self.api_status_label.setText("🔄 测试中...")
        
        # Create and start test thread
        self.api_test_thread = APITestThread(api_key, region, service)
        self.api_test_thread.test_completed.connect(self.on_api_test_completed)
        self.api_test_thread.start()
    
    def on_api_test_completed(self, success, message):
        """Handle API test completion."""
        self.api_test_progress.setVisible(False)
        self.test_api_button.setEnabled(True)
        
        if success:
            self.api_status_label.setText(f"✅ {message}")
        else:
            self.api_status_label.setText(f"❌ {message}")

    def test_llm_connection(self):
        """Test LLM API connection with current settings."""
        api_key = self.llm_api_key_input.text().strip()
        base_url = self.llm_base_url_input.text().strip()
        model = self.llm_model_combo.currentText().strip()

        if not all([api_key, base_url, model]):
            self.llm_api_status_label.setText("❌ 请填写所有LLM设置")
            return

        self.llm_api_test_progress.setVisible(True)
        self.llm_api_test_progress.setRange(0, 0)
        self.llm_test_api_button.setEnabled(False)
        self.llm_api_status_label.setText("🔄 测试中...")

        self.llm_test_thread = LLMTestThread(api_key, base_url, model)
        self.llm_test_thread.test_completed.connect(self.on_llm_test_completed)
        self.llm_test_thread.start()

    def on_llm_test_completed(self, success, message):
        """Handle LLM API test completion."""
        self.llm_api_test_progress.setVisible(False)
        self.llm_test_api_button.setEnabled(True)

        if success:
            self.llm_api_status_label.setText(f"✅ {message}")
        else:
            self.llm_api_status_label.setText(f"❌ {message}")

    def test_embedding_connection(self):
        """Test Embedding API connection with current settings."""
        api_key = self.embedding_api_key_input.text().strip()
        base_url = self.embedding_base_url_input.text().strip()
        model = self.embedding_model_combo.currentText().strip()

        if not all([api_key, base_url, model]):
            self.embedding_api_status_label.setText("❌ 请填写所有Embedding设置")
            return

        self.embedding_api_test_progress.setVisible(True)
        self.embedding_api_test_progress.setRange(0, 0)
        self.embedding_test_api_button.setEnabled(False)
        self.embedding_api_status_label.setText("🔄 测试中...")

        self.embedding_test_thread = EmbeddingTestThread(api_key, base_url, model)
        self.embedding_test_thread.test_completed.connect(self.on_embedding_test_completed)
        self.embedding_test_thread.start()

    def on_embedding_test_completed(self, success, message):
        """Handle Embedding API test completion."""
        self.embedding_api_test_progress.setVisible(False)
        self.embedding_test_api_button.setEnabled(True)

        if success:
            self.embedding_api_status_label.setText(f"✅ {message}")
        else:
            self.embedding_api_status_label.setText(f"❌ {message}")

    def update_rag_vocab_list(self):
        """Updates the RAG vocabulary dropdown list in LLM settings."""
        try:
            if hasattr(self, 'llm_rag_vocab_combo'):
                current_selection = self.llm_rag_vocab_combo.currentText()
                self.llm_rag_vocab_combo.clear()
                self.llm_rag_vocab_combo.addItem("无")
                collections = self.vocabulary_db.list_collections()
                collection_names = [c['name'] for c in collections]
                self.llm_rag_vocab_combo.addItems(collection_names)

                # Restore previous selection if it still exists
                index = self.llm_rag_vocab_combo.findText(current_selection)
                if index != -1:
                    self.llm_rag_vocab_combo.setCurrentIndex(index)
        except Exception as e:
            log.error(f"Failed to update RAG vocabulary list: {e}", exc_info=True)

    def on_manual_add_requested(self, original_text: str, translated_text: str):
        """Handles the request to manually add an entry from the vocabulary view."""
        self.add_text_to_vocabulary(original_text, translated_text)

    def on_rag_vocab_changed(self, name: str):
        """Validates Embedding configuration when RAG vocabulary selection changes."""
        try:
            if name and name != "无":
                api_key_ok = bool(self.embedding_api_key_input.text().strip())
                base_url_ok = bool(self.embedding_base_url_input.text().strip())
                model_ok = bool(self.embedding_model_combo.currentText().strip())
                if not (api_key_ok and base_url_ok and model_ok):
                    QMessageBox.warning(self, "Embedding未配置", "选择RAG词汇本需要先完成Embedding服务的API密钥、Base URL和模型配置。")
                    self.llm_rag_vocab_combo.blockSignals(True)
                    self.llm_rag_vocab_combo.setCurrentText("无")
                    self.llm_rag_vocab_combo.blockSignals(False)
        except Exception as e:
            log.error(f"RAG vocab change validation failed: {e}", exc_info=True)

    def on_embedding_config_requested(self):
        """Configures the embedding provider before the vocabulary view saves changes."""
        try:
            api_key = self.embedding_api_key_input.text().strip()
            base_url = self.embedding_base_url_input.text().strip()
            model = self.embedding_model_combo.currentText().strip()

            if not all([api_key, base_url, model]):
                QMessageBox.warning(self, "Embedding配置不完整", "保存失败：请在“设置”中完整填写Embedding服务的API密钥、Base URL和模型。")
                # We can't easily stop the save process in vocabulary_view from here,
                # but we can prevent the configuration call.
                raise ValueError("Incomplete embedding configuration.")

            self.vocabulary_db.configure_embedding_provider(
                api_key=api_key,
                base_url=base_url,
                model=model
            )
        except Exception as e:
            log.error(f"Failed to configure embedding provider for saving: {e}")
            # The vocabulary_view will still attempt to save, but it will fail
            # in the embedding step and show its own error.

    def on_collections_changed(self):
        """Updates the floating window's collection list when vocabulary books change."""
        try:
            collections = self.vocabulary_db.list_collections()
            self.floating_window.update_collections(collections)
        except Exception as e:
            log.error(f"Failed to update floating window collections: {e}", exc_info=True)
    
    def mark_settings_dirty(self, *args, **kwargs):
        """Mark settings as dirty when a field changes (unless loading)."""
        if getattr(self, "_loading_settings", False):
            return
        self._settings_dirty = True

    def on_tab_changed(self, index: int):
        """Prompt to save Settings when leaving the Settings tab with unsaved changes."""
        try:
            if getattr(self, "_blocking_tab_change", False):
                return
            # If leaving settings tab
            if hasattr(self, 'settings_tab_index') and self._last_tab_index == self.settings_tab_index and index != self.settings_tab_index:
                if getattr(self, "_settings_dirty", False):
                    reply = QMessageBox.question(
                        self,
                        "保存更改",
                        "设置已更改，是否在离开前保存？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Yes
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        self.save_settings()
                        self._settings_dirty = False
                    elif reply == QMessageBox.StandardButton.No:
                        # Discard changes by reloading from persisted settings
                        self.load_settings_to_ui()
                        self._settings_dirty = False
                    else:
                        # Cancel tab change
                        self._blocking_tab_change = True
                        try:
                            self.tabs.setCurrentIndex(self.settings_tab_index)
                        finally:
                            self._blocking_tab_change = False
                        return
            # Update last tab index after handling
            self._last_tab_index = index
        except Exception as e:
            log.error(f"Error handling tab change: {e}", exc_info=True)

    def save_settings(self):
        """Save all settings to configuration."""
        try:
            # Translation settings
            settings.set("translation", "service", self.api_service.currentText())
            settings.set("translation", "api_key", self.api_key_input.text().strip())
            settings.set("translation", "region", self.region_input.text().strip())
            settings.set("translation", "source_language", self.source_lang_combo.currentText())
            settings.set("translation", "target_language", self.target_lang_combo.currentText())
            
            # Mark clean before operations that may trigger change signals
            self._settings_dirty = False

            # Embedding settings
            settings.set("embedding", "provider", self.embedding_provider_combo.currentText())
            settings.set("embedding", "api_key", self.embedding_api_key_input.text().strip())
            settings.set("embedding", "base_url", self.embedding_base_url_input.text().strip())
            settings.set("embedding", "model", self.embedding_model_combo.currentText().strip())

            # LLM settings
            settings.set("llm", "provider", self.llm_provider_combo.currentText())
            settings.set("llm", "api_key", self.llm_api_key_input.text().strip())
            settings.set("llm", "base_url", self.llm_base_url_input.text().strip())
            settings.set("llm", "model", self.llm_model_combo.currentText().strip())
            settings.set("llm", "rag_vocabulary", self.llm_rag_vocab_combo.currentText())

            # Save last selection
            if self.last_selection_rect is not None:
                settings.set("general", "last_selection", [self.last_selection_rect.x(), self.last_selection_rect.y(), self.last_selection_rect.width(), self.last_selection_rect.height()])

            # OCR settings
            settings.set("ocr", "language", self.ocr_lang_combo.currentText())
            settings.set("ocr", "tesseract_path", self.tesseract_path_input.text().strip() or None)
            
            # UI settings
            settings.set("ui", "theme", self.theme_combo.currentText())
            settings.set("ui", "floating_window_opacity", self.opacity_spin.value() / 100.0)
            
            # Hotkey settings
            settings.set("hotkeys", "capture", self.capture_hotkey_input.text().strip())
            settings.set("hotkeys", "translate", self.translate_hotkey_input.text().strip())
            settings.set("hotkeys", "toggle_window", self.toggle_hotkey_input.text().strip())
            settings.set("hotkeys", "save_vocabulary", self.save_vocab_hotkey_input.text().strip())
            
            # Update hotkeys
            self.hotkey_manager.update_hotkeys()
            
            # Update translator instance
            self.translator = get_translator()
            
            # Update OCR language
            self.ocr_engine.set_language(self.ocr_lang_combo.currentText())
            
            # Update target language in main tab
            current_target = self.target_language.currentText()
            new_target = self.target_lang_combo.currentText()
            if current_target != new_target:
                # Find and set the new target language in main tab
                index = self.target_language.findText(new_target)
                if index >= 0:
                    self.target_language.setCurrentIndex(index)
            
            # Show success message
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("设置已保存", 3000)

            if self.llm_rag_vocab_combo.currentText() != "无":
                api_key_ok = bool(self.embedding_api_key_input.text().strip())
                base_url_ok = bool(self.embedding_base_url_input.text().strip())
                model_ok = bool(self.embedding_model_combo.currentText().strip())
                if not (api_key_ok and base_url_ok and model_ok):
                    QMessageBox.warning(self, "Embedding未配置", "已选择RAG词汇本，但Embedding配置不完整。请完善Embedding设置以启用RAG。")
            
            QMessageBox.information(self, "设置", "设置已成功保存！")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置时出错：{str(e)}")
    
    def reset_settings(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self, "重置设置", 
            "确定要重置所有设置为默认值吗？这将清除您的API密钥等配置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Reset to defaults
                settings.current = settings.defaults.copy()
                settings.save()
                
                # Update UI with default values
                self.load_settings_to_ui()
                
                QMessageBox.information(self, "重置完成", "设置已重置为默认值！")
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"重置设置时出错：{str(e)}")
    
    def load_settings_to_ui(self):
        """Load current settings to UI elements."""
        self._loading_settings = True
        try:
            # Translation settings
            self.api_service.setCurrentText(str(settings.get("translation", "service", "microsoft")))
            self.api_key_input.setText(str(settings.get("translation", "api_key", "")))
            self.region_input.setText(str(settings.get("translation", "region", "global")))
            self.source_lang_combo.setCurrentText(str(settings.get("translation", "source_language", "auto")))
            self.target_lang_combo.setCurrentText(str(settings.get("translation", "target_language", "zh-CN")))
        finally:
            self._loading_settings = False
            self._settings_dirty = False

        # Embedding settings
        embedding_provider_name = str(settings.get("embedding", "provider", "自定义..."))
        self.embedding_provider_combo.setCurrentText(embedding_provider_name)
        self.on_embedding_provider_changed(embedding_provider_name)
        self.embedding_api_key_input.setText(str(settings.get("embedding", "api_key", "")))
        embedding_provider = self.embedding_provider_manager.get_provider_by_name(embedding_provider_name)
        if embedding_provider and embedding_provider.get("id") == "custom":
            self.embedding_base_url_input.setText(str(settings.get("embedding", "base_url", "")))
            self.embedding_model_combo.setCurrentText(str(settings.get("embedding", "model", "")))
        else:
            self.embedding_model_combo.setCurrentText(str(settings.get("embedding", "model", "")))
        self._settings_dirty = False

        # LLM settings
        # Load and set the provider first, as it drives the UI state
        provider_name = str(settings.get("llm", "provider", "自定义..."))
        self.llm_provider_combo.setCurrentText(provider_name)
        self.on_llm_provider_changed(provider_name) # Manually trigger update

        self.llm_api_key_input.setText(str(settings.get("llm", "api_key", "")))
        
        # Only load custom URL/Model if the saved provider is "custom"
        provider = self.llm_provider_manager.get_provider_by_name(provider_name)
        if provider and provider.get("id") == "custom":
            self.llm_base_url_input.setText(str(settings.get("llm", "base_url", "")))
            self.llm_model_combo.setCurrentText(str(settings.get("llm", "model", "")))
        else: # Otherwise, use the model from settings, which might be a custom one
             self.llm_model_combo.setCurrentText(str(settings.get("llm", "model", "")))

        if hasattr(self, 'llm_rag_vocab_combo'):
            self.llm_rag_vocab_combo.setCurrentText(str(settings.get("llm", "rag_vocabulary", "无")))


        # OCR settings
        self.ocr_lang_combo.setCurrentText(str(settings.get("ocr", "language", "eng")))
        self.tesseract_path_input.setText(str(settings.get("ocr", "tesseract_path", "") or ""))
        
        # UI settings
        # Set theme without triggering the signal, as it's already applied in __init__
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentText(str(settings.get("ui", "theme", "dark")))
        self.theme_combo.blockSignals(False)
        try:
            opacity_setting = settings.get("ui", "floating_window_opacity", 0.8)
            if isinstance(opacity_setting, (int, float, str)):
                opacity_value = float(opacity_setting)
                self.opacity_spin.setValue(int(opacity_value * 100))
            else:
                self.opacity_spin.setValue(80)
        except (ValueError, TypeError):
            self.opacity_spin.setValue(80) # Fallback to default
        
        # Hotkey settings
        self.capture_hotkey_input.setText(str(settings.get("hotkeys", "capture", "alt+q")))
        self.translate_hotkey_input.setText(str(settings.get("hotkeys", "translate", "alt+w")))
        self.toggle_hotkey_input.setText(str(settings.get("hotkeys", "toggle_window", "ctrl+shift+space")))
        self.save_vocab_hotkey_input.setText(str(settings.get("hotkeys", "save_vocabulary", "ctrl+s")))
        
        # Done loading
        self._settings_dirty = False

        # Load last selection
        rect_coords = settings.get("general", "last_selection")
        if isinstance(rect_coords, list) and len(rect_coords) == 4:
            try:
                # Ensure all coords are integers before creating QRect
                x, y, w, h = [int(c) for c in rect_coords]
                self.last_selection_rect = QRect(x, y, w, h)
            except (ValueError, TypeError):
                self.last_selection_rect = None # Reset if coords are invalid
        
        # Reset API status
        self.api_status_label.setText("未测试")
        if hasattr(self, 'llm_api_status_label'):
            self.llm_api_status_label.setText("未测试")
        if hasattr(self, 'embedding_api_status_label'):
            self.embedding_api_status_label.setText("未测试")
    
    def start_translation(self, screenshot=None, text_to_translate=None):
        """
        Starts the TranslationWorker thread to perform OCR and/or translation.
        """
        if self.translation_worker and self.translation_worker.isRunning():
            log.warning("Translation is already in progress.")
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("翻译任务已在进行中", 3000)
            return

        # --- UI Feedback: Show "in progress" state ---
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("正在处理...")
        self.translate_button.setEnabled(False)
        self.capture_button.setEnabled(False)

        target_lang = self.target_language.currentText()

        # --- Prepare RAG context if using LLM ---
        service = settings.get("translation", "service")
        rag_vocab_name: Optional[str] = None
        if service == "llm":
            rag_vocab_name_setting = settings.get("llm", "rag_vocabulary", "无")
            rag_vocab_name = str(rag_vocab_name_setting) if rag_vocab_name_setting else "无"
            if rag_vocab_name == "无":
                rag_vocab_name = None
            else:
                api_key_ok = bool(self.embedding_api_key_input.text().strip())
                base_url_ok = bool(self.embedding_base_url_input.text().strip())
                model_ok = bool(self.embedding_model_combo.currentText().strip())
                if not (api_key_ok and base_url_ok and model_ok):
                    QMessageBox.warning(self, "Embedding未配置", "已选择RAG词汇本，但Embedding配置不完整。请在设置中完成Embedding配置后再试。")
                    rag_vocab_name = None
        
        vocabulary_db = self.vocabulary_db if rag_vocab_name else None

        # --- Create and configure worker ---
        if screenshot is not None:
            self.translation_worker = TranslationWorker(
                translator=self.translator,
                target_lang=target_lang,
                ocr_engine=self.ocr_engine,
                screenshot=screenshot,
                vocabulary_db=vocabulary_db,
                rag_vocabulary_name=rag_vocab_name
            )
        elif text_to_translate:
            self.translation_worker = TranslationWorker(
                translator=self.translator,
                target_lang=target_lang,
                text_to_translate=text_to_translate,
                vocabulary_db=vocabulary_db,
                rag_vocabulary_name=rag_vocab_name
            )
        else:
            # Restore UI if there's no valid task
            if status_bar:
                status_bar.showMessage("没有翻译任务", 3000)
            self.translate_button.setEnabled(True)
            self.capture_button.setEnabled(True)
            return

        # --- Connect signals from worker to main thread slots ---
        self.translation_worker.translation_successful.connect(self.on_translation_successful)
        self.translation_worker.translation_failed.connect(self.on_translation_failed)
        # Connect the finished signal to our cleanup slot
        self.translation_worker.finished.connect(self.on_translation_finished)

        # --- Start the thread ---
        self.translation_worker.start()

    def on_translation_successful(self, original_text, translated_text):
        """
        Slot to handle the successful completion of the translation worker.
        This runs in the main GUI thread.
        """
        log.info("Main thread: Received successful translation.")
        # Update UI text boxes
        self.source_text.setText(original_text)
        self.translated_text.setText(translated_text)
        
        # Update and show the floating window
        self.floating_window.set_content(original_text, translated_text)
        if self.last_selection_rect is not None:
            self.floating_window.show_at(self.last_selection_rect)
        else:
            self.floating_window.show()

        # --- Restore UI from "in progress" state ---
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("翻译完成", 5000)
        self.translate_button.setEnabled(True)
        self.capture_button.setEnabled(True)

    def on_translation_failed(self, error_message):
        """
        Slot to handle the failure of the translation worker.
        This runs in the main GUI thread.
        """
        log.error(f"Main thread: Received translation failure: {error_message}")
        # Show error in status bar
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage(error_message, 8000)
        
        # --- Restore UI from "in progress" state ---
        self.translate_button.setEnabled(True)
        self.capture_button.setEnabled(True)

    def on_translation_finished(self):
        """
        Slot to handle the QThread.finished signal.
        Schedules the worker for deletion and cleans up the reference.
        """
        log.info("Translation worker has finished, cleaning up.")
        if self.translation_worker:
            self.translation_worker.deleteLater()
            self.translation_worker = None

    def show_api_help(self):
        """Show help dialog for getting API keys."""
        help_text = """
<h3>如何获取微软翻译API密钥</h3>

<h4>1. 创建Azure账户</h4>
<p>• 访问 <a href="https://portal.azure.com/">Azure Portal</a></p>
<p>• 注册新账户（通常有12个月免费试用）</p>

<h4>2. 创建翻译器资源</h4>
<p>• 登录Azure Portal后，点击"+ 创建资源"</p>
<p>• 搜索"Translator"并选择</p>
<p>• 配置资源：</p>
<p>&nbsp;&nbsp;- 资源组：创建新的（如：gametranslator-rg）</p>
<p>&nbsp;&nbsp;- 区域：选择"East Asia"（亚洲东部）</p>
<p>&nbsp;&nbsp;- 名称：如 gametranslator-api</p>
<p>&nbsp;&nbsp;- 定价层：选择"Free F0"（每月200万字符免费）</p>

<h4>3. 获取密钥信息</h4>
<p>• 创建完成后，进入您的翻译器资源</p>
<p>• 左侧菜单 → "密钥和端点"</p>
<p>• 复制"密钥1"和"位置/区域"</p>

<h4>4. 在本程序中配置</h4>
<p>• API密钥：粘贴您复制的密钥1</p>
<p>• 区域：输入位置/区域（如：eastasia）</p>
<p>• 点击"测试API连接"验证配置</p>

<p><b>注意：</b>免费层每月有200万字符的限制，对于个人使用通常足够。</p>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("API密钥获取帮助")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def closeEvent(self, event: Optional[QCloseEvent]) -> None:
        """
        Handle window close event to gracefully stop background threads.
        """
        log.info("Main window is closing. Stopping background services.")
        # Stop hotkey listener
        if hasattr(self, 'hotkey_manager') and self.hotkey_manager:
            self.hotkey_manager.stop_listener()
        
        if event:
            event.accept()


class LLMTestThread(QThread):
    """Thread for testing LLM API connection."""
    test_completed = Signal(bool, str)

    def __init__(self, api_key, base_url, model):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self):
        """Run LLM API test."""
        try:
            # Use a common endpoint for listing models, which is supported by many OpenAI-compatible APIs
            # and serves as a good, lightweight connection test.
            endpoint = f"{self.base_url.rstrip('/')}/models"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            response = requests.get(endpoint, headers=headers, timeout=10)
            
            if response.status_code == 200:
                try:
                    models_data = response.json()
                    # Check if the specified model is in the list of available models
                    if 'data' in models_data and any(m.get('id') == self.model for m in models_data['data']):
                        self.test_completed.emit(True, f"连接成功, 模型 '{self.model}' 可用")
                    else:
                        self.test_completed.emit(True, f"连接成功, 但未在列表中找到模型 '{self.model}' (可能仍可用)")
                except (requests.exceptions.JSONDecodeError, KeyError):
                    self.test_completed.emit(True, "连接成功 (无法验证模型列表)")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    if 'error' in error_detail and 'message' in error_detail['error']:
                        error_msg += f": {error_detail['error']['message']}"
                except requests.exceptions.JSONDecodeError:
                    pass # Keep the simple HTTP status code error
                self.test_completed.emit(False, error_msg)

        except requests.exceptions.Timeout:
            self.test_completed.emit(False, "连接超时")
        except requests.exceptions.ConnectionError as e:
            self.test_completed.emit(False, f"连接错误: {e}")
        except Exception as e:
            self.test_completed.emit(False, f"未知错误: {e}")


class APITestThread(QThread):
    """Thread for testing API connection without blocking UI."""
    
    test_completed = Signal(bool, str)  # success, message
    
    def __init__(self, api_key, region, service):
        super().__init__()
        self.api_key = api_key
        self.region = region
        self.service = service
    
    def run(self):
        """Run API test in background thread."""
        if self.service == "microsoft":
            self.test_microsoft_translator()
        else:
            self.test_completed.emit(False, f"不支持测试 {self.service} 服务")

    def test_microsoft_translator(self):
        """Tests the Microsoft Translator API."""
        try:
            endpoint = "https://api.cognitive.microsofttranslator.com/translate"
            params = {
                'api-version': '3.0',
                'from': 'en',
                'to': 'zh-CN'
            }
            
            headers = {
                'Ocp-Apim-Subscription-Key': self.api_key,
                'Ocp-Apim-Subscription-Region': self.region,
                'Content-type': 'application/json'
            }
            
            body = [{'text': 'Hello'}]
            
            response = requests.post(
                endpoint, 
                params=params,
                headers=headers,
                json=body,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result and len(result) > 0:
                    translated = result[0]['translations'][0]['text']
                    self.test_completed.emit(True, f"连接成功！测试翻译：Hello → {translated}")
                else:
                    self.test_completed.emit(False, "API响应格式异常")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    if 'error' in error_detail:
                        error_msg += f": {error_detail['error'].get('message', '未知错误')}"
                except:
                    pass
                self.test_completed.emit(False, error_msg)
                
        except requests.exceptions.Timeout:
            self.test_completed.emit(False, "连接超时，请检查网络")
        except requests.exceptions.ConnectionError:
            self.test_completed.emit(False, "网络连接错误")
        except Exception as e:
            self.test_completed.emit(False, f"测试失败：{str(e)}")


class EmbeddingTestThread(QThread):
    """Thread for testing Embedding API connection."""
    test_completed = Signal(bool, str)

    def __init__(self, api_key, base_url, model):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self):
        """Run Embedding API test."""
        try:
            endpoint = f"{self.base_url.rstrip('/')}/embeddings"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            body = {
                "input": "test",
                "model": self.model
            }
            response = requests.post(endpoint, headers=headers, json=body, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'data' in data and len(data['data']) > 0 and 'embedding' in data['data'][0]:
                        embedding_length = len(data['data'][0]['embedding'])
                        self.test_completed.emit(True, f"连接成功, 返回 {embedding_length} 维向量")
                    else:
                        self.test_completed.emit(True, "连接成功, 但响应格式不符合预期")
                except (requests.exceptions.JSONDecodeError, KeyError, IndexError):
                    self.test_completed.emit(True, "连接成功 (无法验证响应)")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    if 'error' in error_detail and 'message' in error_detail['error']:
                        error_msg += f": {error_detail['error']['message']}"
                except requests.exceptions.JSONDecodeError:
                    pass
                self.test_completed.emit(False, error_msg)

        except requests.exceptions.Timeout:
            self.test_completed.emit(False, "连接超时")
        except requests.exceptions.ConnectionError as e:
            self.test_completed.emit(False, f"连接错误: {e}")
        except Exception as e:
            self.test_completed.emit(False, f"未知错误: {e}")