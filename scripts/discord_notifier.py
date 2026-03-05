import os
import requests
import json
from datetime import datetime
import pytz

def get_ist_time():
    """Returns formatted India Standard Time (IST) for reporting."""
    try:
        ist = pytz.timezone('Asia/Kolkata')
        return datetime.now(ist).strftime("%Y-%m-%d | %I:%M %p")
    except Exception:
        # Fallback to UTC if pytz or timezone logic fails
        return datetime.utcnow().strftime("%Y-%m-%d | %H:%M UTC")

def send_embed(embed):
    """Internal helper to send a formatted JSON embed to the Discord Webhook."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("⚠️ [DISCORD] Webhook URL missing. Bypassing notification.")
        return
    
    payload = {
        "username": "Ghost Engine Mission Control",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/1384/1384060.png",
        "embeds": [embed]
    }
    
    try:
        response = requests.post(webhook, json=payload, timeout=15)
        if response.status_code >= 400:
            print(f"❌ [DISCORD] HTTP Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ [DISCORD] Connection failed: {e}")

def notify_daily_pulse(data):
    """Sends the daily 5:30 PM IST comprehensive performance and health report."""
    # Data normalization for various module versions
    health = data.get("health_report", data.get("health", {}))
    is_healthy = health.get("is_healthy", True)
    color = 3066993 if is_healthy else 16766720
    
    growth_views = data.get('views_growth', data.get('growth', {}).get('views', 0))
    growth_subs = data.get('subs_growth', data.get('growth', {}).get('subs', 0))
    
    embed = {
        "title": f"📊 Daily Pulse: {data.get('channel_name', data.get('channel', 'Channel'))}",
        "color": color,
        "fields": [
            {
                "name": "📈 Growth (Last 24h)", 
                "value": f"└ Views: **+{growth_views}**\n└ Subs: **+{growth_subs}**", 
                "inline": True
            },
            {
                "name": "🤖 AI Strategy", 
                "value": f"*{data.get('ai_take', data.get('assessment', 'N/A'))}*", 
                "inline": False
            }
        ],
        "footer": {"text": f"Engine IST: {get_ist_time()}"}
    }
    
    if not is_healthy:
        embed["fields"].append({
            "name": "🚨 SECURITY ALERT: TOKEN EXPIRING",
            "value": f"{health.get('msg', 'Warning')}\n\n{health.get('baby_steps', health.get('steps', ''))}",
            "inline": False
        })
    
    send_embed(embed)

def notify_vault_secure(title, vid_id, playlist_id):
    """Confirmation notification when a video is moved to the private vault."""
    embed = {
        "title": "🔒 Video Secured in Vault",
        "color": 3447003,
        "description": f"**Title:** {title}\n**URL:** https://youtu.be/{vid_id}\n**Vault Playlist:** {playlist_id}",
        "footer": {"text": f"Logged at: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_summary(success, msg):
    """General status update for pipeline completion or research cycles."""
    title = "✅ Mission Success" if success else "⚠️ Mission Alert"
    color = 3066993 if success else 15158332
    embed = {
        "title": title,
        "color": color,
        "description": msg,
        "footer": {"text": f"Event Logged: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_error(module, step, error):
    """High-priority crash notification for the AI Doctor protocol."""
    err_msg = str(error)[:500]
    embed = {
        "title": f"🚨 System Error in {module}",
        "color": 15158332,
        "fields": [
            {"name": "Execution Step", "value": step, "inline": True},
            {
                "name": "Traceback Summary", 
                "value": f"```text\n{err_msg}\n```", 
                "inline": False
            }
        ],
        "footer": {"text": f"Crash Time: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_engagement(video_title, comment, reply):
    """Logs an AI-generated fan interaction."""
    embed = {
        "title": "💬 Fan Engagement Success",
        "color": 10181046,
        "fields": [
            {"name": "🎬 Video", "value": video_title[:100], "inline": False},
            {"name": "👤 Fan Comment", "value": f"*{comment[:200]}*", "inline": False},
            {"name": "🤖 AI Reply", "value": reply, "inline": False}
        ],
        "footer": {"text": f"Interaction IST: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_upload(title, sched_time):
    """Notifies when a video is scheduled for public release."""
    embed = {
        "title": "🚀 Video Launch Scheduled",
        "color": 15844367,
        "description": f"**Video:** {title}\n**Scheduled for:** {sched_time}",
        "footer": {"text": f"Scheduled at: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_warning(module, reason, current=None, limit=None):
    """Sends a non-fatal system warning."""
    val_str = f" ({current}/{limit})" if current is not None else ""
    embed = {
        "title": f"⚠️ System Warning: {module}",
        "color": 16776960,
        "description": f"{reason}{val_str}",
        "footer": {"text": f"Warning IST: {get_ist_time()}"}
    }
    send_embed(embed)

def notify_render(niche, topic, script, size_mb, duration_sec):
    """Stats for a newly rendered video file."""
    preview = f"*{script[:200]}...*"
    stats = f"{size_mb:.1f}MB | {duration_sec}s"
    embed = {
        "title": "🎬 Masterpiece Rendered",
        "color": 3447003,
        "fields": [
            {"name": "🎯 Niche", "value": niche.upper(), "inline": True},
            {"name": "📊 Stats", "value": stats, "inline": True},
            {
                "name": "📜 Script Preview", 
                "value": preview, 
                "inline": False
            }
        ],
        "footer": {"text": f"Rendered IST: {get_ist_time()}"}
    }
    send_embed(embed)
    
