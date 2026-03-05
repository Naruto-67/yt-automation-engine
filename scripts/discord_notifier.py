import json
import logging
import requests
from typing import Optional, List, Dict, Any
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DiscordNotifier")

class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.default_username = "Ghost Engine"

    def _send_payload(self, payload: Dict[str, Any]) -> bool:
        if not self.webhook_url:
            return False
        if "username" not in payload:
            payload["username"] = self.default_username
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except:
            return False

    def send_embed(self, title: str, description: str, color: int) -> bool:
        embed = {"title": title, "description": description, "color": color}
        return self._send_payload({"embeds": [embed]})

# Global Helper Functions used by main.py
def notify_summary(success: bool, message: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    notifier = DiscordNotifier(webhook_url)
    color = 0x2ecc71 if success else 0xe74c3c
    title = "✅ Production Success" if success else "⚠️ Production Warning"
    notifier.send_embed(title, message, color)

def notify_error(module: str, error_type: str, message: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    notifier = DiscordNotifier(webhook_url)
    full_msg = f"**Module:** {module}\n**Type:** {error_type}\n**Details:** {message}"
    notifier.send_embed("🚨 Critical Error", full_msg, 0xe74c3c)

def notify_warning(module: str, message: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    notifier = DiscordNotifier(webhook_url)
    notifier.send_embed(f"⚠️ Warning in {module}", message, 0xf1c40f)

def notify_vault_secure(title: str, video_id: str, playlist_id: str):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    notifier = DiscordNotifier(webhook_url)
    msg = f"**Title:** {title}\n**Video ID:** {video_id}\nSecured in Vault Backup."
    notifier.send_embed("☁️ Video Vaulted", msg, 0x3498db)
