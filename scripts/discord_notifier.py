# scripts/discord_notifier.py
import requests
import os
import time
import random
from datetime import datetime
import pytz

class DiscordNotifier:
    def __init__(self):
        # Current scoped context
        webhook_env = os.environ.get("CURRENT_DISCORD_WEBHOOK_ENV", "DISCORD_WEBHOOK_URL")
        self.webhook_url = os.environ.get(webhook_env)

    def get_ist_time(self):
        ist = pytz.timezone('Asia/Kolkata')
        return datetime.now(ist).strftime('%Y-%m-%d %I:%M %p IST')

    def send_rich_embed(self, title, color, fields, thumbnail=None):
        if not self.webhook_url: return False
        payload = {
            "username": "Ghost Engine AI",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2111/2111370.png",
            "embeds": [{
                "title": title, "color": color, "fields": fields,
                "footer": {"text": f"Engine Local Time: {self.get_ist_time()}"}
            }]
        }
        if thumbnail: payload["embeds"][0]["thumbnail"] = {"url": thumbnail}
        try:
            requests.post(self.webhook_url, json=payload, timeout=15)
            return True
        except: return False

# --- NEW V5 OBSERVABILITY METHODS ---

def notify_quota_warning(provider, current, limit):
    """Point 19: High usage warning."""
    notifier = DiscordNotifier()
    fields = [{"name": "⚠️ Quota Alert", "value": f"└ **{provider.upper()}** is at {current}/{limit} usage."}]
    notifier.send_rich_embed("⚡ High Resource Usage", 0xf1c40f, fields)

def notify_provider_swap(module, old_p, new_p):
    """Point 7: Dynamic fallback notification."""
    notifier = DiscordNotifier()
    fields = [{"name": f"🔄 {module} Failover", "value": f"└ Swapped: `{old_p}` ➔ `{new_p}`"}]
    notifier.send_rich_embed("⚙️ System Degraded Mode", 0xe67e22, fields)

def notify_security_flag(comment_user, comment_text, title):
    """Point 18: Prompt injection or troll detection."""
    notifier = DiscordNotifier()
    fields = [
        {"name": "👤 User", "value": f"└ {comment_user}", "inline": True},
        {"name": "📝 Video", "value": f"└ {title}", "inline": True},
        {"name": "🚫 Blocked Content", "value": f"``` {comment_text} ```"}
    ]
    notifier.send_rich_embed("🛡️ Security Protocol Triggered", 0x34495e, fields)

def notify_identity_established(channel_id, niche):
    """Point 9: Niche Discovery confirmation."""
    notifier = DiscordNotifier()
    fields = [
        {"name": "🆔 Channel", "value": f"└ {channel_id}", "inline": True},
        {"name": "🎯 Discovered Niche", "value": f"└ {niche}", "inline": True}
    ]
    notifier.send_rich_embed("✨ New Identity Established", 0x2ecc71, fields)

# --- RE-PROVIDING CORE V5 METHODS FOR COMPLETENESS ---

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, duration, size):
    notifier = DiscordNotifier()
    fields = [
        {"name": "🎯 Niche", "value": f"└ {niche}", "inline": True},
        {"name": "📊 Stats", "value": f"└ {size:.1f}MB | {duration:.1s}s", "inline": True},
        {"name": "🧠 Logic", "value": f"└ **AI:** {script_ai} | **SEO:** {seo_ai}"}
    ]
    notifier.send_rich_embed("🪬 Production Success", 0x9b59b6, fields)

def notify_summary(success, message):
    notifier = DiscordNotifier()
    color = 0x9b59b6 if success else 0xe74c3c
    fields = [{"name": "📝 Log", "value": f"└ {message}"}]
    notifier.send_rich_embed("📊 System Update", color, fields)

def notify_error(module, error_type, message):
    notifier = DiscordNotifier()
    fields = [{"name": "🧩 Module", "value": f"└ {module}"}, {"name": "📜 Details", "value": f"└ {message[:500]}"}]
    notifier.send_rich_embed("🚨 Critical Crash", 0xe74c3c, fields)
