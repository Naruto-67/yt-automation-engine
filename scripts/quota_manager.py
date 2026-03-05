import os
import json
import time
import requests
import traceback
import hashlib
from datetime import datetime, timedelta

# Import the upgraded Groq Client from Step 1
from scripts.groq_client import groq_client

class MasterQuotaManager:
    """
    Ghost Engine V4.0 - The Central Brain (Quota & State Manager).
    Hardened for 2026 API Stability and Long-Term Autonomous Operation.
    
    Manages:
    1. YouTube 10,000 Point Quota State Machine (With 403 "Hard Catch" logic).
    2. Gemini 50/50 Daily Split (Preserving quota for research/search).
    3. Token Birthday Protocol (5-Month Alarm + Baby Steps reset guide).
    4. Production Deficit Logic (Deficit-based Batch Cap @ 4 videos).
    5. The AI Doctor (Self-healing diagnostic engine with quota detection).
    """
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.memory_dir = os.path.join(self.root_dir, "memory")
        self.state_file = os.path.join(self.memory_dir, "api_state.json")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.youtube_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
        self.discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        
        self._ensure_state_exists()
        self._sync_token_birthday()

    def _ensure_state_exists(self):
        """Initializes the persistent state file if missing or corrupted."""
        os.makedirs(self.memory_dir, exist_ok=True)
        if not os.path.exists(self.state_file):
            self._reset_daily_state()

    def _reset_daily_state(self):
        """Resets daily counters while preserving Token metadata and Birthday."""
        current_data = self._read_state_file()
        new_state = {
            "last_reset_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "gemini_used": 0,
            "youtube_points_used": 0,
            "token_birthday": current_data.get("token_birthday", datetime.utcnow().strftime("%Y-%m-%d")),
            "token_hash": current_data.get("token_hash", "")
        }
        self._write_state_file(new_state)

    def _read_state_file(self):
        """Safely reads the JSON state from the memory vault."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _write_state_file(self, data):
        """Safely writes the JSON state to the memory vault."""
        with open(self.state_file, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    # ==========================================
    # 🎂 THE TOKEN BIRTHDAY PROTOCOL
    # ==========================================
    def _sync_token_birthday(self):
        """
        Detects if the YouTube Token has been updated by hashing the first 15 chars.
        If a change is detected, it automatically resets the 150-day alarm.
        """
        if not self.youtube_token:
            return
            
        current_token_fragment = self.youtube_token[:15]
        new_hash = hashlib.md5(current_token_fragment.encode()).hexdigest()
        
        state = self._read_state_file()
        if state.get("token_hash") != new_hash:
            print("🆕 [QUOTA] New YouTube Token detected. Resetting 5-Month Birthday timer.")
            state["token_hash"] = new_hash
            state["token_birthday"] = datetime.utcnow().strftime("%Y-%m-%d")
            self._write_state_file(state)

    def check_token_health(self):
        """
        Evaluates token age. If > 150 days, triggers the warning + Baby Steps.
        Returns: (is_healthy, warning_message, baby_steps_guide)
        """
        state = self._read_state_file()
        birthday_str = state.get("token_birthday", datetime.utcnow().strftime("%Y-%m-%d"))
        birthday = datetime.strptime(birthday_str, "%Y-%m-%d")
        age_days = (datetime.utcnow() - birthday).days
        
        if age_days >= 150:
            msg = f"⚠️ [ALARM] YouTube Refresh Token is {age_days} days old. Expiring soon."
            baby_steps = (
                "🚨 **BABY STEPS TO REFRESH TOKEN:**\n"
                "1. Open [Google Cloud Console](https://console.cloud.google.com/).\n"
                "2. Navigate to 'APIs & Services' > 'Credentials'.\n"
                "3. Ensure redirect URI is set to 'http://localhost:8080'.\n"
                "4. Run your local `auth_refresh.py` script to get a new string.\n"
                "5. Update the `YOUTUBE_REFRESH_TOKEN` in GitHub Repo Secrets.\n"
                "6. The engine will detect the new hash and silence this alarm."
            )
            return False, msg, baby_steps
        return True, "Token Healthy", ""

    # ==========================================
    # 📊 QUOTA TRACKING (The Hard Catch)
    # ==========================================
    def _get_active_state(self):
        """Returns the current state, enforcing a daily reset if the date has changed."""
        state = self._read_state_file()
        if state.get("last_reset_date") != datetime.utcnow().strftime("%Y-%m-%d"):
            self._reset_daily_state()
            return self._read_state_file()
        return state

    def consume_points(self, provider, amount):
        """Deducts points for YouTube (10k limit) or Gemini (50 split)."""
        state = self._get_active_state()
        if provider == "youtube":
            state["youtube_points_used"] += amount
        elif provider == "gemini":
            state["gemini_used"] += amount
        self._write_state_file(state)

    def force_quota_exhaustion(self, provider):
        """
        THE HARD CATCH: If an API returns a 403 or 429, this function 
        instantly locks the module to prevent further failed attempts.
        """
        state = self._get_active_state()
        if provider == "youtube":
            print("🚨 [QUOTA] Hard Catch Triggered: YouTube Quota exhausted. Locking module.")
            state["youtube_points_used"] = 10000
        elif provider == "gemini":
            print("🚨 [QUOTA] Hard Catch Triggered: Gemini Quota exhausted. Locking module.")
            state["gemini_used"] = 100
        self._write_state_file(state)

    def get_available_youtube_quota(self):
        """Returns remaining points out of the 10,000 daily points."""
        state = self._get_active_state()
        return 10000 - state.get("youtube_points_used", 0)

    # ==========================================
    # 📦 THE BATCH-CAPPED PRODUCTION LOGIC
    # ==========================================
    def get_production_deficit(self, current_vault_count):
        """
        Calculates how many videos to make to reach the 14-video buffer.
        Strictly capped at 4 videos to prevent GitHub Runner timeouts.
        """
        target = 14
        deficit = target - current_vault_count
        if deficit <= 0:
            return 0
        
        # Loophole 1 Fix: Batch Cap at 4
        actual_to_make = min(deficit, 4)
        print(f"📦 [BUFFER] Vault: {current_vault_count}/{target}. Production deficit: {deficit}. Batch Size: {actual_to_make}")
        return actual_to_make

    # ==========================================
    # 🏥 THE AI DOCTOR
    # ==========================================
    def diagnose_fatal_error(self, module_name, exception_obj):
        """
        Catches crashes, identifies quota triggers, asks Groq for a fix, 
        and pings Discord Mission Control.
        """
        tb = "".join(traceback.format_exception(type(exception_obj), exception_obj, exception_obj.__traceback__))
        print(f"\n🚨 [AI DOCTOR] Analyzing failure in {module_name}...")
        
        # Log to permanent history
        log_path = os.path.join(self.memory_dir, "error_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.utcnow().isoformat()}] CRASH IN {module_name}:\n{tb}\n")

        # Quota Logic Check
        error_msg = str(exception_obj).lower()
        if "quotaexceeded" in error_msg or "403" in error_msg:
            self.force_quota_exhaustion("youtube")
            diagnosis = "The YouTube Data API quota (10,000 points) has been fully exhausted for today."
        elif "429" in error_msg or "resource_exhausted" in error_msg:
            self.force_quota_exhaustion("gemini")
            diagnosis = "The Gemini API quota has been exhausted. System switching to free fallbacks."
        else:
            # General AI Diagnosis using Groq
            prompt = f"Senior Systems Architect: Diagnose this crash and provide a 1-sentence fix.\n\nModule: {module_name}\nTraceback: {tb[-1200:]}"
            diagnosis = groq_client.generate_text(prompt, role="analyst") or "System paralyzed. Manual check required."

        if self.discord_webhook:
            code_block = "```"
            payload = {
                "content": "🔴 **<@everyone> ENGINE CRITICAL ERROR ALERT**",
                "embeds": [{
                    "title": f"🚨 Crash detected in {module_name}",
                    "color": 15158332,
                    "fields": [
                        {"name": "🤖 AI Diagnosis", "value": f"└ {diagnosis}", "inline": False},
                        {"name": "📜 Traceback (Tail)", "value": f"{code_block}python\n{tb[-600:]}\n{code_block}", "inline": False}
                    ],
                    "footer": {"text": "AI Doctor Protocol V4.0"}
                }]
            }
            try:
                requests.post(self.discord_webhook, json=payload, timeout=10)
            except:
                print("❌ [AI DOCTOR] Discord Webhook unreachable.")
        
        return diagnosis

    # ==========================================
    # 🧠 THE MASTER ROUTER
    # ==========================================
    def generate_text(self, prompt, task_type="creative"):
        """
        The Nervous System Router. Standardizes all text generation.
        Research -> Gemini (Google Search Grounded).
        Creative/Analyst -> Groq (Llama 3.3 Primary).
        """
        if task_type == "research":
            return self._safe_gemini_call(prompt, use_search=True)
            
        # Try Groq first for everything else (Free & Fast)
        res = groq_client.generate_text(prompt, role=task_type)
        if res:
            return res
            
        # Failover to Gemini if Groq is throttled
        print("🔄 [ROUTER] Groq failed or offline. Cascading to Gemini fallback.")
        return self._safe_gemini_call(prompt)

    def _safe_gemini_call(self, prompt, use_search=False):
        """Internal Gemini handler with 50/50 split protection."""
        from google import genai
        
        state = self._read_state_file()
        # Preserve 50 points for search/research tasks
        if state.get("gemini_used", 0) >= 50 and not use_search:
            print("🛡️ [GEMINI] 50-Point Reserve active. Preserving quota for research.")
            return None
            
        try:
            client = genai.Client(api_key=self.gemini_key)
            config = {'tools': [{'google_search': {}}]} if use_search else {}
            
            # Using the stable 2.0-flash release for 2026 consistency
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=config
            )
            self.consume_points("gemini", 1)
            return response.text
        except Exception as e:
            if "429" in str(e).lower():
                self.force_quota_exhaustion("gemini")
            return None

# Singleton instance for engine-wide synchronization
quota_manager = MasterQuotaManager()
