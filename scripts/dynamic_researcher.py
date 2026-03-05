import os
import json
import re
from scripts.quota_manager import quota_manager

def run_dynamic_research():
    print("🔎 [RESEARCH] Scouring the live web for trends...")
    prompt = "Elite YouTube Strategist: Identify 21 viral topics (7 per niche: Fact, Brainrot, Story). Return RAW JSON array: [{'niche': '...', 'topic': '...', 'bg_query': '...'}]."
    
    try:
        # task_type="research" forces Gemini + Google Search Grounding
        raw = quota_manager.generate_text(prompt, task_type="research")
        if raw:
            clean = re.search(r'\[.*\]', raw.replace("```json", "").replace("```", ""), re.DOTALL).group(0)
            matrix = json.loads(clean)
            
            path = os.path.join("memory", "content_matrix.json")
            with open(path, "w", encoding="utf-8") as f: json.dump(matrix, f, indent=4)
            print(f"✅ Research Complete. {len(matrix)} topics locked.")
    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)
