# engine/guardian.py — Ghost Engine V6.3
import os
import json
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_error, notify_summary, notify_quota_warning, notify_provider_swap
from engine.logger import logger
from engine.config_manager import config_manager
from datetime import datetime, timezone

_HEALTH_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory", "guardian_health.json"
)

class GhostGuardian:
    def __init__(self):
        settings = config_manager.get_settings()
        costs = settings.get("guardian_costs", {})
        
        self.COST_PER_VIDEO = {
            "youtube_points": costs.get("youtube_points", 1850),
            "gemini_calls": costs.get("gemini_calls", 3),
            "image_calls": costs.get("image_calls", 7)
        }
        self.SAFE_MODE_THRESHOLD = costs.get("safe_mode_threshold", 0.85)
        self.channel_health = self._load_health()

    def _load_health(self):
        if os.path.exists(_HEALTH_PATH):
            try:
                with open(_HEALTH_PATH, "r") as f:
                    data = json.load(f)
                    if data.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                        return data.get("channels", {})
            except Exception:
                pass
        return {}

    def _save_health(self):
        os.makedirs(os.path.dirname(_HEALTH_PATH), exist_ok=True)
        try:
            with open(_HEALTH_PATH, "w") as f:
                json.dump({
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "channels": self.channel_health
                }, f)
        except Exception as e:
            logger.error(f"Failed to save guardian health: {e}")

    def get_run_forecast(self):
        state = quota_manager._get_active_state()
        yt_rem = quota_manager.LIMITS["youtube"] - state.get("youtube_points", 0)
        gem_rem = quota_manager.LIMITS["gemini"] - state.get("gemini_calls", 0)
        img_rem = quota_manager.LIMITS["cloudflare"] - state.get("cf_images", 0)

        limit_yt = yt_rem // self.COST_PER_VIDEO["youtube_points"]
        limit_gem = gem_rem // self.COST_PER_VIDEO["gemini_calls"]
        limit_img = img_rem // self.COST_PER_VIDEO["image_calls"]

        forecast = min(limit_yt, limit_gem, limit_img)
        logger.engine(f"🔮 FORECAST: System can support ~{forecast} more videos today.")
        return int(forecast)

    def is_safe_mode(self):
        """
        GOD-TIER FIX: Inherits GLOBAL safe mode state as well as per-channel state.
        If Cloudflare dies for Channel A, it correctly shuts off for Channel B.
        """
        channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
        ch_safe = self.channel_health.get(channel_id, {}).get("safe_mode", False)
        gl_safe = self.channel_health.get("GLOBAL", {}).get("safe_mode", False)
        return ch_safe or gl_safe

    def pre_flight_check(self) -> bool:
        forecast = self.get_run_forecast()
        if forecast < 1:
            msg = "🛑 [GUARDIAN] Critical Quota Depletion. Halting run to prevent API ban."
            logger.error(msg)
            notify_summary(False, msg)
            return False

        state = quota_manager._get_active_state()
        channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
        
        img_usage = state.get("cf_images", 0)
        img_limit = quota_manager.LIMITS.get("cloudflare", 95)
        
        if img_usage > (img_limit * 0.8) and img_usage < (img_limit * self.SAFE_MODE_THRESHOLD):
            notify_quota_warning("Cloudflare", img_usage, img_limit)

        if (img_usage / img_limit) > self.SAFE_MODE_THRESHOLD:
            # Trigger safe mode at the GLOBAL level, not just the channel level
            self._trigger_safe_mode("GLOBAL", "Global Resource Depletion")
        
        return True
        
    def _trigger_safe_mode(self, target_id, reason):
        if target_id not in self.channel_health: 
            self.channel_health[target_id] = {}
        
        if not self.channel_health[target_id].get("safe_mode"):
            self.channel_health[target_id]["safe_mode"] = True
            self._save_health()
            logger.engine(f"⚠️ [GUARDIAN] Safe Mode activated for {target_id}: {reason}")
            notify_summary(True, f"🛡️ **Safe Mode Engaged** for {target_id}.\nBypassing custom AI imagery to conserve quota.")

    def report_incident(self, module, error):
        err_msg = str(error).lower()
        channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
        
        if any(x in err_msg for x in ["401", "unauthorized", "invalid_grant"]):
            logger.error(f"🚨 [GUARDIAN] Auth Failure for {channel_id}.")
            notify_error(module, "AUTH_FAILURE", f"The token for {channel_id} has expired or been revoked.")
            return "FATAL"

        if any(x in err_msg for x in ["429", "quota", "limit reached"]):
            self._trigger_safe_mode("GLOBAL", "Mid-run API strike")
            return "SWAP_PROVIDER"

        return "RETRY"

    def report_swap(self, module, old_prov, new_prov):
        logger.engine(f"🔄 Failover in {module}: {old_prov} -> {new_prov}")
        notify_provider_swap(module, old_prov, new_prov)

guardian = GhostGuardian()
