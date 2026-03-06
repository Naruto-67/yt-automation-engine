import requests
import os
import time
import random
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
        
        # 🚨 FIX: Chaotic Biological Pacing mathematically evades automated shadowban algorithms
        time.sleep(random.uniform(2.5, 4.5))
            
        payload = {
            "username": "Ghost Engine AI",
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

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, duration, size, status="Vaulted (Test Mode)"):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    title = metadata.get('title', 'Generated Title')
    desc = metadata.get('description', 'Generated Description')[:150]
    tags = ', '.join(metadata.get('tags', []))[:100]
    
    fields = [
        {"name": "🎯 Niche", "value": f"└ {niche.title()}", "inline": False},
        {"name": "🔥 SEO Metadata", "value": f"**Title:** {title}\n**Tags:** {tags}...\n**Desc:** {desc}...", "inline": False},
        {"name": "📊 Stats", "value": f"└ Size: {size:.1f} MB\n└ Duration: {duration:.1f}s", "inline": False},
        {"name": "📜 Script Preview", "value": f"└ {script[:150]}...", "inline": False},
        {"name": "🧠 Rendered By", "value": f"└ **Script:** {script_ai}\n└ **SEO:** {seo_ai}\n└ **Voice:** {voice_ai}\n└ **Visual:** {visual_ai}", "inline": False},
        {"name": "🏦 Upload Status", "value": f"└ {status}", "inline": False}
    ]
    notifier.send_rich_embed("🪬 Production Success", 0x9b59b6, fields)

def notify_summary(success, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    color = 0x9b59b6 if success else 0xe74c3c 
    
    fields = [
        {"name": "📝 Status Log", "value": f"└ {message}", "inline": False}
    ]
    notifier.send_rich_embed("📊 System Update", color, fields)

def notify_daily_pulse(views, subs, new_rules):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    fields = [
        {"name": "📈 Channel Stats", "value": f"└ **Views:** {views}\n└ **Subs:** {subs}", "inline": False},
        {"name": "🧠 AI Strategy Update", "value": f"└ **Focus:** {new_rules['emphasize'][0]}\n└ **Avoid:** {new_rules['avoid'][0]}", "inline": False}
    ]
    notifier.send_rich_embed("🔮 Daily Channel Pulse & Analysis", 0x9b59b6, fields)

def notify_error(module, error_type, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    fields = [
        {"name": "🧩 Module", "value": f"└ {module}", "inline": False},
        {"name": "⚠️ Error Type", "value": f"└ {error_type}", "inline": False},
        {"name": "📜 Details", "value": f"└ {message[:500]}", "inline": False}
    ]
    notifier.send_rich_embed("🚨 AI Doctor: Critical Crash", 0xe74c3c, fields)

def notify_vault_secure(topic, *args, **kwargs):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    fields = [
        {"name": "📝 Video", "value": f"└ {topic}", "inline": False},
        {"name": "🏦 Status", "value": "└ Securely uploaded to Private Vault", "inline": False}
    ]
    notifier.send_rich_embed("🪬 Vault Secured", 0x9b59b6, fields)

def notify_token_expiry(days_unused):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    scopes = (
        "1. `https://www.googleapis.com/auth/youtube.upload`\n"
        "2. `https://www.googleapis.com/auth/youtube.force-ssl`\n"
        "3. `https://www.googleapis.com/auth/youtube`"
    )
    
    steps = (
        "1. Run your local OAuth Python script.\n"
        "2. Sign in with the Channel's Google Account.\n"
        "3. Copy the newly generated Refresh Token.\n"
        "4. Go to GitHub Repo -> Settings -> Secrets and Variables.\n"
        "5. Update `YOUTUBE_REFRESH_TOKEN`."
    )
    
    fields = [
        {"name": "⚠️ Token Inactivity", "value": f"└ Unused for {days_unused} days", "inline": False},
        {"name": "🔑 Required Scopes", "value": scopes, "inline": False},
        {"name": "🛠️ Steps to Renew", "value": steps, "inline": False}
    ]
    notifier.send_rich_embed("⚠️ YouTube API Token Dormant (Expiring Soon)", 0xe1ad01, fields)
