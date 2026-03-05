import os
import requests
import json
from datetime import datetime
import pytz

def get_ist_time():
    """Returns formatted IST time for the 5:30 PM report."""
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime("%Y-%m-%d | %I:%M %p")

def send_to_discord(payload):
    """Sends the formatted JSON payload to the Discord Webhook."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("⚠️ [DISCORD] Webhook URL missing. Bypassing notification.")
        return
    try:
        response = requests.post(webhook, json=payload, timeout=10)
        if response.status_code >= 400:
            print(f"❌ [DISCORD] Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ [DISCORD] Connection failed: {e}")

def notify_daily_pulse(data):
    """
    Formats and sends the 5:30 PM IST Daily Health & Stats Pulse.
    Includes logic for the 'Baby Steps' Token Alarm.
    """
    health = data["health_report"]
    # Color: Green (3066993) if healthy, Yellow (16766720) if warning
    color = 3066993 if health["is_healthy"] else 16766720
    
    embed = {
        "title": f"📊 Daily Pulse: {data['channel_name']}",
        "color": color,
        "fields": [
            {
                "name": "📈 Growth (Last 24h)",
                "value": f"└ Views: **+{data['views_growth']}**\n└ Subs: **+{data['subs_growth']}**",
                "inline": True
            },
            {
                "name": "🌎 Channel Totals",
                "value": f"└ Total Views: {data['views']:,}\n└ Total Subs: {data['subs']:,}",
                "inline": True
            },
            {
                "name": "🤖 Gemini Assessment",
                "value": f"*{data['ai_take']}*",
                "inline": False
            }
        ],
        "footer": {"text": f"Mission Control • IST: {get_ist_time()}"}
    }

    # If token health is failing, inject the Baby Steps guide
    if not health["is_healthy"]:
        embed["fields"].append({
            "name": "🚨 SECURITY ALERT: TOKEN EXPIRING",
            "value": f"{health['msg']}\n\n{health['baby_steps']}",
            "inline": False
        })

    payload = {
        "username": "Ghost Engine Pulse",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/1384/1384060.png",
        "embeds": [embed]
    }
    send_to_discord(payload)

# --- STANDARD NOTIFICATIONS ---

def notify_render(niche, topic, script, size_mb, duration_sec):
    embed = {
        "title": "🎬 Masterpiece Rendered",
        "color": 3447003,
        "fields": [
            {"name": "🎯 Niche", "value": niche.upper(), "inline": True},
            {"name": "📊 Stats", "value": f"{size_mb:.1f}MB | {duration_sec}s", "inline": True},
            {"name": "📜 Script", "value": f"*{script[:200]}...*", "inline": False}
        ]
    }
    send_to_discord({"embeds": [embed]})

def notify_error(module, step, error_msg):
    embed = {
        "title": f"🚨 Error in {module}",
        "color": 15158332,
        "description": f"**Step:** {step}\n**Error:** {error_msg}"
    }
    send_to_discord({"embeds": [embed]})

def notify_summary(success, message):
    title = "✅ Production Pipeline Complete" if success else "❌ Production Pipeline Failed"
    color = 3066993 if success else 15158332
    embed = {
        "title": title,
        "color": color,
        "description": message
    }
    send_to_discord({"embeds": [embed]})
