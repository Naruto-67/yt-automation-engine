import os
import json
import traceback
import time
import hashlib
from datetime import datetime
from scripts.groq_client import groq_client

class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.memory_dir = os.path.join(self.root_dir, "memory")
        self.state_file = os.path.join(self.memory_dir, "api_state.json")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        
        self.gemini_text_limit = 250 
        self.cloudflare_image_limit = 95 
        self.hf_image_limit = 50 
        
        # 🚨 YOUTUBE QUOTA GUARDIAN (Limit is 10k, we cap at 9500 to be safe)
        self.yt_quota_limit = 9500 
        self.gemini_blocked_for_run = False 
        
        self.TEXT_MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-pro']
        self._ensure_state_exists()

    def _ensure_state_exists(self):
        os.makedirs(self.memory_dir, exist_ok=True)
        if not os.path.exists(self.state_file):
            self._reset_daily_state()

    def _reset_daily_state(self):
        # 🚨 Preserves the Token Hash across daily resets!
        old_state = self._read_state_file()
        new_state = {
            "last_reset_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "gemini_used": 0,
            "youtube_points_used": 0,
            "cf_images_used": 0,
            "hf_images_used": 0,
            "yt_token_hash": old_state.get("yt_token_hash", ""),
            "yt_token_date": old_state.get("yt_token_date", datetime.utcnow().strftime("%Y-%m-%d"))
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
        if provider == "youtube": state["youtube_points_used"] = state.get("youtube_points_used", 0) + amount
        elif provider == "gemini": state["gemini_used"] = state.get("gemini_used", 0) + amount
        elif provider == "cloudflare": state["cf_images_used"] = state.get("cf_images_used", 0) + amount
        elif provider == "huggingface": state["hf_images_used"] = state.get("hf_images_used", 0) + amount
        self._write_state_file(state)

    def can_afford_youtube(self, cost):
        """Checks if a YT action will push us over the 10,000 limit."""
        return self._get_active_state().get("youtube_points_used", 0) + cost <= self.yt_quota_limit

    def check_and_update_refresh_token(self):
        """🚨 Security Tracker: Hashes token, checks age, sends Discord warning if > 120 days."""
        current_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
        if not current_token: return
        
        token_hash = hashlib.sha256(current_token.encode()).hexdigest()
        state = self._get_active_state()
        
        # If the hash changed, you updated the token! Reset the clock.
        if state.get("yt_token_hash", "") != token_hash:
            state["yt_token_hash"] = token_hash
            state["yt_token_date"] = datetime.utcnow().strftime("%Y-%m-%d")
            self._write_state_file(state)
            
        date_str = state.get("yt_token_date", datetime.utcnow().strftime("%Y-%m-%d"))
        token_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_active = (datetime.utcnow() - token_date).days
        
        # Ping Discord every day if the token is over 4 months old
        if days_active >= 120:
            from scripts.discord_notifier import notify_token_expiry
            notify_token_expiry(days_active)

    def is_provider_exhausted(self, provider):
        state = self._get_active_state()
        if provider == "cloudflare": return state.get("cf_images_used", 0) >= self.cloudflare_image_limit
        if provider == "huggingface": return state.get("hf_images_used", 0) >= self.hf_image_limit
        return False

    def diagnose_fatal_error(self, module_name, exception_obj):
        tb = "".join(traceback.format_exception(type(exception_obj), exception_obj, exception_obj.__traceback__))
        error_msg = f"\n🚨 [AI DOCTOR] Crash in {module_name}:\n{tb}\n"
        print(error_msg)
        
        log_path = os.path.join(self.memory_dir, "error_log.txt")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.utcnow().isoformat()}] {error_msg}\n{'-'*50}\n")
        except: pass
        
        from scripts.discord_notifier import notify_error
        notify_error(module_name, type(exception_obj).__name__, str(exception_obj))

    def generate_text(self, prompt, task_type="creative", force_provider=None):
        state = self._get_active_state()
        usage = state.get("gemini_used", 0)
        
        if force_provider == "groq" or task_type == "comment_reply_groq":
            return groq_client.generate_text(prompt, role="commenter"), "Groq Llama 3.3"

        if self.gemini_blocked_for_run and force_provider != "gemini":
            return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3 (Fallback)"

        if usage < self.gemini_text_limit:
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_key)
                for model_name in self.TEXT_MODELS:
                    try:
                        response = client.models.generate_content(model=model_name, contents=prompt)
                        self.consume_points("gemini", 1)
                        time.sleep(4)
                        return response.text, model_name
                    except Exception as e:
                        if "429" in str(e) or "quota" in str(e).lower():
                            self.gemini_blocked_for_run = True
                            break 
            except: pass
            
        print("⚡ [ROUTER] Executing Fallback Protocol (Groq)...")
        return groq_client.generate_text(prompt, role=task_type), "Groq Llama 3.3 (Fallback)"

quota_manager = MasterQuotaManager()
