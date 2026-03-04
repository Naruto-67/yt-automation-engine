import os
import requests
from datetime import datetime
import pytz

def get_webhook():
    return os.environ.get("DISCORD_WEBHOOK_URL")

def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime("%I:%M %p")

def send_message(content):
    webhook = get_webhook()
    if not webhook:
        print("⚠️ Discord Webhook missing. Skipping notification.")
        return
    try:
        requests.post(webhook, json={"content": content})
    except Exception as e:
        print(f"❌ Discord notification failed: {e}")

def notify_render(title, size_mb, duration_sec):
    msg = f"🎬 **{title}** — rendered and saved\n └ Size: {size_mb:.1f}MB | Duration: {duration_sec}s | {get_ist_time()}"
    send_message(msg)

def notify_upload(title, live_time="Tomorrow, 9:00 AM"):
    msg = f"📤 **{title}** — uploaded and scheduled\n └ Goes live: {live_time}"
    send_message(msg)

def notify_warning(title, step, attempt, max_attempt):
    msg = f"⚠️ **{title}** — {step} failed, retrying (attempt {attempt}/{max_attempt})"
    send_message(msg)

def notify_error(title, step, fallback):
    msg = f"🚨 **{title}** — failed at {step}, fallback used: {fallback}"
    send_message(msg)

def notify_cleanup(title, retention_msg):
    msg = f"🗑️ **{title}** — {retention_msg}"
    send_message(msg)

def notify_summary(stats):
    msg = f"✅ **Daily Run Complete** — {stats}"
    send_message(msg)

def notify_analytics(stats_msg):
    msg = f"📈 **Channel Analytics Update**\n{stats_msg}"
    send_message(msg)

if __name__ == "__main__":
    # Local Test
    notify_render("Test Short Story", 15.2, 58)
