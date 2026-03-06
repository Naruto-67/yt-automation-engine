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
        self.gemini_text_limit = 250 
        self.gemini_blocked_for_run = False 
        
        self.TEXT_MODELS = [
            'gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-1.5-flash',
            'gemini-pro'
        ]
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
        last_error_msg = ""
        
        if task_type == "comment_reply":
            print("⚡ [ROUTER] Routing 'COMMENT_REPLY' strictly to Groq Llama 3.3...")
            return groq_client.generate_text(prompt, role="commenter"), "Groq Llama 3.3"

        if self.gemini_blocked_for_run:
            print(f"⚠️ [ROUTER] Gemini is resting. Auto-routing '{task_type.upper()}' to Groq Fallback.")
            return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3 (Fallback: Blocked globally for this run)"

        print(f"🛡️ [ROUTER] Attempting '{task_type.upper()}' via {self.TEXT_MODELS[0]}...")
        
        if usage < self.gemini_text_limit:
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_key)
            except ImportError:
                print("❌ [GEMINI] GenAI SDK missing. Falling back to Groq.")
                return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3 (Fallback: Missing SDK)"
            
            for model_name in self.TEXT_MODELS:
                try:
                    response = client.models.generate_content(
                        model=model_name, 
                        contents=prompt
                    )
                    self.consume_points("gemini", 1)
                    print("⏳ [ROUTER] Pacing API to avoid RPM bans (Sleeping 4s)...")
                    time.sleep(4)
                    return response.text, model_name
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    last_error_msg = error_msg[:50] # Keep it short for Discord
                    if "404" in error_msg or "not found" in error_msg:
                        continue 
                    elif "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                        print(f"⚠️ [ROUTER] Gemini 429 RPM Limit Hit on {model_name}!")
                        self.gemini_blocked_for_run = True
                        break 
                    else:
                        print(f"❌ [GEMINI] Non-rate-limit error on {model_name}: {e}")
                        break
        else:
            print(f"⚠️ [ROUTER] 50/50 Rule Limit Reached ({usage}/{self.gemini_text_limit}).")
            self.gemini_blocked_for_run = True 
            last_error_msg = "50/50 Safety Limit Reached"
            
        print("⚡ [ROUTER] Executing Fallback Protocol (Groq)...")
        fallback_text = groq_client.generate_text(prompt, role=task_type)
        return fallback_text, f"Groq Llama 3.3 (Fallback: {last_error_msg})"

quota_manager = MasterQuotaManager()
