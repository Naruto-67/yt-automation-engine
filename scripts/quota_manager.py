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
    Manages:
    1. YouTube 10,000 Point Quota State Machine.
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
        """
        Detects if the YouTube Token has changed using MD5 hashing.
        If a new token is found, it resets the 5-month timer.
        """
        # We only hash the first 15 characters to detect the specific token instance
        current_token_fragment = self.youtube_token[:15]
        new_hash = hashlib.md5(current_token_fragment.encode()).hexdigest()
        
        state = self._read_state_file()

        if state.get("token_hash") != new_hash:
            print("🆕 [QUOTA] New Token detected. Initializing 5-Month Birthday timer.")
            state["token_hash"] = new_hash
            state["token_birthday"] = datetime.utcnow().strftime("%Y-%m-%d")
            self._write_state_file(state)

    def check_token_health(self):
        """
        Evaluates token age. Triggers warning and 'Baby Steps' if > 150 days.
        Returns: (is_healthy, warning_message, baby_steps_guide)
        """
        state = self._read_state_file()
        birthday_str = state.get("token_birthday", datetime.utcnow().strftime("%Y-%m-%d"))
        birthday = datetime.strptime(birthday_str, "%Y-%m-%d")
        age_days = (datetime.utcnow() - birthday).days
        
        if age_days >= 150:
            msg = f"⚠️ [ALARM] YouTube Refresh Token is {age_days} days old. Expiring in approx {180-age_days} days."
            baby_steps = (
                "🚨 **BABY STEPS TO REFRESH TOKEN:**\n"
                "1. Visit [Google Cloud Console](https://console.cloud.google.com/).\n"
                "2. Navigate to 'APIs & Services' > 'Credentials'.\n"
                "3. Ensure your OAuth 2.0 Client ID is active.\n"
                "4. Run your local `auth_refresh.py` script to get a fresh string.\n"
                "5. Update the `YOUTUBE_REFRESH_TOKEN` in GitHub Repo Secrets.\n"
                "6. The engine will detect the update and silence this alarm."
            )
            return False, msg, baby_steps
        return True, "Token Healthy", ""

    # ==========================================
    # 📊 QUOTA TRACKING (YT 10k & Gemini 50)
    # ==========================================
    def _get_active_state(self):
        """Returns the state, ensuring it is reset for the current day."""
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

    def get_available_youtube_quota(self):
        """Returns the remaining points for today's YouTube API usage."""
        state = self._get_active_state()
        return 10000 - state.get("youtube_points_used", 0)

    # ==========================================
    # 📦 THE BATCH-CAPPED PRODUCTION LOGIC
    # ==========================================
    def get_production_deficit(self, current_vault_count):
        """
        Determines the number of videos needed to reach the 14-video buffer.
        Capped at 4 per run to prevent GitHub Runner RAM/Timeout crashes.
        """
        target_buffer = 14
        deficit = target_buffer - current_vault_count
        
        if deficit <= 0:
            return 0
        
        # Loophole 1 Fix: Batch Cap at 4 videos
        to_make = min(deficit, 4)
        print(f"📦 [BUFFER] Vault: {current_vault_count}/{target_buffer}. Deficit: {deficit}. Production Batch: {to_make}")
        return to_make

    # ==========================================
    # 🏥 THE AI DOCTOR (Diagnosis & Discord)
    # ==========================================
    def diagnose_fatal_error(self, module_name, exception_obj):
        """
        Intercepts crashes, performs a Groq analyst diagnosis, 
        and pings Discord Mission Control.
        """
        tb = "".join(traceback.format_exception(type(exception_obj), exception_obj, exception_obj.__traceback__))
        print(f"\n🚨 [AI DOCTOR] Analyzing failure in {module_name}...")
        
        # Local Error Logging
        log_path = os.path.join(self.memory_dir, "error_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.utcnow().isoformat()}] CRASH IN {module_name}:\n{tb}\n")
        
        # AI Diagnosis (Using Groq Failover Queue)
        prompt = f"System Architect: Diagnose this crash and provide a 1-sentence fix.\n\nModule: {module_name}\nTraceback: {tb[-1200:]}"
        diagnosis = groq_client.generate_text(prompt, role="analyst") or "Total system paralysis. Check logs."

        if self.discord_webhook:
            # Using raw string for backticks to ensure discord formatting
            code_block = "```"
            payload = {
                "content": "🔴 **<@everyone> MANUAL INTERVENTION REQUIRED**",
                "embeds": [{
                    "title": f"🚨 ENGINE CRASH: {module_name}",
                    "color": 15158332,
                    "fields": [
                        {"name": "🤖 AI Diagnosis & Fix", "value": f"└ {diagnosis}", "inline": False},
                        {"name": "📜 Traceback (Tail)", "value": f"{code_block}python\n{tb[-600:]}\n{code_block}", "inline": False}
                    ],
                    "footer": {"text": "AI Doctor Protocol Executed"}
                }]
            }
            try:
                requests.post(self.discord_webhook, json=payload, timeout=10)
            except:
                print("❌ [AI DOCTOR] Failed to reach Discord Webhook.")
        
        return diagnosis

    # ==========================================
    # 🧠 THE MASTER ROUTER (Smart Routing)
    # ==========================================
    def generate_text(self, prompt, task_type="creative"):
        """
        Standardizes all text generation across the engine.
        Routes to Gemini for research (Google Search) and Groq for everything else.
        """
        # 1. LIVE RESEARCH: Requires Gemini + Google Search Grounding
        if task_type == "research":
            return self._safe_gemini_call(prompt, use_search=True)
            
        # 2. STANDARD CREATIVE/ANALYST: Groq Llama 3.3 (Primary)
        res = groq_client.generate_text(prompt, role=task_type)
        if res:
            return res
            
        # 3. FALLBACK: Gemini if Groq is offline or throttled
        print("🔄 [ROUTER] Groq failed. Cascading to Gemini fallback.")
        return self._safe_gemini_call(prompt)

    def _safe_gemini_call(self, prompt, use_search=False):
        """Protected Gemini call that respects the 50/50 daily point split."""
        from google import genai
        
        state = self._read_state_file()
        if state.get("gemini_used", 0) >= 50 and not use_search:
            print("🛡️ [GEMINI] 50-point reserve active. Aborting to save search quota.")
            return None
            
        try:
            client = genai.Client(api_key=self.gemini_key)
            config = {'tools': [{'google_search': {}}]} if use_search else {}
            
            # Using the stable 2.0-flash model for 2026 consistency
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=config
            )
            self.consume_points("gemini", 1)
            return response.text
        except Exception as e:
            if "429" in str(e).lower():
                print("💥 [GEMINI] 429 Quota Exhausted. Locking Gemini for today.")
                self.consume_points("gemini", 100)
            return None

# Singleton instance for engine-wide import
quota_manager = MasterQuotaManager()
