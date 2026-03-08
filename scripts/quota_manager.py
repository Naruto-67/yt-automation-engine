# scripts/quota_manager.py
import os
import traceback
import time
from datetime import datetime, timezone
from scripts.groq_client import groq_client
from engine.database import db
from engine.config_manager import config_manager

class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        
        # Load limits dynamically from settings.yaml
        settings = config_manager.get_settings()
        self.LIMITS = settings.get("api_limits", {
            "gemini": 40,
            "cloudflare": 95,
            "huggingface": 50,
            "youtube": 9500
        })

    def _get_active_state(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = db.get_quota_state(today)
        if not state:
            db.init_quota_state(today, today)
            state = db.get_quota_state(today)
        return state

    def consume_points(self, provider, amount):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key_map = {
            "youtube": "youtube_points",
            "gemini": "gemini_calls",
            "cloudflare": "cf_images",
            "huggingface": "hf_images"
        }
        
        col = key_map.get(provider)
        if col:
            yt_update = today if provider == "youtube" else None
            db.update_quota(today, col, amount, yt_update)

    def can_afford_youtube(self, cost):
        state = self._get_active_state()
        return (state["youtube_points"] + cost) <= self.LIMITS["youtube"]

    def diagnose_fatal_error(self, module, exception):
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp = datetime.now().isoformat()
        err_type = type(exception).__name__
        trace = traceback.format_exc()
        
        with open(error_log, "a") as f:
            f.write(f"\n[{timestamp}] [{module}] {err_type}: {exception}\n{trace}\n{'-'*40}")
        
        from scripts.discord_notifier import notify_error
        notify_error(module, err_type, str(exception))

    def generate_text(self, prompt, task_type="creative", system_prompt=None):
        state = self._get_active_state()
        chains = config_manager.get_providers().get("generation_chains", {})
        text_chain = chains.get("script", ["gemini", "groq"])
        
        for provider in text_chain:
            if provider == "gemini" and state["gemini_calls"] < self.LIMITS["gemini"]:
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
                    print(f"⚠️ Gemini fallback triggered: {e}")
                    
            elif provider == "groq" or provider == "groq_orpheus":
                try:
                    res = groq_client.generate_text(prompt, system_prompt=system_prompt)
                    if res: return res, "Groq Llama 3.3"
                except Exception as e:
                    print(f"⚠️ Groq fallback triggered: {e}")

        return None, "All Providers Exhausted"

quota_manager = MasterQuotaManager()
