# engine/config_manager.py — Ghost Engine V6
import os
import yaml
from typing import List, Dict, Any
from engine.models import ChannelConfig

# Lazy import to avoid circular imports at module load time
def _get_logger():
    from engine.logger import logger
    return logger


class ConfigManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.channels_path  = os.path.join(self.root_dir, "config", "channels.yaml")
        self.providers_path = os.path.join(self.root_dir, "config", "providers.yaml")
        self.settings_path  = os.path.join(self.root_dir, "config", "settings.yaml")
        self._channels: List[ChannelConfig] = []
        self._channels_loaded = False

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            _get_logger().error(f"Missing config file: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            _get_logger().error(f"Failed to parse YAML {path}: {e}")
            return {}

    def _load_channels(self) -> List[ChannelConfig]:
        data = self._load_yaml(self.channels_path)
        raw_channels = data.get("channels", [])
        active_channels: List[ChannelConfig] = []

        for ch in raw_channels:
            if not ch.get("active", False):
                continue

            try:
                # Pydantic uses field aliases (id → channel_id, name → channel_name)
                config = ChannelConfig.model_validate(ch)

                # Auto-discover niche if missing from YAML
                if not config.niche:
                    config = self._discover_niche(config)

                active_channels.append(config)

            except Exception as e:
                _get_logger().error(
                    f"Skipping channel '{ch.get('id', '?')}' due to schema error: {e}"
                )

        _get_logger().engine(f"Loaded {len(active_channels)} active channel(s).")
        return active_channels

    def _discover_niche(self, config: ChannelConfig) -> ChannelConfig:
        """Auto-discovers niche from YouTube history if not set in channels.yaml."""
        try:
            from scripts.youtube_manager import get_youtube_client
            from scripts.niche_discovery import discover_channel_niche, update_yaml_niche

            yt_client = get_youtube_client(config)
            if yt_client:
                discovered = discover_channel_niche(config.channel_id, yt_client)
                update_yaml_niche(config.channel_id, discovered)
                config.niche = discovered
            else:
                config.niche = "Trending Viral Shorts"
        except Exception as e:
            _get_logger().error(f"Niche discovery failed for {config.channel_id}: {e}")
            config.niche = "Trending Viral Shorts"
        return config

    def get_active_channels(self) -> List[ChannelConfig]:
        if not self._channels_loaded:
            self._channels = self._load_channels()
            self._channels_loaded = True
        return self._channels

    def reload_channels(self) -> List[ChannelConfig]:
        """Force reload channels.yaml — used after identity sync or niche update."""
        self._channels_loaded = False
        return self.get_active_channels()

    def get_providers(self) -> Dict[str, Any]:
        return self._load_yaml(self.providers_path)

    def get_settings(self) -> Dict[str, Any]:
        return self._load_yaml(self.settings_path)


config_manager = ConfigManager()
