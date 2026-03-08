# scripts/discord_notifier.py
import requests
import os
import time
import random
from datetime import datetime
import pytz

class DiscordNotifier:
    def __init__(self):
        """
        Scoped Webhook Logic: 
        Automatically selects the correct webhook based on the channel context 
        set by the Orchestrator.
        """
        webhook_env_name = os.environ.get("CURRENT_DISCORD_WEBHOOK_ENV", "DISCORD_WEBHOOK_URL")
        self.webhook_url = os.environ.get(webhook_env_name)

    def get_ist_time(self):
        """Standardizes all system timestamps to IST for uniform logging."""
        ist = pytz.timezone('Asia/Kolkata')
        return datetime.now(ist).strftime('%Y-%m-%d %I:%M %p IST')

    def send_rich_embed(self, title, color, fields, thumbnail=None):
        """Sends a structured embed to Discord with chaotic bio-pacing to evade bans."""
        if not self.webhook_url:
            print(f"⚠️ [NOTIFIER] Webhook missing for env: {os.environ.get('CURRENT_DISCORD_WEBHOOK_ENV')}")
            return False
            
        # Chaotic pacing to mimic human network behavior
        time.sleep(random.uniform(2.0, 4.5))

        payload = {
            "username": "Ghost Engine AI",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2111/2111370.png",
            "embeds": [{
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {"text": f"Engine Local Time: {self.get_ist_time()}"}
            }]
        }
        
        if thumbnail:
            payload["embeds"][0]["thumbnail"] = {"url": thumbnail}

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=15)
            return response.status_code == 200
        except Exception as e:
            print(f"🚨 [NOTIFIER CRASH] Failed to reach Discord: {e}")
            return False

# --- MISSION CONTROL NOTIFICATION SUITE ---

def notify_quota_warning(provider, current, limit):
    """Point 19: High resource usage alert."""
    notifier = DiscordNotifier()
    fields = [{"name": "⚠️ Quota Alert", "value": f"└ **{provider.upper()}** usage is at **{current}/{limit}**."}]
    notifier.send_rich_embed("⚡ Resource Warning", 0xf1c40f, fields)

def notify_provider_swap(module, old_p, new_p):
    """Point 7: Dynamic failover notification."""
    notifier = DiscordNotifier()
    fields = [{"name": f"🔄 {module} Failover", "value": f"└ Swapped: `{old_p}` ➔ `{new_p}`"}]
    notifier.send_rich_embed("⚙️ System Degraded Mode", 0xe67e22, fields)

def notify_security_flag(user, text, title):
    """Point 18: Security protocol triggered by comments/prompts."""
    notifier = DiscordNotifier()
    fields = [
        {"name": "👤 User", "value": f"└ {user}", "inline": True},
        {"name": "📝 Video", "value": f"└ {title}", "inline": True},
        {"name": "🚫 Blocked Content", "value": f"``` {text} ```"}
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

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, duration, size):
    """Full production cycle success report."""
    notifier = DiscordNotifier()
    title = metadata.get('title', 'Generated Video')
    fields = [
        {"name": "🎯 Niche", "value": f"└ {niche.title()}", "inline": True},
        {"name": "🔥 SEO Title", "value": f"└ {title[:100]}", "inline": False},
        {"name": "📊 Stats", "value": f"└ Size: {size:.1f} MB | Duration: {duration:.1f}s", "inline": True},
        {"name": "🧠 Core Logic", "value": f"└ **AI:** {script_ai} | **SEO:** {seo_ai}", "inline": False}
    ]
    notifier.send_rich_embed("🪬 Production Success", 0x9b59b6, fields)

def notify_summary(success, message):
    """Standardized pipeline status log."""
    notifier = DiscordNotifier()
    color = 0x9b59b6 if success else 0xe74c3c
    fields = [{"name": "📝 Status Log", "value": f"└ {message}", "inline": False}]
    notifier.send_rich_embed("📊 System Update", color, fields)

def notify_error(module, error_type, message):
    """Critical crash reporting with detail truncation."""
    notifier = DiscordNotifier()
    fields = [
        {"name": "🧩 Module", "value": f"└ {module}", "inline": True},
        {"name": "⚠️ Error Type", "value": f"└ {error_type}", "inline": True},
        {"name": "📜 Details", "value": f"└ {message[:500]}", "inline": False}
    ]
    notifier.send_rich_embed("🚨 Critical System Crash", 0xe74c3c, fields)
