import os
import json
import time
import requests
import traceback
from datetime import datetime
from google import genai
from google.genai import errors

# Import our newly built Groq API Client
from scripts.groq_client import groq_client

class MasterQuotaManager:
    """
    The 2026 Central Nervous System (Upgraded from the old retry.py).
    Manages the Gemini 50/50 Split, routes tasks to Groq, and houses the AI Doctor.
    """
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.memory_dir = os.path.join(self.root_dir, "memory")
        self.stats_file = os.path.join(self.memory_dir, "quota_tracker.json")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        
        self._ensure_setup()

    def _ensure_setup(self):
        """Creates memory directory and quota tracker file."""
        os.makedirs(self.memory_dir, exist_ok=True)
        if not os.path.exists(self.stats_file):
            self._reset_daily_stats()

    def _reset_daily_stats(self):
        """Resets the Gemini tracker for a new UTC day."""
        with open(self.stats_file, 'w') as f:
            json.dump({
                "date": datetime.utcnow().strftime("%Y-%m-%d"), 
                "gemini_used": 0
            }, f, indent=4)

    def _get_gemini_usage(self):
        """Reads current Gemini usage."""
        with open(self.stats_file, 'r') as f:
            data = json.load(f)
            if data.get("date") != datetime.utcnow().strftime("%Y-%m-%d"):
                self._reset_daily_stats()
                return 0
            return data.get("gemini_used", 0)

    def _increment_gemini_usage(self):
        """Adds 1 to the Gemini tracker."""
        current = self._get_gemini_usage()
        with open(self.stats_file, 'w') as f:
            json.dump({
                "date": datetime.utcnow().strftime("%Y-%m-%d"), 
                "gemini_used": current + 1
            }, f, indent=4)

    # ==========================================
    # 🏥 THE AI DOCTOR (Self-Diagnosing Protocol)
    # ==========================================
    def diagnose_fatal_error(self, module_name, exception_obj):
        """
        Catches a crash, asks Groq to translate the traceback, and pings Discord.
        """
        raw_traceback = "".join(traceback.format_exception(type(exception_obj), exception_obj, exception_obj.__traceback__))
        print(f"\n🚨 [AI DOCTOR] Critical Crash in {module_name}. Analyzing traceback...")
        
        # Log locally for permanent record
        with open(os.path.join(self.memory_dir, "error_log.txt"), "a") as f:
            f.write(f"\n--- CRASH: {module_name} AT {datetime.utcnow().isoformat()} ---\n{raw_traceback}\n")
        
        # Ask Groq to diagnose it (Bypasses Gemini quota)
        prompt = f"""
        You are a Senior Python Developer. My YouTube automation script just crashed.
        Module: {module_name}
        Error Traceback:
        {raw_traceback[-1500:]} 
        
        Provide:
        1. A 1-sentence explanation of what broke.
        2. A 1-sentence instruction on how to fix it.
        """
        
        diagnosis = groq_client.generate_text(prompt, role="creative", system_prompt="You are a Senior Systems Architect.")
        if not diagnosis:
            diagnosis = "The AI Doctor also failed to process the error. Manual check required."

        # Send High-Priority Discord Ping
        if self.discord_webhook:
            # Using a variable for backticks so standard markdown block parsing isn't broken
            code_mark = "```"
            embed = {
                "content": "🔴 **<@everyone> MANUAL ATTENTION NEEDED**",
                "embeds": [{
                    "title": f"🚨 CRITICAL CRASH: {module_name}",
                    "color": 16711680,
                    "fields": [
                        {"name": "🤖 AI Diagnosis & Fix", "value": f"└ {diagnosis}", "inline": False},
                        {"name": "📜 Raw Traceback (Tail)", "value": f"{code_mark}python\n{raw_traceback[-800:]}\n{code_mark}", "inline": False}
                    ],
                    "footer": {"text": "AI Doctor Protocol Executed"}
                }]
            }
            try:
                requests.post(self.discord_webhook, json=embed, timeout=10)
            except:
                print("❌ [AI DOCTOR] Failed to reach Discord Webhook.")
                
        return diagnosis

    # ==========================================
    # 🧠 THE SMART ROUTER (Best vs Fallback)
    # ==========================================
    def generate_text(self, prompt, task_type="creative"):
        """
        The new standard for text generation. Automatically routes tasks.
        task_type: "creative" (Scripts/Comments), "research" (Web Search), "analysis" (Data Pivot)
        """
        # 1. RESEARCH -> Needs Gemini for Google Search Grounding
        if task_type == "research":
            gemini_result = self._safe_gemini_call(prompt, use_search=True)
            if gemini_result: return gemini_result
            print("🔄 [ROUTER] Gemini Research failed. Falling back to Groq Creative...")
            return groq_client.generate_text(prompt, role="creative")
            
        # 2. ANALYSIS -> Needs Groq 120B for deep statistical logic
        elif task_type == "analysis":
            groq_120b = groq_client.generate_text(prompt, role="analyst")
            if groq_120b: return groq_120b
            print("🔄 [ROUTER] Groq Analyst failed. Falling back to Gemini...")
            return self._safe_gemini_call(prompt, use_search=False, override_quota=True)
            
        # 3. CREATIVE -> Needs Groq Llama 3.3 for high volume & human tone
        else: 
            groq_creative = groq_client.generate_text(prompt, role="creative")
            if groq_creative: return groq_creative
            print("🔄 [ROUTER] Groq Creative failed. Falling back to Gemini...")
            return self._safe_gemini_call(prompt, use_search=False)

    # ==========================================
    # 🛡️ INTERNAL GEMINI WRAPPER (The 3x45s Matrix)
    # ==========================================
    def _safe_gemini_call(self, prompt, use_search=False, override_quota=False):
        """Internal handler to protect the Gemini 50/50 split and execute retries."""
        if not self.gemini_key: return None
        
        usage = self._get_gemini_usage()
        if usage >= 50 and not override_quota:
            print(f"🛡️ [GEMINI] 50-Point Reserve Active ({usage}/100). Preserving quota.")
            return None
            
        print(f"🧠 [GEMINI] Processing... (Points used: {usage + 1})")
        
        client = genai.Client(api_key=self.gemini_key)
        config = {'tools': [{'google_search': {}}]} if use_search else {}
        max_strikes = 3

        for strike in range(1, max_strikes + 1):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash-preview-09-2025',
                    contents=prompt,
                    config=config
                )
                self._increment_gemini_usage()
                return response.text
                
            except errors.APIError as e:
                error_str = str(e).lower()
                if "429" in error_str or "exhausted" in error_str:
                    print("💥 [GEMINI] 429 Quota Exhausted! Locking Gemini until midnight.")
                    with open(self.stats_file, 'w') as f:
                        json.dump({"date": datetime.utcnow().strftime("%Y-%m-%d"), "gemini_used": 100}, f)
                    return None 
                    
                print(f"⚠️ [GEMINI] STRIKE {strike} API Error: {e}")
                if strike < max_strikes:
                    time.sleep(5 * strike)
                continue
                
            except Exception as e:
                print(f"❌ [GEMINI] STRIKE {strike} System Error: {e}")
                if strike < max_strikes:
                    time.sleep(5 * strike)
                continue

        print("🚨 [GEMINI] FATAL: Failed after 3 attempts.")
        return None

    # ==========================================
    # 🕰️ LEGACY WRAPPER (Backward Compatibility)
    # ==========================================
    def safe_execute(self, func, *args, **kwargs):
        """
        Keeps your existing scripts running perfectly while we slowly 
        upgrade them to use the new `generate_text` smart router.
        """
        max_strikes = 3
        for strike in range(1, max_strikes + 1):
            try:
                return func(*args, **kwargs)
            except errors.APIError as e:
                if "429" in str(e).lower() or "exhausted" in str(e).lower():
                    print(f"🛑 [LEGACY WRAPPER] 429 Hit. Pausing for 60s...")
                    time.sleep(60)
                    continue
                print(f"⚠️ [LEGACY WRAPPER] STRIKE {strike} Error: {e}")
                time.sleep(5 * strike)
            except Exception as e:
                print(f"❌ [LEGACY WRAPPER] STRIKE {strike} Error: {e}")
                time.sleep(5 * strike)
                
        return None

# Keep the instance name exactly the same so old files don't break!
quota_manager = MasterQuotaManager()
