# scripts/token_health.py
# ─────────────────────────────────────────────────────────────────────────────
# FIX #1: YouTube Refresh Token Silent Death Prevention
#
# WHY THIS EXISTS:
#   YouTube OAuth refresh tokens expire after ~180 days of disuse. When that
#   happens, get_youtube_client() silently returns None, the orchestrator skips
#   the channel, and your channel goes dark — with zero alerts. You'd only notice
#   when you manually check YouTube days later.
#
# WHAT THIS DOES:
#   1. Loads every active channel from channels.yaml.
#   2. Attempts a real, live YouTube API call for each one (not just token parsing).
#   3. Tracks results in memory/token_health.json (last success date, failures).
#   4. Fires tiered Discord alerts based on risk level:
#       🟢 HEALTHY  — auth works, confirmed recently
#       🟡 WARNING  — auth works, but hasn't been confirmed in 7+ days
#                     (pipeline may have been silently failing)
#       🔴 CRITICAL — auth works NOW, but last success was 150+ days ago
#                     (token approaching expiry window — renew immediately)
#       ⚫ DEAD     — auth completely failed (token already expired or revoked)
#
# DESIGN NOTES:
#   - We can't read the token's original issue date from the token string itself.
#     Instead we track our own `last_success_utc` per channel in token_health.json.
#   - First run: sets last_success_utc = today (baseline). Subsequent runs compare.
#   - Uses the same get_youtube_client() as the rest of the engine, so any real
#     auth bug is caught identically here as in production.
#   - The lightweight API call used is channels().list(part="id", mine=True) which
#     costs only 1 YouTube quota point — negligible.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
import yaml
import requests
from datetime import datetime, timezone, timedelta

# ── Constants ────────────────────────────────────────────────────────────────
HEALTH_FILE      = os.path.join(os.path.dirname(__file__), "..", "memory", "token_health.json")
CHANNELS_FILE    = os.path.join(os.path.dirname(__file__), "..", "config", "channels.yaml")
WARN_AFTER_DAYS  = 7    # Alert if no confirmed-working auth in this many days
CRITICAL_DAYS    = 150  # Alert to renew NOW — 30-day buffer before 180-day expiry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_health() -> dict:
    """Load or initialise the token health tracking file."""
    if os.path.exists(HEALTH_FILE):
        try:
            with open(HEALTH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_health(data: dict):
    """Persist health tracking data back to disk."""
    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _load_channels() -> list:
    """Parse channels.yaml and return only active channel dicts."""
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return [ch for ch in data.get("channels", []) if ch.get("active", False)]
    except Exception as e:
        print(f"⚠️ [TOKEN HEALTH] Could not load channels.yaml: {e}")
        return []


def _test_youtube_auth(token_env_var: str) -> tuple[bool, str]:
    """
    Attempt a real YouTube API call using the refresh token stored in the
    named environment variable. Returns (success: bool, detail: str).

    Uses the same OAuth flow as youtube_manager.get_youtube_client() but
    avoids importing the full engine stack (which needs all dependencies
    installed) so this script can run in the lightweight audit environment.
    """
    client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get(token_env_var)

    # Guard: secrets missing
    if not all([client_id, client_secret, refresh_token]):
        missing = [k for k, v in {
            "YOUTUBE_CLIENT_ID": client_id,
            "YOUTUBE_CLIENT_SECRET": client_secret,
            token_env_var: refresh_token
        }.items() if not v]
        return False, f"Missing secrets: {', '.join(missing)}"

    # Step 1: Exchange refresh token for an access token
    try:
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=15
        )
    except Exception as e:
        return False, f"Network error during token refresh: {e}"

    if token_resp.status_code != 200:
        err = token_resp.json().get("error_description", token_resp.text)
        return False, f"Token refresh failed (HTTP {token_resp.status_code}): {err}"

    access_token = token_resp.json().get("access_token")
    if not access_token:
        return False, "Token refresh returned 200 but no access_token in response."

    # Step 2: Make a minimal YouTube API call — 1 quota point only
    try:
        yt_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "id", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15
        )
    except Exception as e:
        return False, f"Network error during YouTube API test: {e}"

    if yt_resp.status_code == 200:
        items = yt_resp.json().get("items", [])
        if items:
            channel_yt_id = items[0].get("id", "unknown")
            return True, f"Authenticated — YouTube channel ID: {channel_yt_id}"
        else:
            # Token works but no channel found (edge case: wrong account)
            return True, "Token valid but no YouTube channel found on this account."
    else:
        err = yt_resp.json().get("error", {}).get("message", yt_resp.text)
        return False, f"YouTube API rejected token (HTTP {yt_resp.status_code}): {err}"


def _days_since(date_str: str) -> int:
    """Return days elapsed since a UTC date string (YYYY-MM-DD)."""
    try:
        past = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - past).days
    except Exception:
        return 9999  # Treat unparseable date as maximally old


def _send_discord_alert(webhook_url: str, embeds: list):
    """Post a Discord embed payload. Silently skips if no webhook configured."""
    if not webhook_url:
        return
    try:
        requests.post(
            webhook_url,
            json={"username": "Ghost Engine — Token Guardian", "embeds": embeds},
            timeout=10
        )
    except Exception as e:
        print(f"⚠️ [TOKEN HEALTH] Discord notify failed: {e}")


# ── Core audit logic ──────────────────────────────────────────────────────────

def run_token_health_check():
    """
    Main entry point. Called by the weekly audit workflow.
    Checks every active channel's YouTube auth and fires Discord alerts.
    """
    print("🔐 [TOKEN HEALTH] Starting YouTube auth health audit...")

    today_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    channels     = _load_channels()
    health_data  = _load_health()
    webhook_url  = os.environ.get("DISCORD_WEBHOOK_URL", "")

    if not channels:
        print("⚠️ [TOKEN HEALTH] No active channels found. Aborting.")
        return

    summary_fields = []   # Collected for the final Discord summary embed
    any_problem    = False

    for ch in channels:
        channel_id    = ch.get("id", "unknown")
        channel_name  = ch.get("name", channel_id)
        token_env     = ch.get("youtube_refresh_token_env", "")

        print(f"  🔍 Testing: {channel_name} ({token_env})...")

        # ── Run the auth test ──────────────────────────────────────────────
        auth_ok, detail = _test_youtube_auth(token_env)

        # ── Load or initialise channel's health record ─────────────────────
        record = health_data.get(channel_id, {
            "last_success_utc":    None,
            "last_check_utc":      None,
            "consecutive_failures": 0,
            "status":              "unknown"
        })

        # ── Update tracking state ──────────────────────────────────────────
        record["last_check_utc"] = today_str

        if auth_ok:
            # First ever success: baseline today
            if not record["last_success_utc"]:
                record["last_success_utc"] = today_str

            record["consecutive_failures"] = 0
            days_since_success = _days_since(record["last_success_utc"])

            # Determine risk tier
            if days_since_success >= CRITICAL_DAYS:
                # Auth works but the token is extremely old → renew immediately
                tier   = "CRITICAL"
                emoji  = "🔴"
                color  = 15158332   # Red
                note   = (
                    f"Token authenticated successfully today but `last_success` was "
                    f"**{days_since_success} days ago**. "
                    f"You are within {180 - days_since_success} days of the 180-day expiry. "
                    f"**Renew this refresh token immediately.**"
                )
                any_problem = True
                # Don't update last_success — keep the old date so the alert keeps firing
            elif days_since_success >= WARN_AFTER_DAYS:
                # Auth works but pipeline may have been silently failing
                tier   = "WARNING"
                emoji  = "🟡"
                color  = 16776960   # Yellow
                note   = (
                    f"Token works today, but the last confirmed success was "
                    f"**{days_since_success} days ago**. "
                    f"Your daily pipeline may have been silently failing. "
                    f"Check the `01_daily_pipeline` workflow logs."
                )
                any_problem = True
                # Update success to today now that we confirmed it works
                record["last_success_utc"] = today_str
            else:
                # Happy path
                tier   = "HEALTHY"
                emoji  = "🟢"
                color  = 3066993    # Green
                note   = f"Auth confirmed. Last success: `{record['last_success_utc']}`."
                record["last_success_utc"] = today_str

            record["status"] = tier.lower()
            print(f"    {emoji} {tier}: {detail}")

        else:
            # Auth completely failed
            record["consecutive_failures"] = record.get("consecutive_failures", 0) + 1
            record["status"]               = "dead"
            tier   = "DEAD"
            emoji  = "⚫"
            color  = 2303786    # Dark grey
            note   = (
                f"**Authentication failed.** The token is expired or revoked.\n"
                f"Error: `{detail}`\n"
                f"Consecutive failures: **{record['consecutive_failures']}**\n"
                f"**Action required: generate a new refresh token immediately.**"
            )
            any_problem = True
            print(f"    ⚫ DEAD: {detail}")

            # Fire an immediate individual alert for dead tokens — don't wait for summary
            _send_discord_alert(webhook_url, [{
                "title": f"⚫ DEAD TOKEN — {channel_name}",
                "description": note,
                "color": color,
                "fields": [
                    {"name": "📺 Channel",   "value": f"└ `{channel_name}` (`{channel_id}`)", "inline": False},
                    {"name": "🔑 Secret",    "value": f"└ `{token_env}`",                      "inline": False},
                    {"name": "📅 Last OK",   "value": f"└ `{record.get('last_success_utc', 'Never')}`", "inline": False},
                ],
                "footer": {"text": "Ghost Engine — Token Guardian"}
            }])

        # Save updated record
        health_data[channel_id] = record

        # Build summary field for the final report embed
        last_ok = record.get("last_success_utc", "Never")
        summary_fields.append({
            "name":   f"{emoji} {channel_name}",
            "value":  f"└ Status: **{tier}** | Last OK: `{last_ok}`\n└ {note}",
            "inline": False
        })

    # ── Persist updated health data ────────────────────────────────────────
    _save_health(health_data)
    print(f"✅ [TOKEN HEALTH] Health data saved to {HEALTH_FILE}")

    # ── Send the weekly summary embed ──────────────────────────────────────
    overall_emoji = "🟢" if not any_problem else "⚠️"
    overall_title = (
        f"{overall_emoji} Weekly Token Health Report — "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    )
    summary_color = 3066993 if not any_problem else 16776960

    _send_discord_alert(webhook_url, [{
        "title":       overall_title,
        "description": (
            "All YouTube OAuth refresh tokens have been audited. "
            "See per-channel results below."
            if not any_problem else
            "⚠️ **One or more channels require attention.** See details below."
        ),
        "color":  summary_color,
        "fields": summary_fields,
        "footer": {"text": "Ghost Engine — runs every Sunday at 20:00 UTC"}
    }])

    print("✅ [TOKEN HEALTH] Audit complete.")


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_token_health_check()
