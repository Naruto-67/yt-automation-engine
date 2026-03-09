# scripts/token_health.py — Ghost Engine V6
"""
Weekly OAuth token health check.
Makes a live YouTube API call for each active channel to confirm tokens are valid.
Sends tiered Discord alerts: 🟢 HEALTHY / 🟡 WARNING / 🔴 CRITICAL / ⚫ DEAD
"""
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
    settings   = config_manager.get_settings()
    stor       = settings.get("storage", {})
    warn_days  = stor.get("token_health_warn_days", 7)
    crit_days  = stor.get("token_health_critical_days", 150)

    health     = _load_health()
    now        = datetime.utcnow()
    now_iso    = now.isoformat()

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        ch_id = channel.channel_id

        # Initialize entry if first run
        if ch_id not in health:
            health[ch_id] = {
                "last_success_iso": None,
                "consecutive_failures": 0,
                "first_seen_iso": now_iso
            }

        entry = health[ch_id]

        # ── Make a live API call to verify token ──────────────────────────────
        # Cost: 1 YT pt per channel (channels.list with mine=True)
        try:
            yt = get_youtube_client(channel)
            if yt is None:
                raise Exception("get_youtube_client returned None (missing credentials)")

            result = yt.channels().list(part="id", mine=True).execute()
            quota_manager.consume_points("youtube", 1)

            if not result.get("items"):
                raise Exception("channels().list returned empty items")

            # ── SUCCESS ──────────────────────────────────────────────────────
            entry["last_success_iso"]       = now_iso
            entry["consecutive_failures"]   = 0
            health[ch_id]                   = entry

            # Calculate days since first_seen (proxy for token age)
            first_seen   = entry.get("first_seen_iso", now_iso)
            days_old     = int((now - datetime.fromisoformat(first_seen)).days)

            if days_old >= crit_days:
                status = "CRITICAL"
                action = (
                    f"Token is {days_old} days old — expires in ~{180 - days_old} days. "
                    f"Renew NOW to avoid service disruption: "
                    f"run `python scripts/get_refresh_token.py` and update "
                    f"`{channel.youtube_refresh_token_env}` in GitHub Secrets."
                )
            elif days_old >= warn_days:
                status = "WARNING"
                action = (
                    f"Token is {days_old} days old. "
                    f"Expires in approximately {180 - days_old} days."
                )
            else:
                status = "HEALTHY"
                action = ""

            notify_token_health(ch_id, status, days_old, action)
            print(f"✅ [{ch_id}] Token {status} (age: {days_old} days)")

        except Exception as e:
            # ── FAILURE ───────────────────────────────────────────────────────
            entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
            health[ch_id]                 = entry

            failures = entry["consecutive_failures"]
            status   = "DEAD" if failures >= 2 else "CRITICAL"
            last_ok  = entry.get("last_success_iso", "never")
            days_old = 0
            try:
                if last_ok and last_ok != "never":
                    days_old = int((now - datetime.fromisoformat(last_ok)).days)
            except Exception:
                pass

            action = (
                f"Token FAILED for `{ch_id}` ({failures} consecutive failures). "
                f"Last success: {last_ok}. Error: {str(e)[:200]}. "
                f"URGENT: regenerate refresh token and update "
                f"`{channel.youtube_refresh_token_env}` in GitHub Secrets."
            )
            notify_token_health(ch_id, status, days_old, action)
            print(f"🚨 [{ch_id}] Token {status}: {e}")

    _save_health(health)
    print("✅ Token health check complete.")


if __name__ == "__main__":
    run_token_health_check()
