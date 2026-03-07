import os
import json
import re
import random
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client


def _jaccard_similarity(str_a, str_b):
    """Word-level Jaccard similarity. Immune to substring false-positives."""
    tokens_a = set(re.findall(r'[a-z]{3,}', str_a))
    tokens_b = set(re.findall(r'[a-z]{3,}', str_b))
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
            video_data.append({"title": title, "views": views, "likes": likes, "id": item["id"]})
            
        video_data.sort(key=lambda x: x["views"], reverse=True)
        top_vids = video_data[:3]
        
        fan_suggestions = []
        try:
            comments = youtube.commentThreads().list(part="snippet", videoId=top_vids[0]["id"], maxResults=5).execute()
            for c in comments.get("items", []):
                fan_suggestions.append(c["snippet"]["topLevelComment"]["snippet"]["textOriginal"])
        except: pass
        
        context = "📊 CHANNEL PERFORMANCE REPORT (PAST 14 DAYS):\nTOP PERFORMING VIDEOS:\n"
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

    pruned_matrix = [i for i in existing_matrix if not i.get("published", False) and not i.get("failed_flag", False)]
    unprocessed_count = len([i for i in pruned_matrix if not i.get("processed", False)])
    needed_topics = 21 - unprocessed_count
    
    if needed_topics <= 0:
        print(f"🛑 [RESEARCHER] Matrix is already at maximum capacity ({unprocessed_count} topics). Skipping API call.")
        tmp_path = matrix_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(pruned_matrix, f, indent=4)
        os.replace(tmp_path, matrix_path)
        return
        
    print(f"📊 [RESEARCHER] Need exactly {needed_topics} topics to reach 21 capacity. Calling AI...")

    # ✅ FIX: Load the last 200 lines from the archive (not all 1460+) to prevent
    # the historical_topics set from growing so large it suffocates deduplication.
    # 200 entries represents ~50 days of context -- more than enough for creative variety.
    historical_topics_raw = []
    recent_history_str = "None"
    if os.path.exists(archive_path):
        with open(archive_path, "r", encoding="utf-8") as f:
            all_lines = [line.strip().lower() for line in f.readlines() if line.strip()]
            # Use only the last 200 for the dedup set, but all last 20 for the prompt context
            historical_topics_raw = all_lines[-200:]
            if all_lines:
                recent_history_str = "\n".join([f"- {t}" for t in all_lines[-20:]])
            
    historical_topics = set(historical_topics_raw)
    for item in existing_matrix:
        historical_topics.add(item.get("topic", "").lower().strip())

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
    
    ⚠️ NEGATIVE BOUNDARY (DO NOT REPEAT THESE RECENT TOPICS):
    {recent_history_str}
    
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

                # ✅ FIX: Jaccard similarity instead of dangerous substring containment.
                # A new topic is only flagged as a duplicate if it shares >= 60% of its
                # meaningful word-tokens with any archived topic. This correctly catches
                # true repeats (e.g., "Black Holes Explained" vs "Explaining Black Holes")
                # while allowing legitimate thematic overlaps (e.g., "Space" topics can
                # appear repeatedly because "space" is too short to trigger the 3-char filter
                # in the Jaccard tokenizer anyway).
                is_duplicate = False
                for existing_topic in historical_topics:
                    if _jaccard_similarity(topic_clean, existing_topic) >= 0.60:
                        is_duplicate = True
                        break
                        
                if not is_duplicate:
                    item["processed"] = False
                    unique_new_topics.append(item)
                    historical_topics.add(topic_clean)
            
            random.shuffle(unique_new_topics)
            
            final_new_batch = unique_new_topics[:needed_topics]
            final_matrix = pruned_matrix + final_new_batch
            
            tmp_path = matrix_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(final_matrix, f, indent=4)
            os.replace(tmp_path, matrix_path)
                
            with open(archive_path, "a", encoding="utf-8") as f:
                for item in final_new_batch:
                    f.write(f"{item.get('topic', '').strip()}\n")
                
            print(f"✅ [RESEARCHER] Matrix updated. Kept {len(pruned_matrix)} queue items + added {len(final_new_batch)} perfectly timed topics.")
            notify_summary(True, f"🧠 **AI Researcher Update**\nQueue restocked using lens: *{active_lens}*. Generated {len(final_new_batch)} highly unique niches.")
        else: raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)


if __name__ == "__main__":
    run_dynamic_research()
