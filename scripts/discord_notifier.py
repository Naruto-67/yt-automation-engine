# scripts/discord_notifier.py
import os
import requests
import time
import random
import traceback

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

def _send_embed(title: str, description: str, color: int):
    if not _ACTIVE_WEBHOOK:
        return
        
    if len(description) > 3900:
        description = description[:3900] + "\n..."
        
    payload = {
        "embeds": [
            {
                "title": f"{title} | {_ACTIVE_CHANNEL}",
                "description": description,
                "color": color
            }
        ]
    }
    
    # 🚨 LEGACY RESTORE: Chaotic Biological Pacing
    time.sleep(random.uniform(2.5, 4.5))
    
    try:
        response = requests.post(_ACTIVE_WEBHOOK, json=payload, timeout=10)
        
        # 🚨 LEGACY RESTORE: Respect HTTP 429 Rate Limit Headers
        if response.status_code == 429:
            try:
                retry_after = response.json().get('retry_after', 5)
                print(f"⚠️ [DISCORD] Rate limited. Pausing for {retry_after}s to ensure delivery...")
                time.sleep(retry_after + 1)
                requests.post(_ACTIVE_WEBHOOK, json=payload, timeout=10)
            except Exception:
                pass
                
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [DISCORD] Failed to send webhook:\n{trace}")

def notify_summary(success: bool, message: str):
    icon = "✅" if success else "🛑"
    color = 0x2ecc71 if success else 0xe74c3c
    _send_embed(f"{icon} System Summary", f"└ 📝 **Message:** {message}", color)

def notify_error(module: str, error_type: str, details: str):
    desc = f"└ 🧩 **Module:** {module}\n└ ⚠️ **Type:** {error_type}\n└ 📝 **Details:** {details}"
    _send_embed("🚨 SYSTEM ERROR", desc, 0xe74c3c)

def notify_step(topic: str, step_name: str, details: str, color: int = 0x3498db):
    desc = f"└ 🎬 **Topic:** {topic}\n└ 📝 **Details:** {details}"
    _send_embed(f"⚙️ Step: {step_name}", desc, color)

def notify_production_success(niche, topic, script, script_ai, seo_ai, voice_ai, visual_ai, metadata, duration, size):
    desc = (f"└ 🎬 **Topic:** {topic}\n"
            f"└ 🧬 **Niche:** {niche}\n"
            f"└ 🤖 **Script AI:** {script_ai}\n"
            f"└ 🎙️ **Voice AI:** {voice_ai}\n"
            f"└ 🎨 **Visual AI:** {visual_ai}\n"
            f"└ 🔍 **SEO AI:** {seo_ai}\n"
            f"└ ⏱️ **Duration:** {duration:.2f}s\n"
            f"└ 💾 **Size:** {size:.2f} MB")
    _send_embed("✅ Production Complete", desc, 0x2ecc71)

def notify_vault_secure(topic: str, video_id: str, vault_id: str):
    desc = f"└ 🎬 **Topic:** {topic}\n└ 🔗 **Video ID:** {video_id}\n└ 📁 **Playlist:** {vault_id}"
    _send_embed("🔒 Video Vaulted", desc, 0x9b59b6)

def notify_published(topic: str, video_id: str, publish_time: str):
    desc = f"└ 🎬 **Topic:** {topic}\n└ 🔗 **Video ID:** {video_id}\n└ ⏰ **Target Time:** {publish_time}"
    _send_embed("🚀 Video Scheduled/Published", desc, 0x1abc9c)

def notify_research_complete(channel_name: str, added_count: int, niche: str, comp_summary: str):
    desc = f"└ 🧬 **Niche:** {niche}\n└ 📥 **Topics Added:** {added_count}\n"
    if comp_summary:
        desc += f"└ 🏆 **Competitor Insight:** {comp_summary[:150]}..."
    _send_embed("🔬 Research Complete", desc, 0x3498db)

def notify_daily_pulse(views: int, subs: int, growth_7d: int, intel: dict):
    desc = (f"└ 👀 **Views:** {views:,}\n"
            f"└ 👥 **Subs:** {subs:,}\n"
            f"└ 🚀 **7D Growth:** {growth_7d:,} views\n"
            f"└ 🎯 **Active Niche:** {intel.get('evolved_niche') or 'Default'}")
    _send_embed("📈 Daily Pulse Report", desc, 0xf1c40f)

def notify_engagement_report(replies_sent: int, flagged_count: int):
    desc = f"└ ✉️ **Replies Sent:** {replies_sent}\n└ 🛡️ **Comments Flagged:** {flagged_count}"
    _send_embed("💬 Engagement Report", desc, 0xe67e22)

def notify_security_flag(author: str, comment: str, video_title: str):
    desc = f"└ 👤 **Author:** {author}\n└ 🎬 **Video:** {video_title}\n└ 📝 **Comment:** {comment[:100]}..."
    _send_embed("🛡️ Security Flag Triggered", desc, 0xe74c3c)

def notify_storage_report(db_size: int, repo_size: float, pruned_jobs: int, topics_trimmed: int):
    desc = f"└ 🗄️ **DB Size:** {db_size} KB\n└ 📦 **Repo Size:** {repo_size:.1f} MB\n└ ✂️ **Jobs Pruned:** {pruned_jobs}"
    _send_embed("🧹 Storage Housekeeping", desc, 0x95a5a6)

def notify_token_health(channel_id: str, status: str, days: int, action: str):
    icon = "✅" if status == "HEALTHY" else "⚠️" if status == "WARNING" else "🚨"
    color = 0x2ecc71 if status == "HEALTHY" else 0xf1c40f if status == "WARNING" else 0xe74c3c
    desc = f"└ 📊 **Status:** {status}\n└ ⏳ **Days Unused:** {days}\n"
    if action:
        desc += f"└ 🛠️ **Action Req:** {action}"
    _send_embed(f"{icon} Token Health Report", desc, color)

def notify_quota_warning(provider: str, usage: int, limit: int):
    desc = f"└ 🔌 **Provider:** {provider}\n└ 📊 **Usage:** {usage} / {limit}"
    _send_embed("⚠️ Quota Warning", desc, 0xf1c40f)

def notify_provider_swap(module: str, old_prov: str, new_prov: str):
    desc = f"└ 🧩 **Module:** {module}\n└ ❌ **Failed:** {old_prov}\n└ ✅ **Swapped To:** {new_prov}"
    _send_embed("🔄 Provider Failover", desc, 0xe67e22)
