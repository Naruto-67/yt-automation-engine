import os
import json
import traceback
from datetime import datetime, timezone, timedelta

def _get_pt_timezone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('America/Los_Angeles')
    except Exception:
        try:
            import pytz
            return pytz.timezone('America/Los_Angeles')
        except Exception:
            return timezone(timedelta(hours=-7))
from engine.database import db
from engine.config_manager import config_manager
from engine.context import ctx

def is_test_mode() -> bool:
    return os.environ.get("TEST_MODE", "false").lower() == "true"

TEST_MODE = is_test_mode()
_FILE_NAME = "quota_state_test.json" if is_test_mode() else "quota_state.json"
_QUOTA_JSON_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "memory", _FILE_NAME)


class CostTracker:
    """
    P2.8: Cost & Token Spend Optimizer.
    Tracks estimated token spend per video and daily total across all LLM operations.
    Formula: tokens ≈ (prompt_words + output_words) * 1.33.
    Features:
    - Logs daily token totals to memory/cost_log.json.
    - Alerts Discord if per-video tokens exceed max_cost_per_video_tokens.
    - Flags is_budget_strained() if daily token spend exceeds 80% of daily_token_budget.
    """
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.log_file = os.path.join(self.root_dir, "memory", "cost_log.json")
        self._current_video_tokens = 0

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _read_log(self) -> dict:
        if not os.path.exists(self.log_file):
            return {"date": self._today(), "daily_tokens": 0, "entries": []}
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("date") != self._today():
                    return {"date": self._today(), "daily_tokens": 0, "entries": []}
                return data
        except Exception:
            return {"date": self._today(), "daily_tokens": 0, "entries": []}

    def _write_log(self, data: dict):
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def reset_video_tracking(self):
        self._current_video_tokens = 0

    def record_generation(self, prompt: str, output: str, task_type: str = "creative", model_name: str = "") -> int:
        p_words = len((prompt or "").split())
        o_words = len((output or "").split())
        est_tokens = int((p_words + o_words) * 1.33)
        self._current_video_tokens += est_tokens

        data = self._read_log()
        data["daily_tokens"] = data.get("daily_tokens", 0) + est_tokens
        data["entries"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_type": task_type,
            "model": model_name,
            "tokens": est_tokens,
            "cumulative_daily": data["daily_tokens"]
        })
        if len(data["entries"]) > 50:
            data["entries"] = data["entries"][-50:]
        self._write_log(data)

        # Check per-video token threshold
        try:
            settings = config_manager.get_settings()
            cost_cfg = settings.get("cost_tracking", {})
            max_vid_tokens = cost_cfg.get("max_cost_per_video_tokens", 3500)
            if self._current_video_tokens > max_vid_tokens:
                from scripts.discord_notifier import notify_quota_warning
                notify_quota_warning(
                    provider=f"Token Limit ({model_name})",
                    usage=self._current_video_tokens,
                    limit=max_vid_tokens
                )
        except Exception:
            pass

        return est_tokens

    def is_budget_strained(self, threshold: float = 0.80) -> bool:
        try:
            settings = config_manager.get_settings()
            cost_cfg = settings.get("cost_tracking", {})
            daily_budget = cost_cfg.get("daily_token_budget", 150000)
            data = self._read_log()
            current_daily = data.get("daily_tokens", 0)
            return current_daily >= (daily_budget * threshold)
        except Exception:
            return False

    def get_video_token_spend(self) -> int:
        return self._current_video_tokens


class MasterQuotaManager:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        settings = config_manager.get_settings()
        self.LIMITS = settings.get("api_limits", {
            "gemini": 38, "cloudflare": 90, "huggingface": 45, "youtube": 9200
        })
        self.cost_tracker = CostTracker()

    def _today_utc(self) -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    def _today_pt(self) -> str: return datetime.now(_get_pt_timezone()).strftime("%Y-%m-%d")
    def _get_channel_id(self) -> str: return ctx.get_channel_id()

    def _get_active_state(self) -> dict:
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
            "date": today_utc, "channel_id": ch_id,
            "youtube_points": ch_state.get("youtube_points", 0), "gemini_calls": gl_state.get("gemini_calls", 0),
            "cf_images": gl_state.get("cf_images", 0), "hf_images": gl_state.get("hf_images", 0)
        }

    def consume_points(self, provider: str, amount: int):
        if TEST_MODE and provider == "youtube": return 
        if provider == "youtube":
            target_id, col, today, yt_update = self._get_channel_id(), "youtube_points", self._today_pt(), self._today_pt()
        else:
            target_id, today, yt_update = "GLOBAL", self._today_utc(), None
            col_map = {"gemini": "gemini_calls", "cloudflare": "cf_images", "huggingface": "hf_images"}
            col = col_map.get(provider)
        
        if col:
            if not db.get_quota_state(today, target_id): db.init_quota_state(today, target_id, today)
            db.update_quota(today, target_id, col, amount, yt_update)
            try:
                state = self._get_active_state()
                os.makedirs(os.path.dirname(_QUOTA_JSON_PATH), exist_ok=True)
                with open(_QUOTA_JSON_PATH, "w") as f: json.dump(state, f, indent=2)
            except Exception: pass

    def can_afford_youtube(self, cost: int) -> bool:
        if TEST_MODE: return True
        return (self._get_active_state().get("youtube_points", 0) + cost) <= self.LIMITS["youtube"]

    def is_provider_exhausted(self, provider: str) -> bool:
        state = self._get_active_state()
        col_limit_map = {"cloudflare": ("cf_images", "cloudflare"), "huggingface": ("hf_images", "huggingface"), "gemini": ("gemini_calls", "gemini")}
        if provider not in col_limit_map: return False
        col, key = col_limit_map[provider]
        return state.get(col, 0) >= self.LIMITS.get(key, 9999)

    def generate_text(self, prompt: str, task_type: str = "creative", system_prompt: str = None) -> tuple:
        """
        Delegates text generation to the dedicated LLMRouter while strictly maintaining quota tracking.
        This resolves the architectural God Object issue cleanly.
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

        # ── P2.8: Cost & Token Spend Tracking ─────────────────────────────────
        try:
            self.cost_tracker.record_generation(
                prompt=prompt,
                output=generated_text or "",
                task_type=task_type,
                model_name=provider_log_name
            )
        except Exception:
            pass

        return generated_text, provider_log_name

    def diagnose_fatal_error(self, module: str, exception: Exception):
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp, trace = datetime.now().isoformat(), traceback.format_exc()
        try:
            if os.path.exists(error_log) and os.path.getsize(error_log) > 1_000_000:
                with open(error_log, "r") as f: lines = f.readlines()
                with open(error_log, "w") as f: f.writelines(lines[len(lines)//2:])
            with open(error_log, "a") as f: f.write(f"\n[{timestamp}] [{module}] {type(exception).__name__}: {exception}\n{trace}\n{'─'*40}")
        except: pass
        try:
            from scripts.discord_notifier import notify_error
            notify_error(module, type(exception).__name__, str(exception))
        except: pass

quota_manager = MasterQuotaManager()
cost_tracker  = quota_manager.cost_tracker
