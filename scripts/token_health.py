# scripts/token_health.py — Ghost Engine V6.1
import os
import json
from datetime import datetime
from engine.config_manager import config_manager
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import set_channel_context, notify_token_health

_HEALTH_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory", "token_health.json"
)

def _load_health() -> dict:
    try:
        if os.path.exists(_HEALTH_PATH):
            with open(_HEALTH_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_health(health: dict):
    os.makedirs(os.path.dirname(_HEALTH_PATH), exist_ok=True)
    with open(_HEALTH_PATH, "w") as f:
        json.dump(health, f, indent=2)

def run_token_health_check():
    health  = _load_health()
    now     = datetime.utcnow()
    now_iso = now.isoformat()

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        ch_id = channel.channel_id

        if ch_id not in health:
            health[ch_id] = {
                "last_success_iso": now_iso,
                "consecutive_failures": 0
            }

        entry = health[ch_id]

        try:
            yt = get_youtube_client(channel)
            if yt is None:
                raise Exception("get_youtube_client returned None (missing credentials)")

            # Test the token by making a lightweight API call
            result = yt.channels().list(part="id", mine=True).execute()
            quota_manager.consume_points("youtube", 1)

            if not result.get("items"):
                raise Exception("channels().list returned empty items")

            # Reset failures on success
            entry["last_success_iso"]     = now_iso
            entry["consecutive_failures"] = 0
            health[ch_id]                 = entry
            
            print(f"✅ [{ch_id}] Token HEALTHY (API responded successfully).")

        except Exception as e:
            # Token failed — either revoked, password changed, or GCP consent screen expired
            entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
            health[ch_id]                 = entry

            failures = entry["consecutive_failures"]
            status   = "DEAD" if failures >= 2 else "CRITICAL"
            last_ok  = entry.get("last_success_iso", "never")
            days_unused = 0
            
            try:
                if last_ok and last_ok != "never":
                    days_unused = int((now - datetime.fromisoformat(last_ok)).days)
            except Exception:
                pass

            action = (
                f"Token FAILED for `{ch_id}` ({failures} consecutive failures).\n"
                f"Days since last successful use: {days_unused}.\n"
                f"Error: {str(e)[:200]}\n"
                f"URGENT: Regenerate refresh token via OAuth Playground and update "
                f"`{channel.youtube_refresh_token_env}` in GitHub Secrets."
            )
            notify_token_health(ch_id, status, days_unused, action)
            print(f"🚨 [{ch_id}] Token {status}: {e}")

    _save_health(health)
    print("✅ Token health check complete.")

if __name__ == "__main__":
    run_token_health_check()
