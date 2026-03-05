import os
import json
import traceback
import time
from datetime import datetime
from scripts.groq_client import groq_client

class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.memory_dir = os.path.join(self.root_dir, "memory")
        self.state_file = os.path.join(self.memory_dir, "api_state.json")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.gemini_text_limit = 250 # The 50/50 Rule (50% of 500 RPD limit)
        self._ensure_state_exists()

    def _ensure_state_exists(self):
        os.makedirs(self.memory_dir, exist_ok=True)
        if not os.path.exists(self.state_file):
            self._reset_daily_state()

    def _reset_daily_state(self):
        new_state = {
            "last_reset_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "gemini_used": 0,
            "youtube_points_used": 0
        }
        self._write_state_file(new_state)

    def _read_state_file(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding="utf-8") as f:
                    return json.load(f)
            except: return {}
        return {}

    def _write_state_file(self, data):
        with open(self.state_file, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def _get_active_state(self):
        state = self._read_state_file()
        if state.get("last_reset_date") != datetime.utcnow().strftime("%Y-%m-%d"):
            self._reset_daily_state()
            return self._read_state_file()
        return state

    def consume_points(self, provider, amount):
        state = self._get_active_state()
        if provider == "youtube": state["youtube_points_used"] += amount
        elif provider == "gemini": state["gemini_used"] += amount
        self._write_state_file(state)

    def diagnose_fatal_error(self, module_name, exception_obj):
        tb = "".join(traceback.format_exception(type(exception_obj), exception_obj, exception_obj.__traceback__))
        print(f"\n🚨 [AI DOCTOR] Crash in {module_name}:\n{tb}\n")

    def generate_text(self, prompt, task_type="creative"):
        state = self._get_active_state()
        usage = state.get("gemini_used", 0)
        
        print(f"🛡️ [ROUTER] Routing '{task_type.upper()}' to Primary (Gemini 3.1 Flash Lite)...")
        
        if usage < self.gemini_text_limit:
            # RETRY LOGIC FOR RPM LIMITS
            for attempt in range(3):
                try:
                    from google import genai
                    client = genai.Client(api_key=self.gemini_key)
                    response = client.models.generate_content(
                        model='gemini-3.1-flash-lite', 
                        contents=prompt
                    )
                    self.consume_points("gemini", 1)
                    return response.text, "Gemini 3.1 Flash Lite"
                except Exception as e:
                    error_msg = str(e).lower()
                    if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                        print(f"⚠️ [ROUTER] Gemini 429 RPM Limit Hit! (Attempt {attempt+1}/3)")
                        print("⏳ [ROUTER] 50/50 Rule Active: Quota remaining. Waiting 60 seconds for RPM to reset...")
                        time.sleep(60)
                    else:
                        print(f"❌ [GEMINI] Non-rate-limit error: {e}")
                        break # Break loop, go to Fallback
        else:
            print(f"⚠️ [ROUTER] 50/50 Rule Limit Reached ({usage}/{self.gemini_text_limit}). Saving remaining quota.")
            
        print("⚡ [ROUTER] Executing Fallback Protocol (Groq)...")
        fallback_text = groq_client.generate_text(prompt, role=task_type)
        return fallback_text, "Groq Llama 3.3"

quota_manager = MasterQuotaManager()
