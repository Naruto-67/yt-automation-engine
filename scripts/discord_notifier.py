# scripts/discord_notifier.py
import requests
import os
import time
import random
from datetime import datetime
import pytz

class DiscordNotifier:
    def __init__(self):
        # Dynamically grab the webhook mapping for the current active channel
        webhook_env_name = os.environ.get("CURRENT_DISCORD_WEBHOOK_ENV", "DISCORD_WEBHOOK_URL")
        self.webhook_url = os.environ.get(webhook_env_name)

    def get_ist_time(self):
        ist = pytz.timezone('Asia/Kolkata')
        return datetime.now(ist).strftime('%Y-%m-%d %I:%M %p IST')

    def send_rich_embed(self, title, color, fields):
        if not self.webhook_url:
            print(f"⚠️ [NOTIFIER] Webhook missing for env: {os.environ.get('CURRENT_DISCORD_WEBHOOK_ENV')}")
            return False
            
        time.sleep(random.uniform(1.5, 3.0)) # Bio-pacing

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
            response = requests.post(self.webhook_url, json=payload, timeout=15)
            return response.status_code == 200
        except:
            return False

def notify_step(topic, step_name, details, color=0x3498db):
    notifier = DiscordNotifier()
    fields = [
        {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
        {"name": f"🔄 {step_name}", "value": f"└ {details}", "inline": False}
    ]
    notifier.send_rich_embed("📡 Engine Telemetry", color, fields)

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, duration, size):
    notifier = DiscordNotifier()
    title = metadata.get('title', 'Generated Title')
    fields = [
        {"name": "🎯 Niche", "value": f"└ {niche.title()}", "inline": False},
        {"name": "🔥 SEO Title", "value": f"└ {title}", "inline": False},
        {"name": "📊 Stats", "value": f"└ Size: {size:.1f} MB | Duration: {duration:.1f}s", "inline": False},
        {"name": "🧠 Core Logic", "value": f"└ **Voice:** {voice_ai} | **Visual:** {visual_ai}", "inline": False}
    ]
    notifier.send_rich_embed("🪬 Production Success", 0x9b59b6, fields)

def notify_summary(success, message):
    notifier = DiscordNotifier()
    color = 0x9b59b6 if success else 0xe74c3c
    fields = [{"name": "📝 Status Log", "value": f"└ {message}", "inline": False}]
    notifier.send_rich_embed("📊 System Update", color, fields)

def notify_error(module, error_type, message):
    notifier = DiscordNotifier()
    fields = [
        {"name": "🧩 Module", "value": f"└ {module}", "inline": False},
        {"name": "⚠️ Error Type", "value": f"└ {error_type}", "inline": False},
        {"name": "📜 Details", "value": f"└ {message[:500]}", "inline": False}
    ]
    notifier.send_rich_embed("🚨 AI Doctor: Critical Crash", 0xe74c3c, fields)

def notify_daily_pulse(views, subs, rules):
    notifier = DiscordNotifier()
    fields = [
        {"name": "📈 Stats", "value": f"└ Views: {views} | Subs: {subs}", "inline": False},
        {"name": "🧠 AI Lesson", "value": f"└ **Focus:** {rules['emphasize'][0]}", "inline": False}
    ]
    notifier.send_rich_embed("🔮 Daily Channel Analysis", 0x3498db, fields)
