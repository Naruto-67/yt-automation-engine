import os
import json
from datetime import datetime
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary

def run_daily_analysis():
    print("📊 [CEO ENGINE] Running channel performance audit & self-improvement cycle...")
    
    # 1. Load current brain state
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    lessons = {"emphasize": ["Fast pacing"], "avoid": ["Boring intros"], "recent_tags": []}
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                lessons = json.load(f)
        except: pass

    youtube = get_youtube_client()
    if not youtube:
        print("⚠️ [CEO ENGINE] YouTube OAuth missing. Skipping live analytics.")
        return

    try:
        # 2. Fetch Live YouTube Data
        data = youtube.channels().list(part="statistics", mine=True).execute()["items"][0]
        stats = data["statistics"]
        views = int(stats.get("viewCount", 0))
        subs = int(stats.get("subscriberCount", 0))

        # 3. Gemini CEO Analysis
        print("🧠 [CEO ENGINE] Handing data to Gemini for strategic analysis...")
        prompt = f"""
        You are the AI CEO of a YouTube Automation channel. 
        Current Stats: {views} total views, {subs} subscribers.
        Current 'Emphasize' rules: {lessons.get('emphasize', [])}
        Current 'Avoid' rules: {lessons.get('avoid', [])}
        
        Based on algorithmic growth strategies for YouTube Shorts in 2026, update our creative rules.
        Provide 3 short, punchy rules to emphasize, and 3 things to strictly avoid.
        
        Return STRICTLY valid JSON:
        {{"emphasize": ["...", "...", "..."], "avoid": ["...", "...", "..."]}}
        """
        
        # FORCE Gemini for this task
        analysis_raw = quota_manager.generate_text(prompt, task_type="analysis")
        
        if analysis_raw:
            import re
            match = re.search(r'\{.*\}', analysis_raw.replace("```json", "").replace("```", ""), re.DOTALL)
            if match:
                new_rules = json.loads(match.group(0))
                lessons["emphasize"] = new_rules.get("emphasize", lessons["emphasize"])
                lessons["avoid"] = new_rules.get("avoid", lessons["avoid"])
                
                # Overwrite the brain
                with open(tracker_path, "w", encoding="utf-8") as f:
                    json.dump(lessons, f, indent=4)
                print("✅ [CEO ENGINE] Gemini successfully updated the system's brain.")
                notify_summary(True, f"CEO Engine updated brain. Views: {views}, Subs: {subs}")
                
    except Exception as e:
        print(f"❌ [CEO ENGINE] Analysis failed: {e}")

if __name__ == "__main__":
    run_daily_analysis()
