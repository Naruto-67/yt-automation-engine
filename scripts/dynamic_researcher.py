# scripts/dynamic_researcher.py
import re
import random
import json
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client
from engine.database import db
from engine.models import VideoJob, ChannelConfig
from engine.config_manager import config_manager

def _jaccard_similarity(str_a, str_b):
    tokens_a = set(re.findall(r'[a-z0-9]{2,}', str_a))
    tokens_b = set(re.findall(r'[a-z0-9]{2,}', str_b))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)

def get_deep_channel_context(youtube):
    if not youtube: return "No channel data available. You must rely purely on current internet trends."
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)
        
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)
        
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "Channel is brand new. Rely purely on current broad internet trends."
        
        stats_response = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids[:50])).execute()
        quota_manager.consume_points("youtube", 1)
        
        video_data = []
        for item in stats_response.get("items", []):
            title = item["snippet"]["title"]
            views = int(item["statistics"].get("viewCount", 0))
            likes = int(item["statistics"].get("likeCount", 0))
            video_data.append({"title": title, "views": views, "likes": likes})
            
        video_data.sort(key=lambda x: x["views"], reverse=True)
        top_vids = video_data[:3]
        
        context = "📊 CHANNEL PERFORMANCE REPORT (PAST 14 DAYS):\nTOP PERFORMING VIDEOS:\n"
        for v in top_vids:
            context += f"- Title: '{v['title']}' | Views: {v['views']} | Likes: {v['likes']}\n"
            
        return context
    except Exception as e:
        return "Failed to fetch stats. Generate broadly appealing viral niches."

def run_dynamic_research(channel_config: ChannelConfig, yt_client):
    if not quota_manager.can_afford_youtube(5):
        print(f"🛑 [QUOTA GUARDIAN] YouTube Quota limit reached for {channel_config.channel_name}. Aborting Research.")
        return

    print(f"🔎 [RESEARCHER] Fetching deep channel data for {channel_config.channel_name}...")
    channel_context = get_deep_channel_context(yt_client)
    
    with db._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM jobs WHERE channel_id = ? AND state != 'published' AND state != 'failed'", (channel_config.channel_id,))
        unprocessed_count = cursor.fetchone()[0]
        
    needed_topics = 21 - unprocessed_count
    
    if needed_topics <= 0:
        print(f"🛑 [RESEARCHER] Queue full for {channel_config.channel_name} ({unprocessed_count} topics). Skipping API call.")
        return
        
    print(f"📊 [RESEARCHER] Need exactly {needed_topics} topics to reach 21 capacity. Calling AI...")

    with db._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topic FROM jobs WHERE channel_id = ? ORDER BY id ASC", (channel_config.channel_id,))
        all_lines = [r[0].lower().strip() for r in cursor.fetchall()]
        
    historical_topics = set(all_lines[-200:])
    recent_history_str = "None"
    if all_lines:
        recent_history_str = "\n".join([f"- {t}" for t in all_lines[-20:]])

    prompt = f"""
    You are an Elite YouTube Shorts Strategist. Your job is to analyze live internet trends and generate EXACTLY {max(5, needed_topics + 5)} fresh video topics.
    
    Target Audience/Niche: {channel_config.niche}
    
    Review our channel data below. Use the "Explore and Exploit" framework:
    {channel_context}
    
    CRITICAL CREATIVE DIRECTIVE:
    Generate highly unique, bizarre, or fascinating topics strictly within the channel's niche. Do not give generic answers.
    
    ⚠️ NEGATIVE BOUNDARY (DO NOT REPEAT THESE RECENT TOPICS):
    {recent_history_str}
    
    Return ONLY a raw JSON array of objects. No intro text. Do not use markdown blocks.
    Format:
    [
        {{"niche": "Specific Sub-Niche", "topic": "Highly specific topic title"}}
    ]
    """

    try:
        raw_text, provider = quota_manager.generate_text(prompt, task_type="research")
        if not raw_text: raise Exception("All AI providers failed to respond.")

        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        start_idx = clean_json_str.find('[')
        end_idx = clean_json_str.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_target = clean_json_str[start_idx:end_idx+1]
            new_matrix = json.loads(json_target)
            unique_new_topics = []
            
            for item in new_matrix:
                topic_clean = item.get("topic", "").lower().strip()
                if not topic_clean:
                    continue
                
                is_duplicate = False
                for existing_topic in historical_topics:
                    if _jaccard_similarity(topic_clean, existing_topic) >= 0.60:
                        is_duplicate = True
                        break
                        
                if not is_duplicate:
                    unique_new_topics.append(item)
                    historical_topics.add(topic_clean) 
            
            random.shuffle(unique_new_topics)
            final_new_batch = unique_new_topics[:needed_topics]
            
            for item in final_new_batch:
                job = VideoJob(
                    channel_id=channel_config.channel_id,
                    topic=item.get('topic', '').strip(),
                    niche=item.get('niche', channel_config.niche)
                )
                db.upsert_job(job)
                
            print(f"✅ [RESEARCHER] Database updated. Added {len(final_new_batch)} perfectly timed topics for {channel_config.channel_name}.")
            notify_summary(True, f"🧠 **AI Researcher Update**\nQueue restocked for **{channel_config.channel_name}**. Generated {len(final_new_batch)} highly unique niches.")
        else: raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    for channel in config_manager.get_active_channels():
        print(f"--- 🚀 Commencing Research Cycle for {channel.channel_name} ---")
        yt_client = get_youtube_client(channel.youtube_refresh_token_env)
        run_dynamic_research(channel, yt_client)
