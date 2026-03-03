import os
import requests
import json

def send_discord_message(message, status="info"):
webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

if name == "main":
send_discord_message("Pipeline connection test: Discord webhook is active!", "success")
