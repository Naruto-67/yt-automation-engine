# engine/guardian.py
import os
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_error, notify_summary
from engine.logger import logger

class GhostGuardian:
    def __init__(self):
        self.COST_PER_VIDEO = {
            "youtube_points": 1850,
            "gemini_calls": 3,
            "image_calls": 7
        }
        self.SAFE_MODE_THRESHOLD = 0.85
        self.channel_health = {} # Maps channel_id to health state

    def get_run_forecast(self):
        state = quota_manager._get_active_state()
        yt_rem = 10000 - state.get("youtube_points", 0)
        gem_rem = 40 - state.get("gemini_calls", 0)
        img_rem = 95 - state.get("cf_images", 0)

        limit_yt = yt_rem // self.COST_PER_VIDEO["youtube_points"]
        limit_gem = gem_rem // self.COST_PER_VIDEO["gemini_calls"]
        limit_img = img_rem // self.COST_PER_VIDEO["image_calls"]

        forecast = min(limit_yt, limit_gem, limit_img)
        logger.engine(f"🔮 FORECAST: System can support ~{forecast} more videos today.")
        return int(forecast)

    def is_safe_mode(self):
        """Checks if the currently processing channel is forced into Safe Mode."""
        channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
        return self.channel_health.get(channel_id, {}).get("safe_mode", False)

    def pre_flight_check(self) -> bool:
        if self.get_run_forecast() < 1:
            msg = "🛑 [GUARDIAN] Critical Quota Depletion. Aborting."
            logger.error(msg)
            notify_summary(False, msg)
            return False

        state = quota_manager._get_active_state()
        if (state.get("cf_images", 0) / 95) > self.SAFE_MODE_THRESHOLD:
            channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
            self._trigger_safe_mode(channel_id, "High Global Image Usage")
        
        return True
        
    def _trigger_safe_mode(self, channel_id, reason):
        if channel_id not in self.channel_health: 
            self.channel_health[channel_id] = {}
        self.channel_health[channel_id]["safe_mode"] = True
        logger.engine(f"⚠️ [GUARDIAN] Safe Mode enabled for {channel_id}: {reason}")

    def report_incident(self, module: str, error: Exception):
        err_msg = str(error).lower()
        channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
        
        if any(x in err_msg for x in ["401", "unauthorized", "invalid_grant"]):
            logger.error(f"🚨 [GUARDIAN] Auth Failure on {channel_id}.")
            notify_error(module, "AUTH_FAILURE", f"Channel {channel_id} token expired.")
            return "FATAL"

        if any(x in err_msg for x in ["429", "quota", "limit reached"]):
            self._trigger_safe_mode(channel_id, "API Quota Limit Hit")
            return "SWAP_PROVIDER"

        return "RETRY"

guardian = GhostGuardian()
