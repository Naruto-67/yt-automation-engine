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
            {"name": "🎯 Niche", "value": f"└ {niche.upper()}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "📊 Stats", "value": f"└ Size: {size_mb:.1f}MB\n└ Duration: {duration_sec}s", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "📜 Script Preview", "value": f"└ *{script[:150]}...*", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_upload(topic, live_time="Tomorrow, 9:00 AM"):
    embed = {
        "title": "📤 Video Uploaded & Scheduled",
        "color": 5763719, # Green
        "fields": [
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "⏰ Goes Live", "value": f"└ {live_time}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_warning(topic, step, attempt, max_attempt):
    embed = {
        "title": f"⚠️ Retry Triggered: {step}",
        "color": 16766720, # Yellow
        "fields": [
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "🔄 Status", "value": f"└ Attempt {attempt} of {max_attempt} failed. Retrying...", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_error(topic, step, fallback_msg):
    embed = {
        "title": f"🚨 Critical Error: {step}",
        "color": 15158332, # Red
        "fields": [
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "🛠️ Action Taken", "value": f"└ {fallback_msg}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_cleanup(filename, retention_msg):
    embed = {
        "title": "🧹 Vault Auto-Janitor Executed",
        "color": 9807270, # Grey
        "fields": [
            {"name": "🗑️ Deleted File", "value": f"└ `{filename}`", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False}, # Spacer
            {"name": "ℹ️ Reason", "value": f"└ {retention_msg}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_summary(success, message):
    color = 3066993 if success else 15158332 # Green if success, Red if fail
    title = "✅ Daily Pipeline Complete" if success else "❌ Daily Pipeline Failed"
    
    embed = {
        "title": title,
        "color": color,
        "fields": [
            {"name": "📊 Summary", "value": f"└ {message}", "inline": False}
        ],
        "footer": {"text": f"Mission Control • {get_ist_time()}"}
    }
    send_embed(embed)

if __name__ == "__main__":
    # Local Test to verify spacing and formatting
    notify_render("Fact", "Test Spaced Layout", "This is a test script to check the new vertical spacing formatting.", 15.2, 58)
    notify_cleanup("FINAL_SHORT_test.mp4", "Vault capacity reached (5 max).")
