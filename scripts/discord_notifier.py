# scripts/discord_notifier.py — Ghost Engine V6
import os
import time
import random
import requests
from datetime import datetime
import pytz

# ─── COLOURS ─────────────────────────────────────────────────────────────────
C_SUCCESS  = 0x2ecc71   # Green
C_INFO     = 0x3498db   # Blue
C_WARN     = 0xf39c12   # Orange
C_ERROR    = 0xe74c3c   # Red
C_PURPLE   = 0x9b59b6   # Purple
C_DARK     = 0x34495e   # Dark slate
C_GOLD     = 0xf1c40f   # Yellow/gold


def _get_ist_time() -> str:
    ist = pytz.timezone("Asia/Kolkata")
    return datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")


def _get_webhook_url() -> str | None:
    """
    Resolves the correct Discord webhook URL for the current channel context.

    Priority:
      1. CURRENT_DISCORD_WEBHOOK_ENV (set by orchestrator / standalone script loops)
      2. DISCORD_WEBHOOK_MAIN (global fallback for single-channel or audit runs)
      3. DISCORD_WEBHOOK_URL (legacy fallback)
    """
    env_name    = os.environ.get("CURRENT_DISCORD_WEBHOOK_ENV")
    webhook_url = os.environ.get(env_name) if env_name else None

    if not webhook_url:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_MAIN") or \
                      os.environ.get("DISCORD_WEBHOOK_URL")

    return webhook_url


def set_channel_context(channel_config):
    """
    Call this at the start of every per-channel loop in standalone scripts.
    Ensures Discord messages go to the right channel's webhook.

    Usage:
        for channel in config_manager.get_active_channels():
            set_channel_context(channel)
            ...
    """
    os.environ["CURRENT_CHANNEL_ID"]            = channel_config.channel_id
    os.environ["CURRENT_DISCORD_WEBHOOK_ENV"]   = channel_config.discord_webhook_env


def _send_embed(title: str, color: int, fields: list,
                thumbnail: str = None) -> bool:
    """Core embed sender with anti-ban jitter and graceful fallback."""
    webhook_url = _get_webhook_url()
    if not webhook_url:
        ch_ctx = os.environ.get("CURRENT_CHANNEL_ID", "?")
        print(f"⚠️ [NOTIFIER] No webhook URL resolved for channel context: {ch_ctx}")
        return False

    # Human-pacing jitter to reduce webhook ban risk
    time.sleep(random.uniform(1.5, 3.5))

    payload = {
        "username":  "Ghost Engine AI",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2111/2111370.png",
        "embeds": [{
            "title":  title,
            "color":  color,
            "fields": fields,
            "footer": {"text": f"🕐 {_get_ist_time()}"}
        }]
    }
    if thumbnail:
        payload["embeds"][0]["thumbnail"] = {"url": thumbnail}

    try:
        r = requests.post(webhook_url, json=payload, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"🚨 [NOTIFIER] Discord request failed: {e}")
        return False


# ─── NOTIFICATION FUNCTIONS ───────────────────────────────────────────────────

def notify_step(topic: str, step: str, detail: str, color: int = C_INFO):
    """General-purpose step progress notification."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = f"⚙️ {step}",
        color  = color,
        fields = [
            {"name": "📺 Channel", "value": f"└ `{ch}`",    "inline": True},
            {"name": "🎬 Topic",   "value": f"└ {topic[:80]}", "inline": True},
            {"name": "📝 Detail",  "value": f"└ {detail[:500]}", "inline": False},
        ]
    )


def notify_production_success(niche, topic, script, script_ai, seo_ai,
                               voice_ai, visual_ai, metadata, duration, size):
    """Full production cycle success embed."""
    ch    = os.environ.get("CURRENT_CHANNEL_ID", "System")
    title = metadata.get("title", topic)[:100]
    _send_embed(
        title  = "🪬 Production Success",
        color  = C_PURPLE,
        fields = [
            {"name": "📺 Channel",    "value": f"└ `{ch}`",         "inline": True},
            {"name": "🎯 Niche",      "value": f"└ {niche.title()}", "inline": True},
            {"name": "🔥 SEO Title",  "value": f"└ {title}",         "inline": False},
            {"name": "🧠 AI Stack",
             "value": f"└ Script: **{script_ai}** | SEO: **{seo_ai}** | "
                      f"Voice: **{voice_ai}** | Visuals: **{visual_ai}**",
             "inline": False},
        ]
    )


def notify_vault_secure(topic: str, video_id: str, playlist_id: str):
    """Confirms a video has been uploaded to the private YouTube vault."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = "🔒 Vaulted Successfully",
        color  = C_SUCCESS,
        fields = [
            {"name": "📺 Channel",   "value": f"└ `{ch}`",               "inline": True},
            {"name": "🎬 Topic",     "value": f"└ {topic[:80]}",          "inline": True},
            {"name": "🆔 Video ID",  "value": f"└ `{video_id}`",          "inline": True},
            {"name": "🏦 Vault",     "value": f"└ Playlist: `{playlist_id}`", "inline": True},
        ]
    )


def notify_published(topic: str, video_id: str, publish_time: str):
    """Confirms a video has been scheduled for public release."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = "🚀 Video Scheduled",
        color  = C_SUCCESS,
        fields = [
            {"name": "📺 Channel",   "value": f"└ `{ch}`",               "inline": True},
            {"name": "🎬 Topic",     "value": f"└ {topic[:80]}",          "inline": True},
            {"name": "🕐 Publish At","value": f"└ {publish_time} UTC",    "inline": True},
            {"name": "🔗 Video",     "value": f"└ youtube.com/watch?v={video_id}", "inline": False},
        ]
    )


def notify_daily_pulse(views: int, subs: int, growth_7d: int, intel: dict):
    """Daily channel analysis results with strategy update."""
    ch      = os.environ.get("CURRENT_CHANNEL_ID", "System")
    new_emp = intel.get("emphasize", ["—"])[-1][:120]
    new_avo = intel.get("avoid", ["—"])[-1][:120]
    _send_embed(
        title  = "🔮 Daily Channel Pulse",
        color  = C_INFO,
        fields = [
            {"name": "📺 Channel",    "value": f"└ `{ch}`",              "inline": True},
            {"name": "📈 Stats",
             "value": f"└ Views: **{views:,}** | Subs: **{subs:,}** | +{growth_7d:,} (7d)",
             "inline": False},
            {"name": "✅ New Focus",  "value": f"└ {new_emp}",          "inline": False},
            {"name": "❌ Avoid",      "value": f"└ {new_avo}",          "inline": False},
        ]
    )


def notify_research_complete(channel_name: str, topics_added: int,
                              niche: str, competitor_insights: str = ""):
    """Weekly research cycle completion."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    fields = [
        {"name": "📺 Channel",    "value": f"└ `{ch}`",               "inline": True},
        {"name": "🧠 Topics Added","value": f"└ **{topics_added}** new", "inline": True},
        {"name": "🎯 Active Niche","value": f"└ {niche}",              "inline": False},
    ]
    if competitor_insights:
        fields.append({
            "name": "🔍 Competitor Intel",
            "value": f"└ {competitor_insights[:300]}",
            "inline": False
        })
    _send_embed(title="🧠 Research Complete", color=C_PURPLE, fields=fields)


def notify_engagement_report(replies_sent: int, flagged: int):
    """Comment engagement session summary."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = "💬 Engagement Report",
        color  = C_INFO,
        fields = [
            {"name": "📺 Channel",       "value": f"└ `{ch}`",                   "inline": True},
            {"name": "✅ Replies Sent",  "value": f"└ **{replies_sent}**",        "inline": True},
            {"name": "🛡️ Flagged",      "value": f"└ **{flagged}** blocked",     "inline": True},
        ]
    )


def notify_quota_warning(provider: str, current: int, limit: int):
    """High resource usage alert."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    pct = int((current / limit) * 100)
    _send_embed(
        title  = "⚡ Quota Warning",
        color  = C_WARN,
        fields = [
            {"name": "📺 Channel",  "value": f"└ `{ch}`",                        "inline": True},
            {"name": "⚠️ Provider", "value": f"└ **{provider.upper()}**",         "inline": True},
            {"name": "📊 Usage",    "value": f"└ {current}/{limit} ({pct}%)",     "inline": True},
        ]
    )


def notify_provider_swap(module: str, old_p: str, new_p: str):
    """Dynamic provider failover notification."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = "⚙️ Provider Failover",
        color  = C_WARN,
        fields = [
            {"name": "📺 Channel",  "value": f"└ `{ch}`",                    "inline": True},
            {"name": "🔄 Module",   "value": f"└ {module}",                  "inline": True},
            {"name": "↔️ Swap",     "value": f"└ `{old_p}` → `{new_p}`",    "inline": False},
        ]
    )


def notify_token_health(channel_id: str, status: str, days_old: int,
                         action_required: str = ""):
    """Weekly OAuth token health report."""
    colour = C_SUCCESS if status == "HEALTHY" else \
             C_WARN    if status in ("WARNING", "CRITICAL") else C_ERROR
    emoji  = {"HEALTHY": "🟢", "WARNING": "🟡", "CRITICAL": "🔴", "DEAD": "⚫"}.get(status, "❓")
    fields = [
        {"name": "📺 Channel",   "value": f"└ `{channel_id}`",             "inline": True},
        {"name": "🔑 Token",     "value": f"└ {emoji} **{status}**",        "inline": True},
        {"name": "📅 Age",       "value": f"└ {days_old} days old",         "inline": True},
    ]
    if action_required:
        fields.append({
            "name": "🚨 Action Required",
            "value": f"└ {action_required}",
            "inline": False
        })
    _send_embed(title="🔑 Token Health Check", color=colour, fields=fields)


def notify_storage_report(db_size_kb: int, repo_size_mb: float,
                           jobs_pruned: int, topics_trimmed: int):
    """Weekly storage housekeeping report."""
    _send_embed(
        title  = "🧹 Storage Housekeeping",
        color  = C_INFO,
        fields = [
            {"name": "🗄️ DB Size",       "value": f"└ {db_size_kb} KB",          "inline": True},
            {"name": "📦 Repo Size",      "value": f"└ {repo_size_mb:.1f} MB",    "inline": True},
            {"name": "🗑️ Jobs Pruned",   "value": f"└ {jobs_pruned}",             "inline": True},
            {"name": "📚 Topics Trimmed","value": f"└ {topics_trimmed}",          "inline": True},
        ]
    )


def notify_summary(success: bool, message: str):
    """Generic pipeline status log — used by orchestrator."""
    ch     = os.environ.get("CURRENT_CHANNEL_ID", "System")
    colour = C_PURPLE if success else C_ERROR
    icon   = "✅" if success else "❌"
    _send_embed(
        title  = f"{icon} System Update",
        color  = colour,
        fields = [
            {"name": "📺 Channel", "value": f"└ `{ch}`",      "inline": True},
            {"name": "📝 Status",  "value": f"└ {message[:800]}", "inline": False},
        ]
    )


def notify_error(module: str, error_type: str, message: str):
    """Critical crash reporting."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = "🚨 Critical System Crash",
        color  = C_ERROR,
        fields = [
            {"name": "📺 Channel",    "value": f"└ `{ch}`",                 "inline": True},
            {"name": "🧩 Module",     "value": f"└ {module}",               "inline": True},
            {"name": "⚠️ Error Type", "value": f"└ `{error_type}`",          "inline": True},
            {"name": "📜 Details",    "value": f"└ {message[:500]}",         "inline": False},
        ]
    )


def notify_identity_established(channel_id: str, niche: str):
    """Niche discovery or update confirmation."""
    _send_embed(
        title  = "✨ Identity Updated",
        color  = C_SUCCESS,
        fields = [
            {"name": "🆔 Channel",       "value": f"└ `{channel_id}`", "inline": True},
            {"name": "🎯 Active Niche",  "value": f"└ {niche}",        "inline": True},
        ]
    )


def notify_security_flag(user: str, text: str, title: str):
    """Security protocol triggered by a comment."""
    ch = os.environ.get("CURRENT_CHANNEL_ID", "System")
    _send_embed(
        title  = "🛡️ Security Protocol Triggered",
        color  = C_DARK,
        fields = [
            {"name": "📺 Channel",       "value": f"└ `{ch}`",      "inline": True},
            {"name": "👤 User",          "value": f"└ {user}",       "inline": True},
            {"name": "🎬 Video",         "value": f"└ {title}",      "inline": False},
            {"name": "🚫 Blocked Text",  "value": f"```{text[:200]}```", "inline": False},
        ]
    )


def notify_audit_report(findings: str):
    """Weekly stack audit results."""
    _send_embed(
        title  = "🛡️ Weekly Stack Audit",
        color  = C_INFO,
        fields = [
            {"name": "🔍 Findings", "value": f"└ {findings[:1000]}", "inline": False},
        ]
    )
