# scripts/dynamic_researcher.py
import re
import random
import json
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client
from engine.database import db
from engine.models import VideoJob, ChannelConfig
from engine.logger import logger

def _jaccard_similarity(str_a, str_b):
    """Original V4 logic: Prevents topic overlap."""
    tokens_a = set(re.findall(r'[a-z0-9]{2,}', str_a.lower()))
    tokens_b = set(re.findall(r'[a-z0-9]{2,}', str_b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)

def get_deep_channel_context(youtube):
    """Original V4 logic: Analyzes channel history for trend alignment."""
    if not youtube: 
        return "No channel data. Rely on current broad internet trends."
    try:
        channels_res = youtube.channels().list(part="contentDetails", mine=True).execute()
        quota_manager.consume_points("youtube", 1)
        uploads_id = channels_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)
        
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: 
            return "Brand new channel. Use viral niche strategies."
        
        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)
        
        video_data = []
        for item in stats.get("items", []):
            video_data.append({
                "title": item["snippet"]["title"],
                "views": int(item["statistics"].get("viewCount", 0)),
                "likes": int(item["statistics"].get("likeCount", 0))
            })
            
        video_data.sort(key=lambda x: x["views"], reverse=True)
        top = video_data[:3]
        
        context = "📊 CHANNEL PERFORMANCE REPORT:\n"
        for v in top:
            context += f"- '{v['title']}' | Views: {v['views']}\n"
        return context
    except Exception as e:
        logger.error(f"Researcher context failed: {e}")
        return "Generate broadly appealing viral niches."

def run_dynamic_research(channel_config: ChannelConfig, yt_client):
    """V5 Implementation: Populates SQLite jobs table with AI-researched topics."""
    if not quota_manager.can_afford_youtube(10):
        logger.error("YouTube Quota too low for research.")
        return

    logger.research(f"Deep-scanning trends for {channel_config.channel_name}...")
    channel_context = get_deep_channel_context(yt_client)
    
    # Check current queue size in SQLite
    with db._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM jobs WHERE channel_id = ? AND state != 'published'", (channel_config.channel_id,))
        unprocessed_count = cursor.fetchone()[0]
        
    needed = 21 - unprocessed_count
    if needed <= 0:
        logger.research(f"Queue full ({unprocessed_count}/21). Research skipped.")
        return
        
    # Get historical topics from SQLite to avoid duplicates
    with db._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topic FROM jobs WHERE channel_id = ?", (channel_config.channel_id,))
        historical_topics = [r[0].lower().strip() for r in cursor.fetchall()]

    prompt = f"""
    You are an Elite YouTube Shorts Strategist. Generate {max(5, needed + 5)} fresh topics.
    Niche: {channel_config.niche}
    Channel Context: {channel_context}
    
    ⚠️ DO NOT REPEAT OR CLOSELY MATCH THESE TOPICS:
    {", ".join(historical_topics[-30:])}
    
    Return raw JSON array only: [{"niche": "...", "topic": "..."}]
    """

    try:
        raw_text, provider = quota_manager.generate_text(prompt, task_type="research")
        if not raw_text: return

        # Clean JSON
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        new_topics = json.loads(clean_json)
        
        added_count = 0
        for item in new_topics:
            if added_count >= needed: break
            
            topic_clean = item.get("topic", "").strip()
            # Jaccard Check
            is_dup = any(_jaccard_similarity(topic_clean, h) > 0.6 for h in historical_topics)
            
            if not is_dup:
                job = VideoJob(
                    channel_id=channel_config.channel_id,
                    topic=topic_clean,
                    niche=item.get("niche", channel_config.niche)
                )
                db.upsert_job(job)
                historical_topics.append(topic_clean.lower())
                added_count += 1
        
        logger.success(f"Added {added_count} unique topics to SQLite.")
        notify_summary(True, f"🧠 **Researcher**: Added {added_count} topics for {channel_config.channel_name}.")

    except Exception as e:
        logger.error(f"Research cycle failed: {e}")
