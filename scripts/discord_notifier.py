import os
import requests
from datetime import datetime
import pytz

def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime("%Y-%m-%d | %I:%M %p")

def send_embed(embed):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook: return
    try: requests.post(webhook, json={"embeds": [embed]}, timeout=10)
    except: pass

def notify_daily_pulse(data):
    """Sends the IST 5:30 PM Pulse with assessment and health check."""
    health = data["health"]
    embed = {
        "title": f"📊 Daily Pulse: {data['channel']}",
        "color": 3066993 if health["is_healthy"] else 16766720,
        "fields": [
            {"name": "📈 Growth", "value": f"└ Views: **+{data['growth']['views']}**\n└ Subs: **+{data['growth']['subs']}**", "inline": True},
            {"name": "🤖 AI Strategy", "value": f"*{data['assessment']}*", "inline": False}
        ],
        "footer": {"text": f"Engine IST: {get_ist_time()}"}
    }
    if not health["is_healthy"]:
        embed["fields"].append({"name": "🚨 TOKEN ALARM", "value": f"{health['msg']}\n{health['steps']}", "inline": False})
    
    send_embed(embed)

def notify_vault_secure(title, vid_id, playlist_id):
    send_embed({
        "title": "🔒 Video Secured in Vault",
        "color": 3447003,
        "description": f"**Title:** {title}\n**URL:** https://youtu.be/{vid_id}\n**Vault:** {playlist_id}"
    })

def notify_summary(success, msg):
    send_embed({
        "title": "✅ Cycle Complete" if success else "⚠️ Cycle Alert",
        "color": 3066993 if success else 15158332,
        "description": msg
    })

def notify_error(module, step, error):
    send_embed({
        "title": f"🚨 Error: {module}",
        "color": 15158332,
        "description": f"**Step:** {step}\n**Error:** {error}"
    })
