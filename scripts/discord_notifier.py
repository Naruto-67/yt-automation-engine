import requests
import os
from datetime import datetime
import pytz

class DiscordNotifier:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def get_ist_time(self):
        ist = pytz.timezone('Asia/Kolkata')
        return datetime.now(ist).strftime('%Y-%m-%d %I:%M %p IST')

    def send_rich_embed(self, title, color, fields):
        if not self.webhook_url: return False
            
        payload = {
            "username": "YouTube Automation Engine",
            "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/YouTube_full-color_icon_%282017%29.svg/1024px-YouTube_full-color_icon_%282017%29.svg.png",
            "embeds": [{
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {"text": f"Engine Local Time: {self.get_ist_time()}"}
            }]
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=10)
            return True
        except: return False

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, status="Vaulted (Test Mode)"):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    # Safely extract metadata
    title = metadata.get('title', 'Generated Title')
    desc = metadata.get('description', 'Generated Description')[:150]
    tags = ', '.join(metadata.get('tags', []))[:100]
    
    fields = [
        {"name": "🎯 Niche & Video", "value": f"**Niche:** {niche.title()}\n**Topic:** {topic}", "inline": False},
        {"name": "🔥 SEO Metadata", "value": f"**Title:** {title}\n**Tags:** {tags}...\n**Desc:** {desc}...", "inline": False},
        {"name": "🧠 AI Architecture & Fallbacks", "value": f"└ **Script:** {script_ai}\n└ **SEO:** {seo_ai}\n└ **Voice:** {voice_ai}\n└ **Visual:** {visual_ai}", "inline": False},
        {"name": "📜 Script Preview", "value": f"└ {script[:150]}...", "inline": False},
        {"name": "🏦 Upload Status", "value": f"└ {status}", "inline": False}
    ]
    notifier.send_rich_embed("🎬 Video Production Success", 0x9b59b6, fields)

def notify_summary(success, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    color = 0x2ecc71 if success else 0xe74c3c
    title = "📊 System Update" if success else "⚠️ System Warning"
    fields = [{"name": "Details", "value": f"└ {message}", "inline": False}]
    notifier.send_rich_embed(title, color, fields)

def notify_error(module, error_type, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    fields = [
        {"name": "🧩 Module", "value": f"└ {module}", "inline": False},
        {"name": "⚠️ Error Type", "value": f"└ {error_type}", "inline": False},
        {"name": "📜 Details", "value": f"└ {message[:500]}", "inline": False}
    ]
    notifier.send_rich_embed("🚨 Critical System Crash", 0xe74c3c, fields)

def notify_vault_secure(topic, *args, **kwargs):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    fields = [
        {"name": "📝 Video", "value": f"└ {topic}", "inline": False},
        {"name": "🏦 Status", "value": "└ Securely uploaded to Private Vault", "inline": False}
    ]
    notifier.send_rich_embed("🏦 Vault Secured", 0x3498db, fields)
