"""
Manages Embedding provider configurations.
"""
import json
import os
from typing import List, Dict, Any, Optional

class EmbeddingProviderManager:
    """
    Handles loading, saving, and managing Embedding provider templates
    from a JSON configuration file.
    """
    def __init__(self, config_path: str = "src/gametranslator/config/embedding_providers.json"):
        self.config_path = config_path
        self.providers: List[Dict[str, Any]] = []
        self.load_providers()

    def load_providers(self):
        """Loads provider configurations from the JSON file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.providers = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading provider config: {e}")
                self.providers = []
        else:
            print(f"Provider config file not found at: {self.config_path}")
            self.providers = []

    def save_providers(self):
        """Saves the current provider configurations to the JSON file."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.providers, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"Error saving provider config: {e}")

    def get_provider_by_id(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """Finds a provider by its unique ID."""
        return next((p for p in self.providers if p.get("id") == provider_id), None)

    def get_provider_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Finds a provider by its display name."""
        return next((p for p in self.providers if p.get("name") == name), None)

    def add_provider(self, name: str, base_url: str, models: List[str]) -> bool:
        """Adds a new custom provider template."""
        if self.get_provider_by_name(name):
            print(f"Provider with name '{name}' already exists.")
            return False

        provider_id = name.lower().replace(" ", "_").strip()
        if self.get_provider_by_id(provider_id):
            i = 1
            while self.get_provider_by_id(f"{provider_id}_{i}"):
                i += 1
            provider_id = f"{provider_id}_{i}"

        new_provider = {
            "id": provider_id,
            "name": name,
            "base_url": base_url,
            "models": models,
            "deletable": True
        }
        self.providers.append(new_provider)
        self.save_providers()
        return True

    def delete_provider(self, provider_id: str) -> bool:
        """Deletes a provider by its ID, if it's deletable."""
        provider = self.get_provider_by_id(provider_id)
        if provider and provider.get("deletable", False):
            self.providers = [p for p in self.providers if p.get("id") != provider_id]
            self.save_providers()
            return True
        return False

    def get_provider_names(self) -> List[str]:
        """Returns a list of all provider display names."""
        return [p.get("name", "Unknown") for p in self.providers]