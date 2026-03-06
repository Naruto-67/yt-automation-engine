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
    
    prompt = f"""
    You are an Elite YouTube Shorts Strategist. Your job is to analyze live internet trends and build a 21-video content matrix for an AI automation channel.
    
    Review our channel data below. You must use the "Explore and Exploit" framework to build the 21 topics:
    
    MANDATORY BUSINESS QUOTA:
    1. THE BASELINE: At least 2 "Short Story" topics and 2 "Facts" topics (pick the best sub-category based on data or trends).
    2. THE EXPLOIT: 12 topics MUST double-down on whatever is currently working best in the channel data below. If a format or topic went viral, milk it.
    3. THE EXPLORE (WILDCARDS): 5 topics MUST be completely NEW, highly viral internet niches that are perfect for AI image generation.
    
    {channel_context}
    
    Return ONLY a raw JSON array of exactly 21 objects. No intro text. Do not use markdown blocks.
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
            
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
            
            existing_matrix = []
            if os.path.exists(matrix_path):
                with open(matrix_path, "r", encoding="utf-8") as f:
                    try: existing_matrix = json.load(f)
                    except: pass
            
            # 🚨 FIX: The "Amnesia Shield". Extract all historical topics to prevent duplicate content.
            historical_topics = {item.get("topic", "").lower().strip() for item in existing_matrix}
            
            # Keep only items that are completely valid queue items or vaulted
            preserved_items = []
            for i in existing_matrix:
                is_processed = i.get("processed", False)
                is_failed = i.get("failed_flag", False)
                is_published = i.get("published", False)
                
                if is_processed and not is_published:
                    preserved_items.append(i)
                elif not is_processed and not is_failed:
                    preserved_items.append(i)
            
            # Filter the AI's new suggestions to guarantee 100% uniqueness
            unique_new_topics = []
            for item in new_matrix:
                topic_clean = item.get("topic", "").lower().strip()
                if topic_clean not in historical_topics:
                    item["processed"] = False
                    unique_new_topics.append(item)
                    historical_topics.add(topic_clean) # Add to set to prevent duplicates within the new batch itself!
            
            random.shuffle(unique_new_topics)
            final_matrix = preserved_items + unique_new_topics
            
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(final_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Matrix updated. Kept {len(preserved_items)} queue items + {len(unique_new_topics)} UNIQUE new topics.")
            notify_summary(True, f"Deep Research Complete. Zombie topics purged. {len(unique_new_topics)} unique dynamic niches generated via {provider}.")
        else: raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    run_dynamic_research()
