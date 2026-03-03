import os
import requests
import json

def send_discord_message(message, status="info"):
    """
    Sends a message to your private Discord server.
    Status can be 'info' (blue), 'success' (green), or 'error' (red).
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    
    if not webhook_url:
        print("Warning: DISCORD_WEBHOOK_URL is not set.")
        return

    # Color coding the messages
    colors = {
        "info": 3447003,      # Blue
        "success": 5763719,   # Green
        "error": 15548997     # Red
    }
    
    color = colors.get(status, 3447003)

    data = {
        "embeds": [
            {
                "description": message,
                "color": color
            }
        ]
    }

    try:
        response = requests.post(
            webhook_url, 
            data=json.dumps(data), 
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

# This block allows us to test the script manually
if __name__ == "__main__":
    # To test this locally, you would need to set your environment variable first
    send_discord_message("🤖 Pipeline connection test: Discord webhook is active!", "success")
