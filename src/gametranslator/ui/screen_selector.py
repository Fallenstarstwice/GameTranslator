"""
Screen selection tool for GameTranslator.
"""
import platform

from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap, QScreen, QMouseEvent, QKeyEvent, QPaintEvent, QShowEvent, QShortcut, QKeySequence

# Import Windows-specific libraries only on Windows
if platform.system() == "Windows":
    try:
        import win32gui
        import win32con
    except ImportError:
        print("pywin32 not installed. For optimal performance on Windows, please run: pip install pywin32")
        win32gui = None
        win32con = None


class ScreenSelector(QWidget):
    """
    A transparent overlay widget for selecting a screen region.
    It displays a pre-captured screenshot and allows the user to select a portion of it.
    """
    
    # Signal emitted when selection is complete, providing the selected QRect
    selection_complete = Signal(QRect)
    
    def __init__(self, screenshot: QPixmap, parent=None):
        """
        Initializes the selector with a full-screen screenshot.
        
        Args:
            screenshot (QPixmap): The pixmap of the screen to display.
        """
        super().__init__(parent)
        self.screenshot = screenshot
        
        # Use a robust set of window flags to create a borderless, top-most overlay
        # that does not steal focus from background applications (like games).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        # Enable transparency for custom painting
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        
        # Set the widget geometry to cover the entire screen
        screen_geometry = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geometry)
        
        # Initialize selection state
        self.selection_rect = QRect()
        self.start_point = None
        self.end_point = None
        self.is_selecting = False
        
        # Set cursor and mouse tracking
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        # Ensure widget receives keyboard focus for ESC to work
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.activateWindow()
        self.raise_()
        # Try to grab keyboard input explicitly as a fallback
        try:
            self.grabKeyboard()
        except Exception:
            pass

        # Add an explicit ESC shortcut as a fallback
        try:
            self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
            # Ensure shortcut works even if the overlay cannot take focus (NOACTIVATE)
            self._esc_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            self._esc_shortcut.activated.connect(self.close)
        except Exception:
            pass
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to start selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.pos()
            self.is_selecting = True
            self.selection_rect = QRect()
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right-click to cancel selection immediately
            self.close()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move to update selection."""
        if self.is_selecting and self.start_point is not None:
            self.end_point = event.pos()
            self.selection_rect = QRect(self.start_point, self.end_point).normalized()
            self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release to complete selection."""
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.end_point = event.pos()
            self.is_selecting = False
            
            # Create final selection rectangle
            if self.start_point is not None and self.end_point is not None:
                self.selection_rect = QRect(self.start_point, self.end_point).normalized()
                
                # Emit signal with selection
                if not self.selection_rect.isEmpty():
                    self.selection_complete.emit(self.selection_rect)
            
            # Close the selector
            self.close()
    
    def showEvent(self, event: QShowEvent):
        """
        Overrides the show event to apply Windows-specific styles right before
        the window is displayed. This is the most reliable time to do this.
        """
        super().showEvent(event)
        if platform.system() == "Windows" and win32gui and win32con:
            hwnd = self.winId()
            if hwnd:
                # Add the NOACTIVATE style. This is the key to preventing focus steal.
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_NOACTIVATE)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press to cancel selection."""
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self.close()
        else:
            super().keyPressEvent(event)
    
    def paintEvent(self, event: QPaintEvent):
        """
        Custom paint event to draw the screenshot, mask, and selection.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Draw the captured screenshot as the base layer.
        painter.drawPixmap(self.rect(), self.screenshot)

        # 2. Draw a semi-transparent dark mask over the entire screen.
        # This provides visual feedback that the app is in selection mode.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        # 3. If a selection is active, "clear" the mask in that area by
        #    drawing the original screenshot part on top and add a border.
        if not self.selection_rect.isEmpty():
            # Draw the corresponding part of the original screenshot inside the selection.
            # This makes the selected area appear bright and clear.
            dpr = self.devicePixelRatio()
            source_rect = QRect(
                self.selection_rect.left() * dpr,
                self.selection_rect.top() * dpr,
                self.selection_rect.width() * dpr,
                self.selection_rect.height() * dpr
            )
            painter.drawPixmap(self.selection_rect, self.screenshot, source_rect)

            # Draw a distinct border around the selection for clarity.
            pen = QPen(QColor(255, 0, 0, 220), 2)  # A solid, bright red
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(self.selection_rect)