import os
import json
import traceback
from datetime import datetime
from scripts.groq_client import groq_client

class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.memory_dir = os.path.join(self.root_dir, "memory")
        self.state_file = os.path.join(self.memory_dir, "api_state.json")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.gemini_blocked_for_run = False # 🚨 THE NEW TRIPWIRE
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
        
        # 1. CHECK THE TRIPWIRE FIRST
        if self.gemini_blocked_for_run:
            print(f"⚠️ [ROUTER] Gemini is cooling down. Auto-routing '{task_type.upper()}' to Groq Fallback.")
            return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3"

        print(f"🛡️ [ROUTER] Routing '{task_type.upper()}' to Primary (Gemini)...")
        
        if state.get("gemini_used", 0) < 1400: 
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_key)
                response = client.models.generate_content(
                    model='gemini-2.0-flash', 
                    contents=prompt
                )
                self.consume_points("gemini", 1)
                return response.text, "Gemini 2.0 Flash"
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ [GEMINI] Failed: {e}")
                
                # 🚨 IF RATE LIMITED, TRiP THE WIRE FOR THE REST OF THE RUN
                if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                    print("🚨 [ROUTER] Rate limit hit! Locking Gemini out for the rest of this workflow.")
                    self.gemini_blocked_for_run = True
                    
                print("⚡ [ROUTER] Executing Fallback Protocol...")
                return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3"
        else:
            self.gemini_blocked_for_run = True
            print("⚠️ [ROUTER] Gemini daily limit reached. Auto-routing to Groq.")
            return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3"

quota_manager = MasterQuotaManager()
