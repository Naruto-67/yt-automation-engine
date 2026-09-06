# scripts/discord_notifier.py — Ghost Engine
"""
Discord notification system. Design principles:

CHANNEL ROUTING:
  Every notification goes to the correct channel's webhook — always.
  AnimeRise alerts → DISCORD_WEBHOOK_CH1
  Topato alerts   → DISCORD_WEBHOOK_CH2
  The _ACTIVE_WEBHOOK is set per-channel before any pipeline step runs.
  System-wide alerts (crashes, audits) go to all active channel webhooks.

NOTIFICATION TIERS:
  🔕 SILENT  — no @mention, no ping. Default for all routine pipeline steps.
               (script gen, voice gen, visuals, rendering, vault)
  🔔 WEEKLY  — @here mention. Weekly channel report + research complete.
  🚨 CRITICAL — @everyone mention. Any unrecoverable error or crash.

EMBEDS:
  Rich Discord embeds with colour-coded sidebars, fields, timestamps, footers.
  No raw text walls. Every notification is scannable in 2 seconds.
"""
import os
import json
import time
import random
import traceback
import requests
from datetime import datetime, timezone

# ── Active channel state ──────────────────────────────────────────────────────
_ACTIVE_WEBHOOK  = os.environ.get("DISCORD_WEBHOOK_URL", "")
_ACTIVE_CHANNEL  = "System"
_ACTIVE_CHANNEL_ID = ""

# ── Mention tiers ─────────────────────────────────────────────────────────────
_MENTION_NONE     = ""
_MENTION_HERE     = "@here"
_MENTION_EVERYONE = "@everyone"

# ── Colour palette ────────────────────────────────────────────────────────────
_COLOR = {
    "green":   0x2ECC71,   # success, complete
    "blue":    0x3498DB,   # info, research, step
    "purple":  0x9B59B6,   # vault, storage
    "yellow":  0xF1C40F,   # warning, pulse
    "orange":  0xE67E22,   # provider swap, engagement
    "red":     0xE74C3C,   # error, critical
    "dark":    0x2C3E50,   # neutral system
    "teal":    0x1ABC9C,   # publish, schedule
    "pink":    0xFF6B9D,   # creative, story
}

# ── Emoji per pipeline step ───────────────────────────────────────────────────
_STEP_EMOJI = {
    "QUEUED":             "📋",
    "SCRIPT_GENERATION":  "✍️",
    "VOICE_GENERATION":   "🎙️",
    "VISUAL_GENERATION":  "🎨",
    "RENDERING":          "🎬",
    "VAULTED":            "🔒",
    "PUBLISHED":          "🚀",
    "FAILED":             "💀",
}


def set_channel_context(channel_config):
    """Call this before processing each channel to route webhooks correctly."""
    global _ACTIVE_WEBHOOK, _ACTIVE_CHANNEL, _ACTIVE_CHANNEL_ID
    if isinstance(channel_config, dict):
        env_key            = channel_config.get("discord_webhook_env", "")
        _ACTIVE_WEBHOOK    = os.environ.get(env_key, "")
        _ACTIVE_CHANNEL    = channel_config.get("channel_name", "System")
        _ACTIVE_CHANNEL_ID = channel_config.get("id", "")
    else:
        env_key            = getattr(channel_config, "discord_webhook_env", "")
        _ACTIVE_WEBHOOK    = os.environ.get(env_key, "")
        _ACTIVE_CHANNEL    = getattr(channel_config, "channel_name", "System")
        _ACTIVE_CHANNEL_ID = getattr(channel_config, "channel_id", "")


def _all_channel_webhooks() -> list[str]:
    """Return webhooks for every active channel — for system-wide broadcasts."""
    try:
        from engine.config_manager import config_manager
        return [
            wh for ch in config_manager.get_active_channels()
            if (wh := os.environ.get(ch.discord_webhook_env, ""))
        ]
    except Exception:
        return [w for w in [_ACTIVE_WEBHOOK] if w]


def _ts() -> str:
    """ISO-8601 timestamp for embed footers."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _send(webhook_url: str, payload: dict, retries: int = 2):
    """Low-level send with rate-limit handling. Never raises — logs and moves on."""
    if not webhook_url:
        return
    for attempt in range(retries + 1):
        try:
            time.sleep(random.uniform(0.8, 1.5))  # gentle throttle
            r = requests.post(webhook_url, json=payload, timeout=10)
            if r.status_code == 429:
                wait = float(r.json().get("retry_after", 5))
                print(f"⚠️ [DISCORD] Rate limited — waiting {wait:.1f}s")
                time.sleep(wait + 0.5)
                continue
            if r.status_code not in (200, 204):
                print(f"⚠️ [DISCORD] HTTP {r.status_code}: {r.text[:100]}")
            return
        except Exception:
            if attempt == retries:
                print(f"⚠️ [DISCORD] Failed after {retries+1} attempts:\n{traceback.format_exc()}")
            else:
                time.sleep(2)


def _send_embed(
    title: str,
    description: str,
    color: int,
    fields: list = None,
    footer_extra: str = "",
    mention: str = _MENTION_NONE,
    thumbnail_url: str = "",
    broadcast: bool = False,
):
    """
    Send a rich Discord embed.

    Parameters
    ----------
    title         : Embed title (no channel prefix — channel name goes in footer)
    description   : Main body text (markdown supported)
    color         : Left sidebar colour (use _COLOR dict)
    fields        : List of {"name": str, "value": str, "inline": bool}
    footer_extra  : Extra string appended to the footer timestamp
    mention       : _MENTION_NONE / _MENTION_HERE / _MENTION_EVERYONE
    thumbnail_url : Small image top-right of embed
    broadcast     : If True, send to ALL active channel webhooks (system alerts)
    """
    embed = {
        "title":       title,
        "color":       color,
        "footer":      {"text": f"Ghost Engine  •  {_ACTIVE_CHANNEL}  •  {_ts()}{('  •  ' + footer_extra) if footer_extra else ''}"},
    }
    if description:
        if len(description) > 3900:
            description = description[:3900] + "\n…"
        embed["description"] = description
    if fields:
        embed["fields"] = [
            {"name": f.get("name", ""), "value": f.get("value", "")[:1024], "inline": f.get("inline", False)}
            for f in fields[:25]
        ]
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    content = mention if mention else None
    payload = {"embeds": [embed]}
    if content:
        payload["content"] = content

    if broadcast:
        for wh in _all_channel_webhooks():
            _send(wh, payload)
    else:
        _send(_ACTIVE_WEBHOOK, payload)


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC NOTIFICATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Pipeline step progress (SILENT) ──────────────────────────────────────────
def notify_step(topic: str, step_name: str, details: str, color: int = _COLOR["blue"]):
    """Silent step notification. One line, no ping."""
    emoji = _STEP_EMOJI.get(step_name, "⚙️")
    _send_embed(
        title=f"{emoji} {step_name.replace('_', ' ').title()}",
        description=f"**{topic[:80]}**\n{details}",
        color=color,
    )


# ── Video vaulted (SILENT) ────────────────────────────────────────────────────
def notify_vault_secure(topic: str, video_id: str, vault_id: str):
    url = f"https://youtu.be/{video_id}" if video_id and "test" not in video_id else None
    _send_embed(
        title="🔒 Vaulted",
        description=f"**{topic[:80]}**",
        color=_COLOR["purple"],
        fields=[
            {"name": "YouTube Link", "value": f"[Watch]({url})" if url else "Test Mode", "inline": True},
            {"name": "Playlist",     "value": vault_id[:50] if vault_id else "—",        "inline": True},
        ],
    )


# ── Full production success dashboard (SILENT) ────────────────────────────────
def notify_production_success(
    niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai,
    metadata, duration, size, video_id="Unknown"
):
    safe_title = str(metadata.get("title", topic))[:95]
    safe_desc  = str(metadata.get("description", ""))[:300].replace("\n", " ")
    tags       = ", ".join(metadata.get("tags", []))[:150]
    preview    = (script[:350] + "…") if len(script) > 350 else script
    url        = f"https://youtu.be/{video_id}" if video_id and "test" not in video_id else None

    embeds = []

    # 1. Main Header
    embeds.append({
        "author": {"name": "✨ GHOST ENGINE PRODUCTION COMPLETE"},
        "title": f"🎬 {safe_title}",
        "url": url,
        "color": _COLOR["green"],
        "description": f"Successfully rendered and vaulted new video.",
        "fields": [
            {"name": "📺 Link", "value": f"[Watch on YouTube]({url})" if url else "Test Mode", "inline": True},
            {"name": "⏱️ Duration", "value": f"{duration:.1f}s", "inline": True},
            {"name": "💾 Size", "value": f"{size:.1f} MB", "inline": True},
        ]
    })

    # 2. SEO & Packaging
    embeds.append({
        "author": {"name": "🔍 SEO & PACKAGING"},
        "color": _COLOR["dark"],
        "description": f"**Description Preview:**\n`yaml\n{safe_desc}\n`\n**Tags:**\n{tags}",
    })

    # 3. Script Preview
    embeds.append({
        "author": {"name": "📜 SCRIPT PREVIEW"},
        "color": _COLOR["dark"],
        "description": f"> *{preview}*",
    })

    # 4. AI Stack Telemetry
    embeds.append({
        "author": {"name": "🧠 AI STACK TELEMETRY"},
        "color": _COLOR["dark"],
        "fields": [
            {"name": "Writer", "value": f"🔹 {script_ai}", "inline": True},
            {"name": "SEO", "value": f"🔹 {seo_ai}", "inline": True},
            {"name": "Voice", "value": f"🔹 {voice_ai}", "inline": True},
            {"name": "Vision", "value": f"🔹 {visual_ai}", "inline": True},
        ],
        "footer": {"text": f"Ghost Engine  •  {_ACTIVE_CHANNEL}  •  {_ts()}"}
    })

    _send(_ACTIVE_WEBHOOK, {"embeds": embeds})


# ── Research complete (WEEKLY PING) ───────────────────────────────────────────
def notify_research_complete(channel_name: str, added_count: int, niche: str, comp_summary: str):
    gap_text = ""
    if "CONTENT GAPS" in comp_summary:
        lines    = comp_summary.split("\n")
        gap_line = next((l for l in lines if "CONTENT GAPS" in l), "")
        gap_text = "\n".join(lines[lines.index(gap_line)+1 : lines.index(gap_line)+4]) if gap_line in lines else ""

    _send_embed(
        title="🔬 Research Complete",
        description=f"**{added_count} new topics queued** for {channel_name}",
        color=_COLOR["blue"],
        fields=[
            {"name": "🧬 Niche",           "value": niche[:100],              "inline": False},
            {"name": "🕳️ Competitor Gaps",  "value": f"`\n{gap_text[:280]}\n`" if gap_text else "N/A", "inline": False},
        ],
        mention=_MENTION_HERE,   # ← weekly ping
    )


# ── Daily pulse / weekly report dashboard (WEEKLY PING) ────────────────────────
def notify_daily_pulse(views: int, subs: int, growth_7d: int, intel: dict, analytics: dict = None):
    # Growth phase label
    if subs < 500:
        phase = "🚀 LAUNCH PHASE"
        phase_desc = "Focusing on broad variety and finding winning pillars."
    elif subs < 1000:
        phase = "📈 GROWTH PHASE"
        phase_desc = "Doubling down on proven categories and high retention."
    else:
        phase = "💰 MONETIZATION"
        phase_desc = "Optimizing for RPM and advertiser-friendly topics."

    ctr = analytics.get('ctr', 0.0) if analytics else 0.0
    ret = analytics.get('avg_view_pct', 0.0) if analytics else 0.0
    
    embeds = []

    # 1. Header & Topline Metrics
    embeds.append({
        "author": {"name": f"📊 WEEKLY CHANNEL REPORT  •  {_ACTIVE_CHANNEL}"},
        "color": _COLOR["yellow"],
        "description": f"**{phase}**\n{phase_desc}",
        "fields": [
            {"name": "👥 Subscribers", "value": f"`yaml\n{subs:,}\n`", "inline": True},
            {"name": "👀 Total Views", "value": f"`yaml\n{views:,}\n`", "inline": True},
            {"name": "🚀 7-Day Growth", "value": f"`yaml\n+{growth_7d:,}\n`", "inline": True},
        ]
    })
    
    # 2. Analytics Performance
    embeds.append({
        "author": {"name": "📈 ENGAGEMENT METRICS (28D)"},
        "color": _COLOR["dark"],
        "fields": [
            {"name": "🖱️ Click-Through Rate", "value": f"{ctr:.2f}%" if ctr else "No data", "inline": True},
            {"name": "⏳ Avg Retention", "value": f"{ret:.1f}%" if ret else "No data", "inline": True},
        ]
    })
    
    # 3. Channel Intelligence
    pillar_data = intel.get("title_templates", {})
    top_pillar = max(pillar_data, key=lambda k: pillar_data[k].get("total_views", 0)) if (isinstance(pillar_data, dict) and pillar_data) else "Need more data"
    
    embeds.append({
        "author": {"name": "🧠 CHANNEL INTELLIGENCE"},
        "color": _COLOR["dark"],
        "fields": [
            {"name": "📌 Top Performing Pillar", "value": f"**{top_pillar.upper()}**", "inline": True},
            {"name": "🎯 Active Niche", "value": f"*{intel.get('evolved_niche') or 'Default'}*", "inline": True},
        ],
        "footer": {"text": f"Ghost Engine Analysis  •  {_ts()}"}
    })

    _send(_ACTIVE_WEBHOOK, {"embeds": embeds, "content": _MENTION_HERE})


# ── Critical error (PING EVERYONE) ───────────────────────────────────────────
def notify_error(module: str, error_type: str, details: str):
    _send_embed(
        title="🚨 CRITICAL PIPELINE ERROR",
        description=f"**Module:** {module}\n**Type:** {error_type}",
        color=_COLOR["red"],
        fields=[
            {"name": "💬 Stacktrace / Details", "value": f"`python\n{details[:1000]}\n`", "inline": False},
        ],
        mention=_MENTION_EVERYONE,  # ← critical ping
        broadcast=True,             # ← goes to ALL channel webhooks
    )


# ── System Summary (SILENT on success, PING on failure) ──────────────────────
def notify_summary(success: bool, message: str, title: str = "System Summary", broadcast: bool = False):
    icon = "✅" if success else "⚠️"
    color = _COLOR["green"] if success else _COLOR["red"]
    mention = _MENTION_HERE if not success else _MENTION_NONE
    
    _send_embed(
        title=f"{icon} {title}",
        description=message[:2000],
        color=color,
        mention=mention,
        broadcast=broadcast,
    )


# ── Storage housekeeping (SILENT) ────────────────────────────────────────────
def notify_storage_report(db_size: int, repo_size: float, pruned_jobs: int, topics_trimmed: int):
    _send_embed(
        title="🧹 Storage Housekeeping",
        description="Weekly cleanup complete.",
        color=_COLOR["dark"],
        fields=[
            {"name": "🗄️ DB Size",       "value": f"{db_size} KB",      "inline": True},
            {"name": "📦 Repo Size",      "value": f"{repo_size:.1f} MB","inline": True},
            {"name": "✂️ Jobs Pruned",    "value": str(pruned_jobs),     "inline": True},
        ],
    )


# ── Token health (SILENT unless warning/critical) ─────────────────────────────
def notify_token_health(channel_id: str, status: str, days: int, action: str):
    status_map = {
        "HEALTHY":  (_COLOR["green"],  "✅", _MENTION_NONE),
        "WARNING":  (_COLOR["yellow"], "⚠️", _MENTION_NONE),    # silent yellow
        "CRITICAL": (_COLOR["red"],    "🚨", _MENTION_HERE),    # ping on critical token issue
    }
    color, icon, mention = status_map.get(status, (_COLOR["dark"], "ℹ️", _MENTION_NONE))
    _send_embed(
        title=f"{icon} Token Health — {status}",
        description=f"Channel: {channel_id}  •  Days unused: **{days}**",
        color=color,
        fields=[{"name": "🛠️ Action Required", "value": action, "inline": False}] if action else [],
        mention=mention,
    )


# ── Provider failover (SILENT) ────────────────────────────────────────────────
def notify_provider_swap(module: str, old_prov: str, new_prov: str):
    _send_embed(
        title="🔄 Provider Failover",
        description=f"{module}",
        color=_COLOR["orange"],
        fields=[
            {"name": "❌ Failed",      "value": old_prov, "inline": True},
            {"name": "✅ Swapped To",  "value": new_prov, "inline": True},
        ],
    )


# ── Quota warning (SILENT — informational only) ───────────────────────────────
def notify_quota_warning(provider: str, usage: int, limit: int):
    pct = int((usage / limit) * 100) if limit else 0
    _send_embed(
        title="⚠️ Quota Warning",
        description=f"**{provider}** is at {pct}% capacity",
        color=_COLOR["yellow"],
        fields=[
            {"name": "Usage", "value": f"{usage:,} / {limit:,}", "inline": True},
        ],
    )


# ── Published (SILENT) ───────────────────────────────────────────────────────
def notify_published(topic: str, video_id: str, publish_time: str):
    url = f"https://youtu.be/{video_id}" if video_id else "—"
    _send_embed(
        title="🚀 Video Scheduled",
        description=f"**{topic[:80]}**\n[Watch]({url})",
        color=_COLOR["teal"],
        fields=[
            {"name": "⏰ Publish Time", "value": publish_time, "inline": True},
        ],
    )


# ── Dead notification stubs (removed features — kept as no-ops to avoid import errors) ──
def notify_engagement_report(*args, **kwargs): pass
def notify_security_flag(*args, **kwargs): pass
