"""
Global Hotkey manager for GameTranslator using pynput.GlobalHotKeys.
"""

import logging
from PySide6.QtCore import QObject, Signal, QThread
from pynput import keyboard

from src.gametranslator.config.settings import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class ListenerThread(QThread):
    """
    This thread runs pynput.keyboard.GlobalHotKeys to avoid blocking the GUI.
    It emits a signal when a registered hotkey combination is detected.
    """
    hotkey_triggered = Signal(str)

    def __init__(self, hotkeys_config):
        super().__init__()
        # hotkeys_config is a dict like {"<ctrl>+<shift>+c": "capture"}
        self.hotkeys_config = hotkeys_config
        self.listener = None
        log.info(f"ListenerThread initialized for hotkeys: {list(hotkeys_config.keys())}")

    def on_activate_factory(self, name):
        """Factory to create a callback for a specific hotkey name."""
        def on_activate():
            log.info(f"Global hotkey '{name}' detected.")
            self.hotkey_triggered.emit(name)
        return on_activate

    def run(self):
        """Start the keyboard listener."""
        log.info("Starting global hotkey listener thread.")
        
        # Map hotkey strings to their activation callbacks
        callbacks = {
            sequence: self.on_activate_factory(name)
            for sequence, name in self.hotkeys_config.items()
        }

        # GlobalHotKeys is a context manager and runs in its own thread.
        # The `join()` method will block until the listener is stopped.
        try:
            with keyboard.GlobalHotKeys(callbacks) as self.listener:
                self.listener.join()
        except Exception as e:
            # This can happen if another application has already registered the same hotkey,
            # or on Linux if the required X11 libraries are not present.
            log.error(f"Failed to register global hotkeys: {e}", exc_info=True)

        log.info("Global hotkey listener thread stopped.")

    def stop(self):
        """Stop the keyboard listener."""
        if self.listener:
            log.info("Stopping global hotkey listener thread.")
            self.listener.stop()


class HotkeyManager(QObject):
    """
    Manages global application hotkeys using pynput in a separate thread.
    """
    capture_triggered = Signal()
    translate_triggered = Signal()
    toggle_window_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.listener_thread = None
        self.setup_hotkeys()

    def _to_pynput_format(self, key_string):
        """Converts "ctrl+shift+c" to "<ctrl>+<shift>+c"."""
        parts = key_string.lower().strip().split('+')
        formatted_parts = []
        for part in parts:
            # Only wrap known modifier/special keys in angle brackets
            if part in ['ctrl', 'shift', 'alt', 'space']:
                formatted_parts.append(f'<{part}>')
            else:
                # Keep regular characters as they are
                formatted_parts.append(part)
        return '+'.join(formatted_parts)

    def setup_hotkeys(self):
        """
        Loads hotkey configurations from settings, creates, and starts the listener thread.
        """
        if self.listener_thread and self.listener_thread.isRunning():
            self.listener_thread.stop()
            self.listener_thread.wait()

        # The keys are the hotkey sequences, the values are the names of the signals to emit.
        hotkeys_to_register = {
            self._to_pynput_format(str(settings.get("hotkeys", "capture", "alt+q"))): "capture",
            self._to_pynput_format(str(settings.get("hotkeys", "translate", "alt+w"))): "translate",
            self._to_pynput_format(str(settings.get("hotkeys", "toggle_window", "ctrl+shift+space"))): "toggle_window",
        }
        
        self.listener_thread = ListenerThread(hotkeys_to_register)
        self.listener_thread.hotkey_triggered.connect(self._on_hotkey_triggered)
        self.listener_thread.start()

    def _on_hotkey_triggered(self, name):
        """
        Slot to receive signals from the listener thread and emit the corresponding
        public signal. This ensures the final signal is emitted in the main GUI thread.
        """
        if name == "capture":
            self.capture_triggered.emit()
        elif name == "translate":
            self.translate_triggered.emit()
        elif name == "toggle_window":
            self.toggle_window_triggered.emit()
            
    def update_hotkeys(self):
        """Public method to reload hotkeys from settings."""
        log.info("Updating hotkeys...")
        self.setup_hotkeys()

    def stop_listener(self):
        """Public method to explicitly stop the listener thread."""
        if self.listener_thread and self.listener_thread.isRunning():
            self.listener_thread.stop()
            self.listener_thread.wait()