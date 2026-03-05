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
    Hardened for 2026 API Stability.
    
    Manages:
    1. YouTube 10,000 Point Quota State Machine (With 403 Hard Catch).
    2. Gemini 50/50 Daily Split.
    3. Token Birthday Protocol (5-Month Alarm + Baby Steps instructions).
    4. Production Deficit Logic (Capped at 4 videos per run).
    5. The AI Doctor (Self-healing diagnostic engine).
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
        """Initializes the persistent state file if missing."""
        os.makedirs(self.memory_dir, exist_ok=True)
        if not os.path.exists(self.state_file):
            self._reset_daily_state()

    def _reset_daily_state(self):
        """Resets daily counters while preserving Token metadata."""
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
        """Safely reads the JSON state."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _write_state_file(self, data):
        """Safely writes the JSON state."""
        with open(self.state_file, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    # ==========================================
    # 🎂 THE TOKEN BIRTHDAY PROTOCOL
    # ==========================================
    def _sync_token_birthday(self):
        """Detects if the YouTube Token has changed and resets the 5-month timer."""
        current_token_fragment = self.youtube_token[:15]
        new_hash = hashlib.md5(current_token_fragment.encode()).hexdigest()
        
        state = self._read_state_file()
        if state.get("token_hash") != new_hash:
            print("🆕 [QUOTA] New Token detected. Initializing Birthday timer.")
            state["token_hash"] = new_hash
            state["token_birthday"] = datetime.utcnow().strftime("%Y-%m-%d")
            self._write_state_file(state)

    def check_token_health(self):
        """Triggers warning and 'Baby Steps' if token is > 150 days old."""
        state = self._read_state_file()
        birthday_str = state.get("token_birthday", datetime.utcnow().strftime("%Y-%m-%d"))
        birthday = datetime.strptime(birthday_str, "%Y-%m-%d")
        age_days = (datetime.utcnow() - birthday).days
        
        if age_days >= 150:
            msg = f"⚠️ [ALARM] YouTube Refresh Token is {age_days} days old."
            baby_steps = (
                "🚨 **BABY STEPS TO REFRESH TOKEN:**\n"
                "1. Visit [Google Cloud Console](https://console.cloud.google.com/).\n"
                "2. Navigate to 'APIs & Services' > 'Credentials'.\n"
                "3. Ensure redirect URI is 'http://localhost:8080'.\n"
                "4. Run your local `auth_refresh.py` script.\n"
                "5. Update `YOUTUBE_REFRESH_TOKEN` in GitHub Secrets."
            )
            return False, msg, baby_steps
        return True, "Token Healthy", ""

    # ==========================================
    # 📊 QUOTA TRACKING (The Hard Catch)
    # ==========================================
    def _get_active_state(self):
        """Returns state with daily reset logic."""
        state = self._read_state_file()
        if state.get("last_reset_date") != datetime.utcnow().strftime("%Y-%m-%d"):
            self._reset_daily_state()
            return self._read_state_file()
        return state

    def consume_points(self, provider, amount):
        """Deducts points for YouTube or Gemini."""
        state = self._get_active_state()
        if provider == "youtube":
            state["youtube_points_used"] += amount
        elif provider == "gemini":
            state["gemini_used"] += amount
        self._write_state_file(state)

    def force_quota_exhaustion(self, provider):
        """
        HARD CATCH: If an API returns a 403 (Quota Exceeded), 
        this function locks the module for the rest of the day.
        """
        state = self._get_active_state()
        if provider == "youtube":
            print("🚨 [QUOTA] Hard Catch: YouTube 10k Limit hit. Locking module.")
            state["youtube_points_used"] = 10000
        elif provider == "gemini":
            print("🚨 [QUOTA] Hard Catch: Gemini Limit hit. Locking module.")
            state["gemini_used"] = 100
        self._write_state_file(state)

    def get_available_youtube_quota(self):
        state = self._get_active_state()
        return 10000 - state.get("youtube_points_used", 0)

    # ==========================================
    # 📦 THE BATCH-CAPPED PRODUCTION LOGIC
    # ==========================================
    def get_production_deficit(self, current_vault_count):
        deficit = 14 - current_vault_count
        if deficit <= 0: return 0
        to_make = min(deficit, 4)
        print(f"📦 [BUFFER] Deficit: {deficit}. Production Batch: {to_make}")
        return to_make

    # ==========================================
    # 🏥 THE AI DOCTOR
    # ==========================================
    def diagnose_fatal_error(self, module_name, exception_obj):
        tb = "".join(traceback.format_exception(type(exception_obj), exception_obj, exception_obj.__traceback__))
        print(f"\n🚨 [AI DOCTOR] Analyzing failure in {module_name}...")
        
        # Detect Quota Limits from the Exception Message
        error_msg = str(exception_obj).lower()
        if "quotaexceeded" in error_msg or "403" in error_msg:
            self.force_quota_exhaustion("youtube")
            diagnosis = "YouTube Data API daily quota (10,000 pts) has been exhausted."
        elif "429" in error_msg or "resource_exhausted" in error_msg:
            self.force_quota_exhaustion("gemini")
            diagnosis = "Gemini API quota has been exhausted."
        else:
            prompt = f"Diagnose this crash: Module: {module_name}\nTraceback: {tb[-1000:]}"
            diagnosis = groq_client.generate_text(prompt, role="analyst") or "Unknown system failure."

        if self.discord_webhook:
            payload = {
                "content": "🔴 **<@everyone> ENGINE CRITICAL ALERT**",
                "embeds": [{
                    "title": f"🚨 Crash in {module_name}",
                    "color": 15158332,
                    "fields": [
                        {"name": "🤖 AI Diagnosis", "value": f"└ {diagnosis}", "inline": False},
                        {"name": "📜 Traceback (Tail)", "value": f"
http://googleusercontent.com/immersive_entry_chip/0

### 🚢 Final Re-Simulation Result:
* **Case:** You test the uploader 10 times in a row.
* **Result:** On the 7th test, the YouTube API returns `403 quotaExceeded`.
* **Engine Action:** The `AI Doctor` detects the 403, calls `force_quota_exhaustion("youtube")`, which sets `youtube_points_used` to 10,000.
* **Discord Alert:** You get a red notification: *"AI Diagnosis: YouTube Data API daily quota (10,000 pts) has been exhausted."*
* **Subsequent Runs:** If a workflow triggers an hour later, `main.py` checks the quota, sees 0 remaining, and shuts down immediately without calling any other APIs. 

**This is the ultimate armor.** What is our next move? Are we ready to trigger the first manual workflow test on GitHub?
