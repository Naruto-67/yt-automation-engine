import os
import json
from datetime import datetime
from scripts.quota_manager import quota_manager

def get_optimal_publish_times():
    """Asks Gemini CEO for the best 2 times to post today."""
    print("🧠 [PUBLISHER] Asking Gemini CEO for optimal retention times...")
    prompt = """
    Based on global YouTube Shorts algorithms, what are the two absolute best times (in UTC format: HH:MM) 
    to post a short form video today to maximize initial feed spike?
    Return ONLY a valid JSON array of two time strings, e.g., ["14:30", "22:00"]
    """
    response = quota_manager.generate_text(prompt, task_type="analysis")
    try:
        import re
        match = re.search(r'\[.*\]', response.replace("```json", "").replace("```", "").strip(), re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except: pass
    return ["15:00", "23:00"] # Fallback default times

def run_publisher():
    print("📡 [PUBLISHER] Waking up. Scanning Vault...")
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
    
    if not os.path.exists(matrix_path):
        print("❌ [PUBLISHER] No memory found.")
        return

    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix = json.load(f)

    # Find videos that are vaulted but NOT published
    vault = [t for t in matrix if t.get("processed", False) and not t.get("published", False)]
    
    if len(vault) < 2:
        print(f"⚠️ [PUBLISHER] Not enough videos in the vault ({len(vault)}). Aborting publish to preserve backlog.")
        return

    # Sort the vault by the date they were created (oldest first)
    vault.sort(key=lambda x: x.get("vaulted_date", "2099-01-01"))
    videos_to_publish = vault[:2]
    
    times = get_optimal_publish_times()
    
    print(f"📅 [PUBLISHER] Scheduling 2 oldest videos for: {times[0]} UTC and {times[1]} UTC")
    
    for i, video in enumerate(videos_to_publish):
        print(f"   -> Publishing '{video['topic']}' at {times[i]}")
        # NOTE: Once Test Mode is off, the YouTube API code will be injected here 
        # to physically change the video from "Private" to "Public" at the scheduled time.
        
        # Mark as published in memory
        for matrix_item in matrix:
            if matrix_item['topic'] == video['topic']:
                matrix_item['published'] = True
                matrix_item['published_date'] = datetime.utcnow().isoformat()
                
    with open(matrix_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)
        
    print("✅ [PUBLISHER] Successfully scheduled today's content.")

if __name__ == "__main__":
    run_publisher()
