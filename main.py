"""
GameTranslator - Main entry point.
"""

import sys
import ctypes
from PySide6.QtWidgets import QApplication

from src.gametranslator.ui.main_window import MainWindow


def main():
    """Main entry point for the application."""
    # Make the application DPI-aware on Windows
    if sys.platform == 'win32':
        try:
            # This is the modern way to set DPI awareness for Windows 10 and later
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            # Fallback for older Windows versions
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass  # Could not set DPI awareness

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
