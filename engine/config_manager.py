# engine/config_manager.py
import os
import yaml
from typing import List, Dict, Any
from engine.logger import logger
from engine.models import ChannelConfig
from scripts.niche_discovery import discover_channel_niche, update_yaml_niche
from scripts.youtube_manager import get_youtube_client

class ConfigManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.channels_path = os.path.join(self.root_dir, "config", "channels.yaml")
        self.providers_path = os.path.join(self.root_dir, "config", "providers.yaml")
        self.settings_path = os.path.join(self.root_dir, "config", "settings.yaml")
        self.channels = self._load_channels()

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

    def _load_channels(self) -> List[ChannelConfig]:
        data = self._load_yaml(self.channels_path)
        raw_channels = data.get("channels", [])
        active_channels = []
        
        for ch in raw_channels:
            if not ch.get("active", False): continue
            
            # 🚨 V5 VALIDATION & REPAIR LOOP
            try:
                # 1. Pydantic validates existing data and applies defaults
                config = ChannelConfig(**ch)
                
                # 2. Trigger Niche Discovery if missing
                if not config.niche:
                    yt_client = get_youtube_client(config.youtube_refresh_token_env)
                    if yt_client:
                        discovered = discover_channel_niche(config.channel_id, yt_client)
                        update_yaml_niche(config.channel_id, discovered)
                        config.niche = discovered
                    else:
                        config.niche = "Trending Viral Shorts" # Global fallback

                active_channels.append(config)
            except Exception as e:
                logger.error(f"Skipping channel entry due to invalid schema: {e}")
                
        return active_channels

    def get_active_channels(self) -> List[ChannelConfig]:
        return self.channels
        
    def get_providers(self) -> Dict[str, Any]:
        return self._load_yaml(self.providers_path)

    def get_settings(self) -> Dict[str, Any]:
        return self._load_yaml(self.settings_path)

config_manager = ConfigManager()
