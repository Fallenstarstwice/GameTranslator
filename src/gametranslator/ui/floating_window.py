"""
Floating window UI for GameTranslator.
"""
import platform
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QPushButton, QHBoxLayout, QComboBox
from PySide6.QtCore import Qt, QRect, Signal, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QMouseEvent, QShowEvent
from typing import List, Dict, Any

from src.gametranslator.config.settings import settings

if platform.system() == "Windows":
    try:
        import win32gui
        import win32con
    except ImportError:
        win32gui = None
        win32con = None
else:
    win32gui = None
    win32con = None


class NoFocusComboBox(QComboBox):
    """自定义下拉菜单，防止抢占焦点"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
    def showPopup(self):
        """重写showPopup方法，确保弹出窗口不抢占焦点"""
        super().showPopup()
        # 获取弹出窗口并设置不抢占焦点
        popup = self.findChild(QWidget)
        if popup and platform.system() == "Windows" and win32gui and win32con:
            hwnd = popup.winId()
            if hwnd:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_NOACTIVATE)


class FloatingWindow(QWidget):
    """Floating translation window that does not steal focus."""
    
    add_to_vocabulary_requested = Signal(str, str, str)

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # 设置窗口不获取焦点
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        try:
            opacity_setting = settings.get("ui", "floating_window_opacity", 0.8)
            opacity = float(opacity_setting)
        except (ValueError, TypeError):
            opacity = 0.8
        self.setWindowOpacity(opacity)

        self.setMinimumWidth(200)
        self.setMaximumWidth(600)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title bar
        title_bar_layout = QHBoxLayout()
        title_label = QLabel("GameTranslator")
        title_label.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #AAA;")

        self.close_button = QPushButton("X")
        self.close_button.setFixedSize(20, 20)
        self.close_button.setStyleSheet("""
            QPushButton { 
                background-color: #555; 
                color: #FFF; 
                border-radius: 10px; 
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
            QPushButton:pressed {
                background-color: #999;
            }
        """)
        self.close_button.clicked.connect(self.hide)

        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch()
        title_bar_layout.addWidget(self.close_button)

        self.main_layout.addLayout(title_bar_layout)

        self.setStyleSheet("""
            QWidget { background-color: #333; color: #FFF; border-radius: 8px; }
            QLabel { padding: 5px; }
            QComboBox { border: 1px solid #555; border-radius: 3px; }
        """)

        self.source_label = QLabel()
        self.source_label.setFont(QFont("Arial", 10))
        self.source_label.setWordWrap(True)
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.source_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.main_layout.addWidget(separator)

        self.translated_label = QLabel()
        self.translated_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.translated_label.setWordWrap(True)
        self.translated_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.translated_label)

        button_layout = QHBoxLayout()
        
        # 创建自定义的不抢占焦点的下拉菜单
        self.collection_combo = NoFocusComboBox()
        button_layout.addWidget(self.collection_combo)

        self.add_button = QPushButton("添加")
        self.add_button.clicked.connect(self.on_add_to_vocab_clicked)
        button_layout.addWidget(self.add_button)
        self.main_layout.addLayout(button_layout)

        self.old_pos = None

    def update_collections(self, collections: List[Dict[str, Any]]):
        """Populates the collections combobox."""
        current_selection = self.collection_combo.currentText()
        self.collection_combo.clear()
        if not collections:
            self.collection_combo.addItem("无词汇本")
            self.collection_combo.setEnabled(False)
            self.add_button.setEnabled(False)
        else:
            for coll in collections:
                self.collection_combo.addItem(coll['name'])
            self.collection_combo.setEnabled(True)
            self.add_button.setEnabled(True)
            
            index = self.collection_combo.findText(current_selection)
            if index != -1:
                self.collection_combo.setCurrentIndex(index)

    def on_add_to_vocab_clicked(self):
        """Emits a signal with the current content and selected collection."""
        collection_name = self.collection_combo.currentText()
        source = self.source_label.text()
        translated = self.translated_label.text()

        if source and translated and collection_name and collection_name != "无词汇本":
            self.add_to_vocabulary_requested.emit(collection_name, source, translated)
            self.add_button.setText("已添加!")
            QTimer.singleShot(1500, lambda: self.add_button.setText("添加"))

    def set_content(self, source_text: str, translated_text: str):
        """Set the source and translated text to display."""
        self.source_label.setText(source_text)
        self.translated_label.setText(translated_text)
        self.adjustSize()

    def show_at(self, rect: QRect):
        """Show the window positioned relative to the given rectangle."""
        self.adjustSize()
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()

        target_x = rect.x() + (rect.width() - self.width()) // 2
        target_y = rect.y() - self.height() - 10

        if target_y < screen_geometry.y():
            target_y = rect.y() + rect.height() + 10

        target_x = max(screen_geometry.x(), min(target_x, screen_geometry.right() - self.width()))

        self.move(target_x, target_y)
        self.show()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if platform.system() == "Windows" and win32gui and win32con:
            hwnd = self.winId()
            if hwnd:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_NOACTIVATE)