"""
Settings management for GameTranslator.
"""

import os
import yaml
from pathlib import Path


class Settings:
    """Manages application settings."""
    
    def __init__(self):
        """Initialize settings with default values."""
        self.config_dir = Path.home() / ".gametranslator"
        self.config_file = self.config_dir / "config.yaml"
        
        # Default settings
        self.defaults = {
            "ui": {
                "theme": "dark",
                "floating_window_opacity": 0.8,
                "floating_window_size": [400, 300],
            },
            "ocr": {
                "language": "eng",
                "tesseract_path": None,  # Auto-detect
            },
            "translation": {
                "service": "microsoft",
                "source_language": "auto",
                "target_language": "zh-CN",
                "api_key": "Eph1qOHuivWuXnp17nVJO4bGsuJexh5FNPdr6cn2z8vdTvmaOki7JQQJ99BIACULyCpXJ3w3AAAbACOGy7c5",
            },
            "hotkeys": {
                "capture": "ctrl+shift+c",
                "translate": "ctrl+shift+t",
                "toggle_window": "ctrl+shift+space",
            },
        }
        
        # Current settings
        self.current = self.defaults.copy()
        
        # Create config directory if it doesn't exist
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Load settings if config file exists, otherwise save defaults
        if self.config_file.exists():
            self.load()
        else:
            self.save()
    
    def load(self):
        """Load settings from config file."""
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded:
                    # Update current settings with loaded values
                    self._update_dict(self.current, loaded)
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def save(self):
        """Save current settings to config file."""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(self.current, f, default_flow_style=False)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def _update_dict(self, target, source):
        """Recursively update dictionary values."""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._update_dict(target[key], value)
            else:
                target[key] = value
    
    def get(self, section, key, default=None):
        """Get a setting value."""
        try:
            return self.current[section][key]
        except KeyError:
            return default
    
    def set(self, section, key, value):
        """Set a setting value."""
        if section not in self.current:
            self.current[section] = {}
        self.current[section][key] = value
        self.save()


# Global settings instance
settings = Settings()