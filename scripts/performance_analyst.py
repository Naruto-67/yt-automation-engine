import os
import json
import re
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_daily_pulse

def run_daily_analysis():
    print("📊 [CEO ENGINE] Running channel performance audit & self-improvement cycle...")
    
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    safe_defaults = {
        "emphasize": ["Engineer seamless narrative loops to maximize watch time"],
        "avoid": ["Boring intros without immediate visual hooks"],
        "recent_tags": [],
        "preferred_visuals": []
    }
    
    lessons = dict(safe_defaults)
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                file_data = json.load(f)
                if isinstance(file_data, dict):
                    for key, value in file_data.items():
                        lessons[key] = value
                        
                    if not isinstance(lessons.get("emphasize"), list):
                        lessons["emphasize"] = safe_defaults["emphasize"]
                    if not isinstance(lessons.get("avoid"), list):
                        lessons["avoid"] = safe_defaults["avoid"]
                    if not isinstance(lessons.get("recent_tags"), list):
                        lessons["recent_tags"] = []
                    if not isinstance(lessons.get("preferred_visuals"), list):
                        lessons["preferred_visuals"] = []
        except Exception as load_err:
            print(f"⚠️ [CEO] Could not load lessons file, using defaults: {load_err}")

    youtube = get_youtube_client()
    if not youtube: return

    try:
        channel_req = youtube.channels().list(part="statistics", mine=True).execute()
        quota_manager.consume_points("youtube", 1)
        
        if not channel_req.get("items"):
            raise ValueError("No channel data found.")
            
        stats = channel_req["items"][0]["statistics"]
        views = max(int(stats.get("viewCount", 0)), 1)
        subs = max(int(stats.get("subscriberCount", 0)), 0)

        current_emphasize = "\n".join([f"- {r}" for r in lessons["emphasize"][-4:]])
        current_avoid = "\n".join([f"- {r}" for r in lessons["avoid"][-4:]])

        prompt = f"""
        You are the AI CEO of a YouTube Automation channel. 
        Current Stats: {views} total views, {subs} subscribers.
        
        Our current active strategies:
        {current_emphasize}
        
        What we currently avoid:
        {current_avoid}
        
        Based on algorithmic growth strategies for YouTube Shorts, give me ONE brand new rule to emphasize, and ONE brand new thing to avoid. Make them highly specific to psychological hooks and retention graphs.
        
        Return STRICTLY valid JSON:
        {{"new_emphasize": "...", "new_avoid": "..."}}
        """
        
        analysis_raw, _ = quota_manager.generate_text(prompt, task_type="analysis")
        
        if analysis_raw:
            match = re.search(r'\{.*\}', analysis_raw.replace("```json", "").replace("```", ""), re.DOTALL)
            if match:
                new_rules = json.loads(match.group(0))
                
                # Protect against LLM returning Lists instead of Strings
                new_emp = str(new_rules.get("new_emphasize", "")).strip()
                new_avo = str(new_rules.get("new_avoid", "")).strip()
                
                if new_emp and new_emp not in lessons["emphasize"]:
                    lessons["emphasize"].append(new_emp)
                if new_avo and new_avo not in lessons["avoid"]:
                    lessons["avoid"].append(new_avo)
                    
                lessons["emphasize"] = lessons["emphasize"][-5:]
                lessons["avoid"] = lessons["avoid"][-5:]
                
                tmp_path = tracker_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(lessons, f, indent=4)
                os.replace(tmp_path, tracker_path)
                    
                pulse_data = {
                    "emphasize": [new_emp if new_emp else lessons["emphasize"][-1]],
                    "avoid": [new_avo if new_avo else lessons["avoid"][-1]]
                }
                notify_daily_pulse(views, subs, pulse_data)
                
    except Exception as e:
        quota_manager.diagnose_fatal_error("performance_analyst.py", e)

if __name__ == "__main__":
    run_daily_analysis()
