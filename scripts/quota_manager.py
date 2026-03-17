# scripts/quota_manager.py
# Ghost Engine V26.0.0 — Unified Quota Control & Multi-Provider Tracking
import os
import json
import traceback
import pytz
from datetime import datetime, timezone
from engine.database import db
from engine.config_manager import config_manager
from engine.context import ctx

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
_FILE_NAME = "quota_state_test.json" if TEST_MODE else "quota_state.json"
_QUOTA_JSON_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "memory", _FILE_NAME)

class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        settings = config_manager.get_settings()
        # V26: Updated limits reflecting 2026 free-tier standards [cite: 50]
        self.LIMITS = settings.get("api_limits", {
            "gemini": 38, "cloudflare": 90, "huggingface": 45, "youtube": 9200
        })

    def _today_utc(self) -> str: 
        return datetime.now(timezone.utc).strftime("%Y-%m-%d") [cite: 404]
 
    def _today_pt(self) -> str: 
        """PT is used for YouTube Data API resets."""
        return datetime.now(pytz.timezone('America/Los_Angeles')).strftime("%Y-%m-%d") [cite: 405]

    def _get_channel_id(self) -> str: 
        return ctx.get_channel_id()

    def _get_active_state(self) -> dict:
        """Retrieves and merges global and channel-specific quota usage. [cite: 406-407]"""
        today_utc, today_pt, ch_id = self._today_utc(), self._today_pt(), self._get_channel_id()
        
        ch_state = db.get_quota_state(today_pt, ch_id)
        if not ch_state:
            db.init_quota_state(today_pt, ch_id, today_pt)
            ch_state = db.get_quota_state(today_pt, ch_id) or {}
            
        gl_state = db.get_quota_state(today_utc, "GLOBAL")
        if not gl_state:
            db.init_quota_state(today_utc, "GLOBAL", today_utc)
            gl_state = db.get_quota_state(today_utc, "GLOBAL") or {}
            
        return {
            "date": today_utc, 
            "channel_id": ch_id,
            "youtube_points": ch_state.get("youtube_points", 0), 
            "gemini_calls": gl_state.get("gemini_calls", 0),
            "cf_images": gl_state.get("cf_images", 0), 
            "hf_images": gl_state.get("hf_images", 0)
        }

    def consume_points(self, provider: str, amount: int):
        """Standardized point consumption for all V26 providers. [cite: 408-409]"""
        if TEST_MODE and provider == "youtube": return 
        
        if provider == "youtube":
            target_id, col, today, yt_update = self._get_channel_id(), "youtube_points", self._today_pt(), self._today_pt()
        else:
            target_id, today, yt_update = "GLOBAL", self._today_utc(), None
            col_map = {"gemini": "gemini_calls", "cloudflare": "cf_images", "huggingface": "hf_images"}
            col = col_map.get(provider)
        
        if col:
            if not db.get_quota_state(today, target_id): 
                db.init_quota_state(today, target_id, today)
            db.update_quota(today, target_id, col, amount, yt_update)
            
            # Sync to physical JSON file for external monitoring tools
            try:
                state = self._get_active_state()
                os.makedirs(os.path.dirname(_QUOTA_JSON_PATH), exist_ok=True)
                with open(_QUOTA_JSON_PATH, "w") as f: 
                    json.dump(state, f, indent=2)
            except Exception: 
                pass

    def can_afford_youtube(self, cost: int) -> bool:
        """Safety check before executing heavy YouTube API tasks."""
        if TEST_MODE: return True
        return (self._get_active_state().get("youtube_points", 0) + cost) <= self.LIMITS["youtube"]

    def is_provider_exhausted(self, provider: str) -> bool:
        """Determines if a provider has reached its daily ceiling. [cite: 410]"""
        state = self._get_active_state()
        col_limit_map = {
            "cloudflare": ("cf_images", "cloudflare"), 
            "huggingface": ("hf_images", "huggingface"), 
            "gemini": ("gemini_calls", "gemini")
        }
        if provider not in col_limit_map: return False
        col, key = col_limit_map[provider]
        return state.get(col, 0) >= self.LIMITS.get(key, 9999)

    def generate_text(self, prompt: str, task_type: str = "creative", system_prompt: str = None) -> tuple:
        """
        V26 Interface: Routes text generation to the LLMRouter while tracking quota. 
        [cite: 411-413]
        """
        gemini_quota_ok = not self.is_provider_exhausted("gemini")
        
        from engine.llm_router import llm_router
        generated_text, provider_log_name, provider_key = llm_router.execute_generation(
            prompt=prompt, 
            system_prompt=system_prompt, 
            gemini_quota_ok=gemini_quota_ok,
            task_type=task_type,
        )
        
        if provider_key and provider_key != "none":
            self.consume_points(provider_key, 1)
            
        return generated_text, provider_log_name

    def diagnose_fatal_error(self, module: str, exception: Exception):
        """V26 Incident Logger: Captures stack traces and notifies Discord. [cite: 414-415]"""
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp, trace = datetime.now().isoformat(), traceback.format_exc()
        try:
            # Atomic log pruning to prevent disk fill 
            if os.path.exists(error_log) and os.path.getsize(error_log) > 1_000_000:
                with open(error_log, "r") as f: lines = f.readlines()
                with open(error_log, "w") as f: f.writelines(lines[len(lines)//2:])
            with open(error_log, "a") as f: 
                f.write(f"\n[{timestamp}] [{module}] {type(exception).__name__}: {exception}\n{trace}\n{'─'*40}")
        except: 
            pass
        try:
            from scripts.discord_notifier import notify_error
            notify_error(module, type(exception).__name__, str(exception))
        except: 
            pass

quota_manager = MasterQuotaManager()
