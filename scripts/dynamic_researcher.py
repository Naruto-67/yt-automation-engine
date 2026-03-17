# scripts/dynamic_researcher.py
# Ghost Engine V26.0.0 — Multi-Lens Trend Discovery & Niche Evolution
import re
import json
import yaml
import os
import random
import traceback
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import set_channel_context, notify_research_complete, notify_summary
from engine.database import db
from engine.models import VideoJob, ChannelConfig
from engine.logger import logger

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def _jaccard_similarity(a: str, b: str) -> float:
    """Detects topic overlap to prevent duplicate content [cite: 203-204]"""
    ta = set(re.findall(r'[a-z0-9]{2,}', a.lower()))
    tb = set(re.findall(r'[a-z0-9]{2,}', b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def get_deep_channel_context(youtube) -> str:
    """Analyzes the channel's own top-performing content [cite: 205-210]"""
    if not youtube: return "No channel data."
    try:
        uploads_id = youtube.channels().list(
            part="contentDetails", mine=True
        ).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        vids = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=20
        ).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "Brand new channel — generate broad content."

        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)

        video_data = sorted([
            {"title": i["snippet"]["title"], "views": int(i["statistics"].get("viewCount", 0))}
            for i in stats.get("items", [])
        ], key=lambda x: x["views"], reverse=True)[:5]

        return "📊 Current Top Content:\n" + "\n".join([f"- '{v['title']}' | {v['views']:,} views" for v in video_data])
    except Exception as e:
        logger.error(f"Context fetch failed: {e}")
        return "Generate broad niches."

def research_competitors(youtube, niche: str) -> str:
    """Scans competitors to find what is working in the niche [cite: 211-218]"""
    if not youtube: return ""
    try:
        search = youtube.search().list(
            part="snippet", type="channel", q=niche, order="relevance", maxResults=3
        ).execute()
        quota_manager.consume_points("youtube", 100)

        competitor_ids = [item["snippet"]["channelId"] for item in search.get("items", [])]
        insights = []
        for ch_id in competitor_ids:
            ch_res = youtube.channels().list(part="contentDetails,snippet", id=ch_id).execute()
            quota_manager.consume_points("youtube", 1)
            
            uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            pl_items = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=5).execute()
            quota_manager.consume_points("youtube", 1)
            
            insights.append(f"Channel: {ch_res['items'][0]['snippet']['title']}\n" + 
                            "\n".join([f"  - '{v['snippet']['title']}'" for v in pl_items.get("items", [])]))
        return "\n\n".join(insights)
    except Exception:
        return ""

def _generate_topics(channel_config: ChannelConfig, needed: int, channel_context: str, competitor_context: str, historical_topics: list, prompts_cfg: dict, active_niche: str):
    """V26: Uses AI to find topics filtered through Creative Lenses [cite: 219-225]"""
    sys_msg  = prompts_cfg["researcher"]["system_prompt"]
    user_msg = prompts_cfg["researcher"]["user_template"].format(
        needed_count=needed,
        niche=active_niche,
        channel_context=channel_context + f"\n\n🏆 COMPETITORS:\n{competitor_context}",
        history_string=", ".join(historical_topics[-100:]) if historical_topics else "None"
    )
    
    # V26 Logic: Force all ideas through a random Creative Lens from channels.yaml [cite: 220-221]
    if channel_config.creative_lenses:
        lens = random.choice(channel_config.creative_lenses)
        user_msg += f"\n\n🚨 CRITICAL: Filter all ideas through this Creative Lens: '{lens}'. Make them bizarre."

    raw, _ = quota_manager.generate_text(user_msg, task_type="research", system_prompt=sys_msg)
    try:
        start, end = raw.find('{'), raw.rfind('}')
        if start != -1 and end != -1:
            data = json.loads(raw[start:end+1])
            return data.get("topics", []), data.get("evolved_niche")
    except Exception:
        logger.error("Failed to parse AI research JSON.")
    return [], None

def run_dynamic_research(channel_config: ChannelConfig, yt_client):
    """Main Orchestrator for trend research [cite: 226-241]"""
    if not quota_manager.can_afford_youtube(150): return
    set_channel_context(channel_config)
    
    unprocessed = db.get_unprocessed_count(channel_config.channel_id)
    needed = 21 - unprocessed
    if needed <= 0: return

    logger.research(f"Deep-scanning trends for {channel_config.channel_name}...")
    prompts_cfg = load_config_prompts()
    historical_topics = db.get_all_historical_topics(channel_config.channel_id)
    
    channel_context = get_deep_channel_context(yt_client)
    intel = db.get_channel_intelligence(channel_config.channel_id)
    active_niche = intel.get("evolved_niche") or channel_config.niche
    
    competitor_context = research_competitors(yt_client, active_niche)
    
    new_topics, evolved_niche = _generate_topics(
        channel_config, needed, channel_context, competitor_context, historical_topics, prompts_cfg, active_niche
    )

    added_count = 0
    for item in new_topics:
        topic_text = item.get("topic", "") if isinstance(item, dict) else str(item)
        if not topic_text: continue
        
        # Prevent repetitive content [cite: 236-237]
        if any(_jaccard_similarity(topic_text, h) > 0.6 for h in historical_topics): continue
        
        db.upsert_job(VideoJob(channel_id=channel_config.channel_id, topic=topic_text, niche=active_niche))
        db.archive_topic(channel_config.channel_id, topic_text, active_niche)
        historical_topics.append(topic_text.lower())
        added_count += 1

    if evolved_niche and evolved_niche != active_niche:
        intel["evolved_niche"] = evolved_niche
        db.upsert_channel_intelligence(channel_config.channel_id, intel)

    logger.success(f"Added {added_count} unique topics for {channel_config.channel_name}.")
    notify_research_complete(channel_config.channel_name, added_count, active_niche, competitor_context[:150])
