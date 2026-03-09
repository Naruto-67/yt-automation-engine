# scripts/token_health.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #1 — YouTube Refresh Token Silent Death Prevention
#
# BUG: When a token expires (~180 days unused), get_youtube_client() returns
# None, the orchestrator silently skips the channel, and your channel goes
# dark with zero alerts. You'd only notice days later when you check manually.
#
# FIX: Every Sunday this makes a REAL live OAuth call for each channel and
# sends tiered Discord alerts:
#   🟢 HEALTHY  — auth confirmed working
#   🟡 WARNING  — works today but no confirmed success in 7+ days
#   🔴 CRITICAL — works now but 150+ days since last success (renew NOW)
#   ⚫ DEAD     — auth completely failed (token expired or revoked)
#
# STATE: memory/token_health.json persists last_success_utc per channel so
# the day-counter survives week-to-week across ephemeral GitHub Actions runners.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import yaml
import requests
from datetime import datetime, timezone

HEALTH_FILE     = os.path.join(os.path.dirname(__file__), "..", "memory", "token_health.json")
CHANNELS_FILE   = os.path.join(os.path.dirname(__file__), "..", "config", "channels.yaml")
WARN_AFTER_DAYS = 7
CRITICAL_DAYS   = 150  # 30-day buffer before YouTube's 180-day expiry


def _load_health() -> dict:
    if os.path.exists(HEALTH_FILE):
        try:
            with open(HEALTH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_health(data: dict):
    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _load_channels() -> list:
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return [ch for ch in data.get("channels", []) if ch.get("active", False)]
    except Exception as e:
        print(f"⚠️ [TOKEN HEALTH] Could not load channels.yaml: {e}")
        return []


def _test_youtube_auth(token_env_var: str):
    """
    Makes a real live OAuth exchange + YouTube API call (1 quota point only).
    Returns (success: bool, detail: str).
    Intentionally does NOT import the engine stack — works in the lightweight
    audit environment that only has requests + pyyaml installed.
    """
    client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get(token_env_var)

    if not all([client_id, client_secret, refresh_token]):
        missing = [k for k, v in {
            "YOUTUBE_CLIENT_ID": client_id,
            "YOUTUBE_CLIENT_SECRET": client_secret,
            token_env_var: refresh_token,
        }.items() if not v]
        return False, f"Missing secrets: {', '.join(missing)}"

    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": client_id, "client_secret": client_secret,
                  "refresh_token": refresh_token, "grant_type": "refresh_token"},
            timeout=15,
        )
    except Exception as e:
        return False, f"Network error: {e}"

    if r.status_code != 200:
        return False, f"Token refresh failed (HTTP {r.status_code}): {r.json().get('error_description', r.text)}"

    access_token = r.json().get("access_token")
    if not access_token:
        return False, "Token refresh returned 200 but no access_token."

    try:
        yt = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "id", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
    except Exception as e:
        return False, f"YouTube API network error: {e}"

    if yt.status_code == 200:
        items = yt.json().get("items", [])
        ch_id = items[0].get("id", "no-channel") if items else "no-channel-found"
        return True, f"Authenticated — YouTube channel ID: {ch_id}"
    return False, f"YouTube API rejected token (HTTP {yt.status_code}): {yt.json().get('error', {}).get('message', yt.text)}"


def _discord(webhook_url: str, embeds: list):
    if not webhook_url:
        return
    try:
        requests.post(webhook_url,
                      json={"username": "Ghost Engine — Token Guardian", "embeds": embeds},
                      timeout=10)
    except Exception as e:
        print(f"⚠️ [TOKEN HEALTH] Discord notify failed: {e}")


def _days_since(date_str: str) -> int:
    try:
        past = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - past).days
    except Exception:
        return 9999


def run_token_health_check():
    print("🔐 [TOKEN HEALTH] Starting YouTube OAuth health audit...")
    today_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    channels    = _load_channels()
    health_data = _load_health()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")

    if not channels:
        print("⚠️ [TOKEN HEALTH] No active channels found. Aborting.")
        return

    summary_fields = []
    any_problem    = False

    for ch in channels:
        channel_id   = ch.get("id", "unknown")
        channel_name = ch.get("name", channel_id)
        token_env    = ch.get("youtube_refresh_token_env", "")

        print(f"  🔍 Testing: {channel_name} (secret env: {token_env})...")
        auth_ok, detail = _test_youtube_auth(token_env)

        record = health_data.get(channel_id, {
            "last_success_utc": None, "last_check_utc": None,
            "consecutive_failures": 0, "status": "unknown",
        })
        record["last_check_utc"] = today_str

        if auth_ok:
            if not record["last_success_utc"]:
                record["last_success_utc"] = today_str  # First-run baseline
            record["consecutive_failures"] = 0
            days_ok = _days_since(record["last_success_utc"])

            if days_ok >= CRITICAL_DAYS:
                tier, emoji, color = "CRITICAL", "🔴", 15158332
                note = (f"Token works but last confirmed success was **{days_ok} days ago**. "
                        f"Only **{180 - days_ok} days** until YouTube kills it. **Renew NOW.**")
                any_problem = True
                # Don't update last_success — keep this alert firing weekly until renewed
            elif days_ok >= WARN_AFTER_DAYS:
                tier, emoji, color = "WARNING", "🟡", 16776960
                note = (f"Token works today but last confirmed success was **{days_ok} days ago**. "
                        f"Check `01_daily_pipeline` logs — it may have been silently failing.")
                any_problem = True
                record["last_success_utc"] = today_str
            else:
                tier, emoji, color = "HEALTHY", "🟢", 3066993
                note = f"Auth confirmed. Last success: `{record['last_success_utc']}`."
                record["last_success_utc"] = today_str

            record["status"] = tier.lower()
            print(f"    {emoji} {tier}: {detail}")

        else:
            record["consecutive_failures"] = record.get("consecutive_failures", 0) + 1
            record["status"] = "dead"
            tier, emoji, color = "DEAD", "⚫", 2303786
            note = (f"**Auth FAILED.** Token expired or revoked.\n"
                    f"Error: `{detail}`\nConsecutive failures: **{record['consecutive_failures']}**\n"
                    f"**Your channel is not producing videos. Regenerate the token now.**")
            any_problem = True
            print(f"    ⚫ DEAD: {detail}")
            # Fire an immediate individual alert — don't wait for the summary
            _discord(webhook_url, [{
                "title": f"⚫ DEAD TOKEN — {channel_name}", "description": note, "color": color,
                "fields": [
                    {"name": "📺 Channel", "value": f"└ `{channel_name}` (`{channel_id}`)", "inline": False},
                    {"name": "🔑 Secret",  "value": f"└ `{token_env}`",                      "inline": False},
                    {"name": "📅 Last OK", "value": f"└ `{record.get('last_success_utc', 'Never')}`", "inline": False},
                ],
                "footer": {"text": "Ghost Engine — Token Guardian"},
            }])

        health_data[channel_id] = record
        last_ok = record.get("last_success_utc", "Never")
        summary_fields.append({
            "name":   f"{emoji} {channel_name}",
            "value":  f"└ **{tier}** | Last OK: `{last_ok}`\n└ {note}",
            "inline": False,
        })

    _save_health(health_data)
    print(f"✅ [TOKEN HEALTH] Saved to {HEALTH_FILE}")

    _discord(webhook_url, [{
        "title": f"{'🟢' if not any_problem else '⚠️'} Weekly Token Health — {today_str}",
        "description": ("All tokens healthy." if not any_problem
                        else "⚠️ **One or more channels need attention.**"),
        "color":  3066993 if not any_problem else 16776960,
        "fields": summary_fields,
        "footer": {"text": "Ghost Engine — runs every Sunday 20:00 UTC"},
    }])
    print("✅ [TOKEN HEALTH] Audit complete.")


if __name__ == "__main__":
    run_token_health_check()
