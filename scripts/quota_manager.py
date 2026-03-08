# scripts/quota_manager.py (Full Refined V5)
import os
import json
import traceback
import time
import re
from datetime import datetime, timezone
from scripts.groq_client import groq_client

class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.state_file = os.path.join(self.root_dir, "memory", "api_state.json")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        
        # Hard Limits
        self.LIMITS = {
            "gemini": 40,
            "cloudflare": 95,
            "huggingface": 50,
            "youtube": 9500
        }

    def _get_active_state(self):
        """Reads and auto-resets daily quotas based on UTC date."""
        if not os.path.exists(self.state_file):
            return self._reset_state()
        
        with open(self.state_file, 'r') as f:
            state = json.load(f)
            
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if state.get("last_reset_date") != today:
            return self._reset_state(today)
        return state

    def _reset_state(self, date_str=None):
        today = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_state = {
            "last_reset_date": today,
            "gemini_used": 0,
            "youtube_points_used": 0,
            "cf_images_used": 0,
            "hf_images_used": 0,
            "yt_last_used_date": today # POINT 11: Tracks inactivity
        }
        with open(self.state_file, 'w') as f:
            json.dump(new_state, f, indent=4)
        return new_state

    def consume_points(self, provider, amount):
        state = self._get_active_state()
        key_map = {
            "youtube": "youtube_points_used",
            "gemini": "gemini_used",
            "cloudflare": "cf_images_used",
            "huggingface": "hf_images_used"
        }
        
        key = key_map.get(provider)
        if key:
            state[key] += amount
            if provider == "youtube":
                state["yt_last_used_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=4)

    def can_afford_youtube(self, cost):
        state = self._get_active_state()
        return (state["youtube_points_used"] + cost) <= self.LIMITS["youtube"]

    def diagnose_fatal_error(self, module, exception):
        """POINT 20: Persistent Error Logging."""
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp = datetime.now().isoformat()
        err_type = type(exception).__name__
        trace = traceback.format_exc()
        
        with open(error_log, "a") as f:
            f.write(f"\n[{timestamp}] [{module}] {err_type}: {exception}\n{trace}\n{'-'*40}")
        
        from scripts.discord_notifier import notify_error
        notify_error(module, err_type, str(exception))

    def generate_text(self, prompt, task_type="creative", system_prompt=None):
        """POINT 7: Provider Registry (Gemini -> Groq Fallback)."""
        state = self._get_active_state()
        
        # Try Gemini first
        if state["gemini_used"] < self.LIMITS["gemini"]:
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_key)
                response = client.models.generate_content(
                    model='gemini-1.5-flash', 
                    contents=prompt,
                    config={'system_instruction': system_prompt} if system_prompt else None
                )
                self.consume_points("gemini", 1)
                return response.text, "Gemini 1.5 Flash"
            except Exception as e:
                print(f"⚠️ Gemini failed: {e}. Falling back to Groq...")

        # Fallback to Groq Llama 3.3 (POINT 7)
        res = groq_client.generate_text(prompt, system_prompt=system_prompt)
        return res, "Groq Llama 3.3"

quota_manager = MasterQuotaManager()
