import os
import requests
from datetime import datetime
import pytz

def get_webhook():
    return os.environ.get("DISCORD_WEBHOOK_URL")

def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime("%I:%M %p")

def send_embed(embed_data):
    webhook = get_webhook()
    if not webhook:
        print("⚠️ Discord Webhook missing. Skipping notification.")
        return
    try:
        print("📢 Pinging Discord Mission Control...")
        payload = {
            "username": "YouTube Automation Engine",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/1384/1384060.png",
            "embeds": [embed_data]
        }
        requests.post(webhook, json=payload)
    except Exception as e:
        print(f"❌ Discord notification failed: {e}")

def notify_render(niche, topic, script, size_mb, duration_sec):
    embed = {
        "title": "🎬 Masterpiece Rendered & Locked",
        "color": 3447003, # Blue
        "fields": [
            {"name": "🎯 Niche", "value": niche.upper(), "inline": True},
            {"name": "📝 Topic", "value": topic, "inline": True},
            {"name": "📊 Stats", "value": f"**Size:** {size_mb:.1f}MB\n**Duration:** {duration_sec}s", "inline": False},
            {"name": "📜 Script Preview", "value": f"*{script[:150]}...*", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_warning(topic, step, attempt, max_attempt):
    embed = {
        "title": f"⚠️ Retry Triggered: {step}",
        "description": f"**Topic:** {topic}\nAttempt {attempt} of {max_attempt} failed. Retrying...",
        "color": 16766720 # Yellow
    }
    send_embed(embed)

def notify_error(topic, step, fallback_msg):
    embed = {
        "title": f"🚨 Critical Error at {step}",
        "description": f"**Topic:** {topic}\n**Action Taken:** {fallback_msg}",
        "color": 15158332 # Red
    }
    send_embed(embed)

def notify_cleanup(filename, retention_msg):
    embed = {
        "title": "🧹 Vault Auto-Janitor Executed",
        "description": f"**Deleted:** `{filename}`\n**Reason:** {retention_msg}",
        "color": 9807270 # Grey
    }
    send_embed(embed)

def notify_summary(success, message):
    color = 3066993 if success else 15158332 # Green if success, Red if fail
    title = "✅ Daily Pipeline Complete" if success else "❌ Daily Pipeline Failed"
    
    embed = {
        "title": title,
        "description": message,
        "color": color,
        "footer": {"text": "Mission Control Dashboard"}
    }
    send_embed(embed)

if __name__ == "__main__":
    # Local Test of the new embed system
    notify_render("Fact", "Test Topic", "This is a test script...", 15.2, 58)
