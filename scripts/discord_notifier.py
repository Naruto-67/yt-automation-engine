import requests
import os

class DiscordNotifier:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def send_embed(self, title, description, color):
        if not self.webhook_url:
            print("⚠️ [DISCORD] No Webhook URL found in environment secrets.")
            return False
            
        payload = {
            "username": "Ghost Engine",
            "embeds": [{"title": title, "description": description, "color": color}]
        }
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            if res.status_code in [200, 204]:
                print("✅ [DISCORD] Notification successfully sent.")
                return True
            else:
                print(f"❌ [DISCORD] Failed to send. HTTP {res.status_code}: {res.text}")
                return False
        except Exception as e:
            print(f"❌ [DISCORD] Error establishing connection: {e}")
            return False

def notify_summary(success, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    color = 0x2ecc71 if success else 0xe74c3c
    title = "✅ Production Success" if success else "⚠️ Production Warning"
    notifier.send_embed(title, message, color)

def notify_error(module, error_type, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    full_msg = f"**Module:** {module}\n**Type:** {error_type}\n**Details:** {message}"
    notifier.send_embed("🚨 Critical Error", full_msg, 0xe74c3c)

def notify_warning(module, message):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    notifier.send_embed(f"⚠️ Warning in {module}", message, 0xf1c40f)

# 🚨 THE FIX: Re-adding the missing function that youtube_manager.py expects!
def notify_vault_secure(topic, *args, **kwargs):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    notifier.send_embed("🏦 Vault Secured", f"Video successfully vaulted: {topic}", 0x3498db)
