import re
import random
import json
import yaml
import os
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client
from engine.database import db
from engine.models import VideoJob, ChannelConfig
from engine.logger import logger

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "prompts.yaml")
    with open(path, "r", encoding="utf-8") as f: return yaml.safe_load(f)

def _jaccard_similarity(str_a, str_b):
    tokens_a, tokens_b = set(re.findall(r'[a-z0-9]{2,}', str_a.lower())), set(re.findall(r'[a-z0-9]{2,}', str_b.lower()))
    if not tokens_a or not tokens_b: return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

def get_deep_channel_context(youtube):
    if not youtube: return "No channel data."
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "Brand new channel."
        
        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        video_data = sorted([{"title": i["snippet"]["title"], "views": int(i["statistics"].get("viewCount", 0))} for i in stats.get("items", [])], key=lambda x: x["views"], reverse=True)
        return "📊 Top Content:\n" + "\n".join([f"- '{v['title']}' | Views: {v['views']}" for v in video_data[:3]])
    except Exception: return "Generate broad niches."

def run_dynamic_research(channel_config: ChannelConfig, yt_client):
    if not quota_manager.can_afford_youtube(10): return
    logger.research(f"Deep-scanning trends for {channel_config.channel_name}...")
    
    with db._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM jobs WHERE channel_id = ? AND state != 'published'", (channel_config.channel_id,))
        unprocessed_count = cursor.fetchone()[0]
        cursor.execute("SELECT topic FROM jobs WHERE channel_id = ?", (channel_config.channel_id,))
        historical_topics = [r[0].lower().strip() for r in cursor.fetchall()]
        
    needed = 21 - unprocessed_count
    if needed <= 0: return

    prompts_cfg = load_config_prompts()
    sys_msg = prompts_cfg['researcher']['system_prompt']
    user_msg = prompts_cfg['researcher']['user_template'].format(
        needed_count=max(5, needed + 5), niche=channel_config.niche,
        channel_context=get_deep_channel_context(yt_client),
        history_string=", ".join(historical_topics[-30:]) if historical_topics else "None"
    )

    try:
        raw_text, _ = quota_manager.generate_text(user_msg, task_type="research", system_prompt=sys_msg)
        if not raw_text: return

        new_topics = json.loads(raw_text.replace("```json", "").replace("```", "").strip())
        added_count = 0
        for item in new_topics:
            if added_count >= needed: break
            topic_clean = item.get("topic", "").strip()
            if not any(_jaccard_similarity(topic_clean, h) > 0.6 for h in historical_topics):
                db.upsert_job(VideoJob(channel_id=channel_config.channel_id, topic=topic_clean, niche=item.get("niche", channel_config.niche)))
                historical_topics.append(topic_clean.lower())
                added_count += 1
        
        logger.success(f"Added {added_count} unique topics to SQLite.")
        notify_summary(True, f"🧠 **Researcher**: Added {added_count} topics for {channel_config.channel_name}.")
    except Exception as e: logger.error(f"Research cycle failed: {e}")
