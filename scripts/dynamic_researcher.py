import os
import json
import re
import random
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client

def get_deep_channel_context(youtube):
    if not youtube: return "No channel data available. You must rely purely on current internet trends."
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)
        
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=15).execute()
        quota_manager.consume_points("youtube", 1)
        
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "Channel is brand new. Rely purely on current broad internet trends."
        
        stats_response = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)
        
        video_data = []
        for item in stats_response.get("items", []):
            title = item["snippet"]["title"]
            views = int(item["statistics"].get("viewCount", 0))
            likes = int(item["statistics"].get("likeCount", 0))
            video_data.append({"title": title, "views": views, "likes": likes, "id": item["id"]})
            
        video_data.sort(key=lambda x: x["views"], reverse=True)
        top_vids = video_data[:3]
        
        fan_suggestions = []
        try:
            comments = youtube.commentThreads().list(part="snippet", videoId=top_vids[0]["id"], maxResults=5).execute()
            for c in comments.get("items", []):
                fan_suggestions.append(c["snippet"]["topLevelComment"]["snippet"]["textOriginal"])
        except: pass
        
        context = "📊 CHANNEL PERFORMANCE REPORT (PAST 7 DAYS):\nTOP PERFORMING VIDEOS:\n"
        for v in top_vids:
            context += f"- Title: '{v['title']}' | Views: {v['views']} | Likes: {v['likes']}\n"
        
        if fan_suggestions:
            context += "\n💬 RECENT FAN COMMENTS / SUGGESTIONS:\n"
            for s in fan_suggestions: context += f"- \"{s}\"\n"
            
        return context
    except Exception as e:
        print(f"⚠️ [RESEARCHER] Data fetch error: {e}")
        return "Failed to fetch stats. Generate broadly appealing viral niches."

def run_dynamic_research():
    if not quota_manager.can_afford_youtube(5):
        print("🛑 [QUOTA GUARDIAN] YouTube Quota limit reached. Aborting Research to prevent ban.")
        return

    print("🔎 [RESEARCHER] Fetching deep channel data & generating new matrix...")
    youtube = get_youtube_client()
    channel_context = get_deep_channel_context(youtube)
    
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
    archive_path = os.path.join(root_dir, "memory", "topic_archive.txt")
    
    existing_matrix = []
    if os.path.exists(matrix_path):
        with open(matrix_path, "r", encoding="utf-8") as f:
            try: existing_matrix = json.load(f)
            except: pass

    unprocessed_count = len([i for i in existing_matrix if not i.get("processed", False) and not i.get("failed_flag", False)])
    needed_topics = 21 - unprocessed_count
    
    if needed_topics <= 0:
        print(f"🛑 [RESEARCHER] Matrix is already at maximum capacity ({unprocessed_count} topics). Skipping API call to save money.")
        return
        
    print(f"📊 [RESEARCHER] Need exactly {needed_topics} topics to reach 21 capacity. Calling AI...")

    # 🚨 FIX: Creative Lenses force the LLM out of repetitive loops over a 365-day cycle.
    lenses = [
        "Historical Anomalies and Forgotten Empires",
        "Deep Ocean Mysteries and Bizarre Biology",
        "Psychological Paradoxes and Mind Experiments",
        "Futuristic Tech and Cyberpunk Concepts",
        "Microscopic World and Invisible Sciences",
        "Space Oddities and Cosmic Terrors",
        "Glitches in the Matrix and Simulation Theories",
        "Unsolved Cryptography and Hidden Codes",
        "Bizarre Internet Subcultures and Digital Lore",
        "Ancient Mythology visualized through Sci-Fi"
    ]
    active_lens = random.choice(lenses)

    prompt = f"""
    You are an Elite YouTube Shorts Strategist. Your job is to analyze live internet trends and generate EXACTLY {max(5, needed_topics + 5)} fresh video topics.
    
    Review our channel data below. Use the "Explore and Exploit" framework:
    {channel_context}
    
    CRITICAL CREATIVE DIRECTIVE:
    To prevent repetitive content, you MUST filter all your ideas through this specific lens: "{active_lens}".
    Generate highly unique, bizarre, or fascinating topics that strictly fit this lens. Do not give generic answers.
    
    Return ONLY a raw JSON array of objects. No intro text. Do not use markdown blocks.
    Format:
    [
        {{"niche": "Liminal Spaces", "topic": "The infinite pool room experiment"}},
        ...
    ]
    """

    try:
        raw_text, provider = quota_manager.generate_text(prompt, task_type="research")
        if not raw_text: raise Exception("All AI providers failed to respond.")

        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            new_matrix = json.loads(match.group(0))
            
            historical_topics = set()
            if os.path.exists(archive_path):
                with open(archive_path, "r", encoding="utf-8") as f:
                    historical_topics = {line.strip().lower() for line in f.readlines() if line.strip()}
                    
            for item in existing_matrix:
                historical_topics.add(item.get("topic", "").lower().strip())
            
            preserved_items = []
            for i in existing_matrix:
                is_processed = i.get("processed", False)
                is_failed = i.get("failed_flag", False)
                is_published = i.get("published", False)
                
                if is_failed: continue
                
                if is_processed and not is_published:
                    preserved_items.append(i)
                elif not is_processed:
                    preserved_items.append(i)
            
            unique_new_topics = []
            for item in new_matrix:
                topic_clean = item.get("topic", "").lower().strip()
                if topic_clean not in historical_topics:
                    item["processed"] = False
                    unique_new_topics.append(item)
                    historical_topics.add(topic_clean) 
            
            random.shuffle(unique_new_topics)
            
            final_new_batch = unique_new_topics[:needed_topics]
            final_matrix = preserved_items + final_new_batch
            
            tmp_path = matrix_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(final_matrix, f, indent=4)
            os.replace(tmp_path, matrix_path)
                
            with open(archive_path, "a", encoding="utf-8") as f:
                for item in final_new_batch:
                    f.write(f"{item.get('topic', '').strip()}\n")
                
            print(f"✅ [RESEARCHER] Matrix updated. Kept {len(preserved_items)} queue items + added {len(final_new_batch)} perfectly timed topics.")
            notify_summary(True, f"🧠 **AI Researcher Update**\nQueue restocked using lens: *{active_lens}*. Generated {len(final_new_batch)} highly unique niches.")
        else: raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    run_dynamic_research()
