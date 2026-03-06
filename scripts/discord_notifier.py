def notify_token_expiry(days_unused):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    notifier = DiscordNotifier(webhook_url)
    
    scopes = (
        "1. `https://www.googleapis.com/auth/youtube.upload`\n"
        "2. `https://www.googleapis.com/auth/youtube.force-ssl`\n"
        "3. `https://www.googleapis.com/auth/youtube`"
    )
    
    steps = (
        "1. Run your local OAuth Python script.\n"
        "2. Sign in with the Channel's Google Account.\n"
        "3. Copy the newly generated Refresh Token.\n"
        "4. Go to GitHub Repo -> Settings -> Secrets and Variables.\n"
        "5. Update `YOUTUBE_REFRESH_TOKEN`."
    )
    
    fields = [
        {"name": "⚠️ Token Inactivity", "value": f"└ Unused for {days_unused} days", "inline": False},
        {"name": "🔑 Required Scopes", "value": scopes, "inline": False},
        {"name": "🛠️ Steps to Renew", "value": steps, "inline": False}
    ]
    notifier.send_rich_embed("⚠️ YouTube API Token Dormant (Expiring Soon)", 0xe1ad01, fields)
