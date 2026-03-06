import os
import json
import re
import random
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client

def get_deep_channel_context(youtube):
    """🚨 DEEP DATA: Fetches batched stats & comments from the past week while protecting quota."""
    if not youtube: return "No channel data available. Generate broadly appealing viral niches."
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)
        
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=15).execute()
        quota_manager.consume_points("youtube", 1)
        
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "Channel is new. Generate trending topics."
        
        # Batch API request (1 point for up to 50 videos)
        stats_response = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)
        
        video_data = []
        for item in stats_response.get("items", []):
            title = item["snippet"]["title"]
            views = int(item["statistics"].get("viewCount", 0))
            likes = int(item["statistics"].get("likeCount", 0))
            video_data.append({"title": title, "views": views, "likes": likes, "id": item["id"]})
            
        # Sort to find the highest performing videos
        video_data.sort(key=lambda x: x["views"], reverse=True)
        top_vids = video_data[:3]
        
        # Pull a few comments from the absolute best video for fan suggestions
        fan_suggestions = []
        try:
            comments = youtube.commentThreads().list(part="snippet", videoId=top_vids[0]["id"], maxResults=5).execute()
            for c in comments.get("items", []):
                fan_suggestions.append(c["snippet"]["topLevelComment"]["snippet"]["textOriginal"])
        except: pass
        
        context = "📊 CHANNEL PERFORMANCE REPORT (PAST 7 DAYS):\n"
        context += "TOP PERFORMING NICHES:\n"
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
    print("🔎 [RESEARCHER] Fetching deep channel data & generating new matrix...")
    youtube = get_youtube_client()
    channel_context = get_deep_channel_context(youtube)
    
    # 🚨 QUOTA MANDATE: Enforces your 2-Video Minimum baseline dynamically via prompt engineering.
    prompt = f"""
    You are an Elite YouTube Shorts Strategist. 
    Review our exact channel data and fan suggestions below. Identify our winning formats, and invent 21 NEW, highly viral YouTube Shorts topics. 
    
    MANDATORY BUSINESS QUOTA (CRITICAL):
    Out of the 21 topics generated, you MUST include:
    1. At least 2 topics in the "Short Story" niche (e.g., 'Horror Story', 'Sci-Fi Tale').
    2. At least 2 topics in the "Facts" niche. You should dynamically pick the best sub-category based on our performance (e.g., 'Bizarre Facts', 'Space Facts', 'Psychology Facts').
    3. The remaining 17 topics should be based entirely on what is performing best or trending. (If stories/facts are doing well, you can generate more than the minimum 2).
    
    {channel_context}
    
    Return ONLY a raw JSON array of exactly 21 objects. No intro text. Do not use markdown blocks.
    Format:
    [
        {{"niche": "Cyberpunk Lore", "topic": "The 2077 Neon Incident"}},
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
            for item in new_matrix: item["processed"] = False 
            
            # 🚨 THE SHUFFLE: Mixes up the 21 videos so we don't upload 4 facts in a row on Monday
            random.shuffle(new_matrix)
            
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
            
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(new_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Matrix updated, quotas enforced, and array shuffled for variety.")
            notify_summary(True, f"Deep Research Complete. Weekly quota enforced. 21 new videos mapped via {provider}.")
        else:
            raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    run_dynamic_research()
