# scripts/discord_notifier.py — Ghost Engine V8.1
import os
import requests

_ACTIVE_WEBHOOK = None
_ACTIVE_CHANNEL = "Unknown Channel"

def set_channel_context(channel_config):
    global _ACTIVE_WEBHOOK, _ACTIVE_CHANNEL
    if isinstance(channel_config, dict):
        _ACTIVE_WEBHOOK = os.environ.get(channel_config.get("discord_webhook_env", ""))
        _ACTIVE_CHANNEL = channel_config.get("channel_name", "Unknown Channel")
    else:
        _ACTIVE_WEBHOOK = os.environ.get(getattr(channel_config, "discord_webhook_env", ""))
        _ACTIVE_CHANNEL = getattr(channel_config, "channel_name", "Unknown Channel")

def _send(content: str):
    if not _ACTIVE_WEBHOOK:
        return
    try:
        requests.post(_ACTIVE_WEBHOOK, json={"content": content}, timeout=10)
    except Exception as e:
        print(f"⚠️ [DISCORD] Failed to send webhook: {e}")

def notify_summary(success: bool, message: str):
    icon = "✅" if success else "🛑"
    msg = f"{icon} **System Summary** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 📝 **Message:** {message}"
    _send(msg)

def notify_error(module: str, error_type: str, details: str):
    msg = f"🚨 **SYSTEM ERROR** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🧩 **Module:** {module}\n"
    msg += f"└ ⚠️ **Type:** {error_type}\n"
    msg += f"└ 📝 **Details:** {details}"
    _send(msg)

def notify_step(topic: str, step_name: str, details: str, color: int = 0x3498db):
    msg = f"⚙️ **Step: {step_name}** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🎬 **Topic:** {topic}\n"
    msg += f"└ 📝 **Details:** {details}"
    _send(msg)

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, duration, size):
    msg = f"✅ **Production Complete** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🎬 **Topic:** {topic}\n"
    msg += f"└ 🧬 **Niche:** {niche}\n"
    msg += f"└ 🤖 **Script AI:** {script_ai}\n"
    msg += f"└ 🎙️ **Voice AI:** {voice_ai}\n"
    msg += f"└ 🎨 **Visual AI:** {visual_ai}\n"
    msg += f"└ 🔍 **SEO AI:** {seo_ai}\n"
    msg += f"└ ⏱️ **Duration:** {duration:.2f}s\n"
    msg += f"└ 💾 **Size:** {size:.2f} MB"
    _send(msg)

def notify_vault_secure(topic: str, video_id: str, vault_id: str):
    msg = f"🔒 **Video Vaulted** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🎬 **Topic:** {topic}\n"
    msg += f"└ 🔗 **Video ID:** {video_id}\n"
    msg += f"└ 📁 **Playlist:** {vault_id}"
    _send(msg)

def notify_published(topic: str, video_id: str, publish_time: str):
    msg = f"🚀 **Video Scheduled/Published** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🎬 **Topic:** {topic}\n"
    msg += f"└ 🔗 **Video ID:** {video_id}\n"
    msg += f"└ ⏰ **Target Time:** {publish_time}"
    _send(msg)

def notify_research_complete(channel_name: str, added_count: int, niche: str, comp_summary: str):
    msg = f"🔬 **Research Complete** | {channel_name}\n"
    msg += f"└ 🧬 **Niche:** {niche}\n"
    msg += f"└ 📥 **Topics Added:** {added_count}\n"
    if comp_summary:
        msg += f"└ 🏆 **Competitor Insight:** {comp_summary[:150]}..."
    _send(msg)

def notify_daily_pulse(views: int, subs: int, growth_7d: int, intel: dict):
    msg = f"📈 **Daily Pulse Report** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 👀 **Views:** {views:,}\n"
    msg += f"└ 👥 **Subs:** {subs:,}\n"
    msg += f"└ 🚀 **7D Growth:** {growth_7d:,} views\n"
    msg += f"└ 🎯 **Active Niche:** {intel.get('evolved_niche') or 'Default'}"
    _send(msg)

def notify_engagement_report(replies_sent: int, flagged_count: int):
    msg = f"💬 **Engagement Report** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ ✉️ **Replies Sent:** {replies_sent}\n"
    msg += f"└ 🛡️ **Comments Flagged:** {flagged_count}"
    _send(msg)

def notify_security_flag(author: str, comment: str, video_title: str):
    msg = f"🛡️ **Security Flag Triggered** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 👤 **Author:** {author}\n"
    msg += f"└ 🎬 **Video:** {video_title}\n"
    msg += f"└ 📝 **Comment:** {comment[:100]}..."
    _send(msg)

def notify_storage_report(db_size: int, repo_size: float, pruned_jobs: int, topics_trimmed: int):
    msg = f"🧹 **Storage Housekeeping** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🗄️ **DB Size:** {db_size} KB\n"
    msg += f"└ 📦 **Repo Size:** {repo_size:.1f} MB\n"
    msg += f"└ ✂️ **Jobs Pruned:** {pruned_jobs}"
    _send(msg)

def notify_token_health(channel_id: str, status: str, days: int, action: str):
    icon = "✅" if status == "HEALTHY" else "⚠️" if status == "WARNING" else "🚨"
    msg = f"{icon} **Token Health Report** | {channel_id}\n"
    msg += f"└ 📊 **Status:** {status}\n"
    msg += f"└ ⏳ **Days Unused:** {days}\n"
    if action:
        msg += f"└ 🛠️ **Action Req:** {action}"
    _send(msg)

def notify_quota_warning(provider: str, usage: int, limit: int):
    msg = f"⚠️ **Quota Warning** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🔌 **Provider:** {provider}\n"
    msg += f"└ 📊 **Usage:** {usage} / {limit}"
    _send(msg)

def notify_provider_swap(module: str, old_prov: str, new_prov: str):
    msg = f"🔄 **Provider Failover** | {_ACTIVE_CHANNEL}\n"
    msg += f"└ 🧩 **Module:** {module}\n"
    msg += f"└ ❌ **Failed:** {old_prov}\n"
    msg += f"└ ✅ **Swapped To:** {new_prov}"
    _send(msg)
