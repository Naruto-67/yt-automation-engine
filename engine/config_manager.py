# engine/config_manager.py
import os
import yaml
from typing import List, Dict, Any
from engine.logger import logger
from engine.models import ChannelConfig
from functools import lru_cache

class ConfigManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.channels_path = os.path.join(self.root_dir, "config", "channels.yaml")
        self.providers_path = os.path.join(self.root_dir, "config", "providers.yaml")
        self.settings_path = os.path.join(self.root_dir, "config", "settings.yaml")

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            logger.error(f"Missing config file: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to parse YAML {path}: {e}")
            return {}

    def get_active_channels(self) -> List[ChannelConfig]:
        data = self._load_yaml(self.channels_path)
        raw_channels = data.get("channels", [])
        active_channels = []
        for ch in raw_channels:
            if ch.get("active", False):
                active_channels.append(ChannelConfig(
                    channel_id=ch.get("id", ""),
                    channel_name=ch.get("name", ""),
                    niche=ch.get("niche", ""),
                    target_audience=ch.get("target_audience", "Global"),
                    youtube_refresh_token_env=ch.get("youtube_refresh_token_env", ""),
                    youtube_client_id_env=ch.get("youtube_client_id_env", ""),
                    youtube_client_secret_env=ch.get("youtube_client_secret_env", ""),
                    discord_webhook_env=ch.get("discord_webhook_env", ""),
                    creative_lenses=ch.get("creative_lenses", [])
                ))
        return active_channels

    def get_providers(self) -> Dict[str, Any]:
        return self._load_yaml(self.providers_path)

    @lru_cache(maxsize=1)
    def get_settings(self) -> Dict[str, Any]:
        return self._load_yaml(self.settings_path)

    def reload_channels(self):
        pass

config_manager = ConfigManager()
