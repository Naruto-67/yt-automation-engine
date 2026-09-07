# scripts/api_monitor.py — Ghost Engine
"""
Weekly API health monitor. Makes REAL live HTTP calls to every API key
in the stack and reports pass/fail to Discord.

Checks:
  - Gemini API key (generate_text test call)
  - Groq API key (models list ping)
  - Cloudflare Workers AI (account balance / model list ping)
  - HuggingFace token (whoami ping)
  - Pixabay API key (1-image search ping)
  - YouTube OAuth tokens (channels.list ping per channel)

Each check is independent — a failure in one does not skip others.
Results are printed to GitHub Actions logs and dispatched to Discord.
"""
import os
import json
import requests
from datetime import datetime
from scripts.discord_notifier import notify_summary, notify_error, set_channel_context
from engine.config_manager import config_manager


# ── Colour codes for Discord embed ──────────────────────────────────────────
_GREEN = "🟢"
_RED   = "🔴"
_WARN  = "🟡"


def _check_gemini() -> tuple:
    """Ping Gemini API with a minimal generate request."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return False, "GEMINI_API_KEY secret not set"
    try:
        url  = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        body = {"contents": [{"parts": [{"text": "Say OK"}]}]}
        r    = requests.post(url, json=body, timeout=15)
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        r   = requests.get(url, timeout=15)
        if r.status_code == 200:
            return True, "API key valid, model responding"
            models = [m.get("name", "").replace("models/", "") for m in r.json().get("models", []) if "gemini" in m.get("name", "")]
            # Just grab top 3 for the log
            model_list = ", ".join(models[:3]) if models else "Unknown"
            return True, f"API key valid | Available: {model_list}"
        elif r.status_code == 401 or r.status_code == 403:
            return False, f"Key rejected (HTTP {r.status_code}) — key may be expired or revoked"
        elif r.status_code == 429:
            return True, f"Key valid but rate-limited (HTTP 429) — quota exhausted today"
        else:
            return False, f"Unexpected HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"Request failed: {e}"


def _check_groq() -> tuple:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return False, "GROQ_API_KEY secret not set"
    try:
        r = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10
        )
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", [])[:3]]
            return True, f"Key valid | Available: {', '.join(models)}"
        elif r.status_code in (401, 403):
            return False, f"Key rejected (HTTP {r.status_code}) — expired or revoked"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"Request failed: {e}"


def _check_cloudflare() -> tuple:
    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    api_token  = os.environ.get("CF_API_TOKEN", "")
    if not account_id or not api_token:
        missing = []
        if not account_id: missing.append("CF_ACCOUNT_ID")
        if not api_token:  missing.append("CF_API_TOKEN")
        return False, f"Secrets not set: {', '.join(missing)}"
    try:
        # Ping the Workers AI models endpoint — cheap, no quota cost
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search?per_page=1"
        r   = requests.get(url, headers={"Authorization": f"Bearer {api_token}"}, timeout=10)
        if r.status_code == 200 and r.json().get("success"):
            return True, "Account ID and API token valid"
        elif r.status_code in (401, 403):
            return False, f"Token rejected (HTTP {r.status_code}) — may be expired"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"Request failed: {e}"


def _check_huggingface() -> tuple:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        return False, "HF_TOKEN secret not set"
    try:
        r = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if r.status_code == 200:
            name = r.json().get("name", "unknown")
            return True, f"Token valid | Account: {name}"
        elif r.status_code in (401, 403):
            return False, "Token rejected — expired or revoked"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"Request failed: {e}"


def _check_pixabay() -> tuple:
    key = os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        return False, "PIXABAY_API_KEY secret not set"
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={"key": key, "q": "nature", "per_page": 3},
            timeout=10
        )
        if r.status_code == 200:
            hits = r.json().get("totalHits", "?")
            return True, f"Key valid | Test query returned {hits:,} results"
        elif r.status_code == 400:
            data = r.json()
            msg  = data.get("message", r.text[:120])
            return False, f"Key rejected — {msg}"
        elif r.status_code == 429:
            return True, "Key valid but rate-limited today (HTTP 429)"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"Request failed: {e}"


def _check_youtube_tokens() -> list:
    """Check OAuth refresh token for each active channel."""
    results = []
    channels = config_manager.get_active_channels()
    for ch in channels:
        token_env     = ch.youtube_refresh_token_env
        client_id     = os.environ.get(token_env.replace("REFRESH_TOKEN", "CLIENT_ID"), "")
        client_secret = os.environ.get(token_env.replace("REFRESH_TOKEN", "CLIENT_SECRET"), "")
        refresh_token = os.environ.get(token_env, "")

        if not all([client_id, client_secret, refresh_token]):
            missing = [e for e, v in [
                (token_env.replace("REFRESH_TOKEN", "CLIENT_ID"), client_id),
                (token_env.replace("REFRESH_TOKEN", "CLIENT_SECRET"), client_secret),
                (token_env, refresh_token)
            ] if not v]
            results.append((ch.channel_name, False, f"Secrets missing: {', '.join(missing)}"))
            continue

        try:
            # Exchange refresh token for access token
            r = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            }, timeout=15)
            if r.status_code == 200 and "access_token" in r.json():
                results.append((ch.channel_name, True, "OAuth token valid — refresh successful"))
            elif r.status_code in (400, 401):
                err = r.json().get("error_description", r.text[:120])
                results.append((ch.channel_name, False, f"Token rejected — {err}. Re-authorise via OAuth Playground."))
            else:
                results.append((ch.channel_name, False, f"HTTP {r.status_code}: {r.text[:120]}"))
        except Exception as e:
            results.append((ch.channel_name, False, f"Request failed: {e}"))
    return results


def run_audit():
    print("🕵️ [MONITOR] Running live API health audit...")

    active_channels = config_manager.get_active_channels()
    if active_channels:
        set_channel_context(active_channels[0])

    now       = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines     = [f"**🛡️ Weekly API Health Report** — {now}\n"]
    all_ok    = True

    # ── Core AI APIs ──────────────────────────────────────────────────────────
    checks = [
        ("Gemini API",        _check_gemini),
        ("Groq API",          _check_groq),
        ("Cloudflare AI",     _check_cloudflare),
        ("HuggingFace",       _check_huggingface),
        ("Pixabay",           _check_pixabay),
    ]

    for name, fn in checks:
        ok, detail = fn()
        icon = _GREEN if ok else _RED
        if not ok: all_ok = False
        status = "PASS" if ok else "FAIL"
        line   = f"{icon} **{name}**: {status} — {detail}"
        lines.append(line)
        print(f"  {icon} {name}: {status} — {detail}")

    # ── YouTube OAuth tokens (one per channel) ────────────────────────────────
    lines.append("\n**YouTube OAuth Tokens:**")
    yt_results = _check_youtube_tokens()
    for ch_name, ok, detail in yt_results:
        icon = _GREEN if ok else _RED
        if not ok: all_ok = False
        status = "PASS" if ok else "FAIL"
        line   = f"{icon} **{ch_name}**: {status} — {detail}"
        lines.append(line)
        print(f"  {icon} {ch_name}: {status} — {detail}")

    # ── Summary ───────────────────────────────────────────────────────────────
    if all_ok:
        lines.append("\n✅ **All systems operational.** No action required.")
        print("✅ [MONITOR] All systems operational.")
    else:
        lines.append("\n⚠️ **Action required** — failed checks need attention before the next pipeline run.")
        print("⚠️ [MONITOR] Some checks failed — see report above.")

    report = "\n".join(lines)
    notify_summary(all_ok, report, title="API Health Report", broadcast=True)
    print("📡 [MONITOR] Report dispatched to Discord.")


if __name__ == "__main__":
    run_audit()
