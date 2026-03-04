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
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/1384/1384060.png", # Fixed raw URL
            "embeds": [embed_data]
        }
        response = requests.post(webhook, json=payload)
        
        # Explicitly catch silent API rejections from Discord
        if response.status_code >= 400:
            print(f"❌ Discord API Error {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"❌ Discord request failed entirely: {e}")

def notify_render(niche, topic, script, size_mb, duration_sec):
    embed = {
        "title": "🎬 Masterpiece Rendered & Locked",
        "color": 3447003, 
        "fields": [
            {"name": "🎯 Niche", "value": f"└ {niche.upper()}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "📊 Stats", "value": f"└ Size: {size_mb:.1f}MB\n└ Duration: {duration_sec}s", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "📜 Script Preview", "value": f"└ *{script[:150]}...*", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_vault_secure(seo_title, video_id, playlist_id):
    video_url = f"https://youtu.be/{video_id}" # Fixed raw URL formatting
    embed = {
        "title": "🔒 Video Secured in YouTube Vault",
        "color": 9807270, 
        "fields": [
            {"name": "📝 SEO Title Applied", "value": f"└ {seo_title}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "🔗 Private Link", "value": f"└ [Click to view Video in Vault]({video_url})", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_upload(topic, live_time="Tomorrow, 9:00 AM"):
    embed = {
        "title": "📤 Video Uploaded & Scheduled",
        "color": 5763719, 
        "fields": [
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "⏰ Goes Live", "value": f"└ {live_time}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_warning(topic, step, attempt, max_attempt):
    embed = {
        "title": f"⚠️ Retry Triggered: {step}",
        "color": 16766720, 
        "fields": [
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "🔄 Status", "value": f"└ Attempt {attempt} of {max_attempt} failed. Retrying...", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_error(topic, step, fallback_msg):
    embed = {
        "title": f"🚨 Critical Error: {step}",
        "color": 15158332, 
        "fields": [
            {"name": "📝 Topic", "value": f"└ {topic}", "inline": False},
            {"name": "\u200b", "value": "\u200b", "inline": False},
            {"name": "🛠️ Action Taken / Detail", "value": f"└ {fallback_msg}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_summary(success, message):
    color = 3066993 if success else 15158332 
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
