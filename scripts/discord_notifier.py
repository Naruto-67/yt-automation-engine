import json
import logging
import requests
from typing import Optional, List, Dict, Any

# Configure basic logging for professional monitoring
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DiscordNotifier")

class DiscordNotifier:
    """
    A robust class for sending text messages and rich embeds to a Discord Webhook.
    """
    def __init__(self, webhook_url: str, default_username: Optional[str] = None, default_avatar_url: Optional[str] = None):
        """
        Initializes the Discord notifier.
        
        :param webhook_url: The full Discord webhook URL.
        :param default_username: Optional username to override the webhook's default name.
        :param default_avatar_url: Optional avatar URL to override the webhook's default avatar.
        """
        self.webhook_url = webhook_url
        self.default_username = default_username
        self.default_avatar_url = default_avatar_url

    def _send_payload(self, payload: Dict[str, Any]) -> bool:
        """Internal method to dispatch the JSON payload to the Discord webhook."""
        # Inject default username and avatar if provided and not already in payload
        if self.default_username and "username" not in payload:
            payload["username"] = self.default_username
        if self.default_avatar_url and "avatar_url" not in payload:
            payload["avatar_url"] = self.default_avatar_url

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10 # Prevents hanging indefinitely
            )
            response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
            logger.info("Successfully sent notification to Discord.")
            return True
            
        except requests.exceptions.Timeout:
            logger.error("Request to Discord webhook timed out.")
            return False
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"An unexpected error occurred while sending to Discord: {e}")
            return False

    def send_message(self, content: str) -> bool:
        """
        Sends a simple plain-text message.
        """
        if not content.strip():
            logger.warning("Attempted to send an empty message.")
            return False
        return self._send_payload({"content": content})

    def send_embed(self, 
                   title: str, 
                   description: str, 
                   color: int = 0x3498db, 
                   fields: Optional[List[Dict[str, Any]]] = None, 
                   footer_text: Optional[str] = None) -> bool:
        """
        Sends a rich embed message (useful for alerts, formatted data, etc.).
        
        :param title: The title of the embed.
        :param description: The main body text of the embed.
        :param color: Hex color code (integer). Default is a nice blue.
        :param fields: List of dictionaries containing 'name', 'value', and optional 'inline' boolean.
        :param footer_text: Optional small text at the bottom of the embed.
        """
        embed: Dict[str, Any] = {
            "title": title,
            "description": description,
            "color": color
        }

        if fields:
            embed["fields"] = fields

        if footer_text:
            embed["footer"] = {"text": footer_text}

        return self._send_payload({"embeds": [embed]})

if __name__ == "__main__":
    # --- Example Usage / Testing ---
    # Replace the string below with your actual webhook URL to test
    WEBHOOK_URL = "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
    
    # Initialize the notifier
    notifier = DiscordNotifier(
        webhook_url=WEBHOOK_URL,
        default_username="System Monitor",
        default_avatar_url="https://cdn-icons-png.flaticon.com/512/2889/2889312.png"
    )

    # 1. Sending a standard text message
    notifier.send_message("🟢 System startup sequence initiated successfully.")

    # 2. Sending a detailed alert embed
    notifier.send_embed(
        title="⚠️ System Alert: High CPU Usage",
        description="The server CPU usage has exceeded the normal threshold for the last 5 minutes.",
        color=0xe74c3c, # Red color for error/alert
        fields=[
            {"name": "Server Node", "value": "us-east-1-prod-04", "inline": True},
            {"name": "Current CPU", "value": "94.2%", "inline": True},
            {"name": "Action Taken", "value": "Auto-scaling rules triggered. Provisioning new instances...", "inline": False}
        ],
        footer_text="Monitoring Infrastructure v2.1"
    )
