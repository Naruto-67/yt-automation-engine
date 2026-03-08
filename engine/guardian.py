# engine/guardian.py
import os
import json
from datetime import datetime
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_error, notify_summary
from engine.logger import logger

class GhostGuardian:
    def __init__(self):
        # Point 19: Define mathematical constants for forecasting
        self.COST_PER_VIDEO = {
            "youtube_points": 1850,  # 1600 (upload) + 250 (metadata/playlists)
            "gemini_calls": 3,       # Research + Script + Metadata
            "image_calls": 7         # Average scenes per video
        }
        self.SAFE_MODE_THRESHOLD = 0.85 # Activate safe mode at 85% quota usage

    def get_run_forecast(self):
        """
        Point 19: Predicts how many videos the current quota can support.
        """
        state = quota_manager._get_active_state()
        
        yt_rem = 10000 - state.get("youtube_points_used", 0)
        gem_rem = 40 - state.get("gemini_used", 0)
        img_rem = 95 - state.get("cf_images_used", 0)

        # Calculate bottleneck
        limit_yt = yt_rem // self.COST_PER_VIDEO["youtube_points"]
        limit_gem = gem_rem // self.COST_PER_VIDEO["gemini_calls"]
        limit_img = img_rem // self.COST_PER_VIDEO["image_calls"]

        forecast = min(limit_yt, limit_gem, limit_img)
        
        logger.engine(f"🔮 FORECAST: System can support ~{forecast} more videos today.")
        return int(forecast)

    def pre_flight_check(self) -> bool:
        """
        Point 8: Final check before a JobRunner starts a new job.
        """
        forecast = self.get_run_forecast()
        
        if forecast < 1:
            msg = "🛑 [GUARDIAN] Critical Quota Depletion. Aborting run to protect API health."
            logger.error(msg)
            notify_summary(False, msg)
            return False

        # Point 10: Check if Safe Mode should be forced
        state = quota_manager._get_active_state()
        if (state.get("cf_images_used", 0) / 95) > self.SAFE_MODE_THRESHOLD:
            logger.engine("⚠️ [GUARDIAN] High Image Usage detected. Enabling SAFE_MODE (Pexels Only).")
            os.environ["GHOST_SAFE_MODE"] = "true"
        
        return True

    def report_incident(self, module: str, error: Exception):
        """
        Point 9: Self-healing detection.
        Decides if an error is a 'retryable glitch' or a 'fatal provider failure'.
        """
        err_msg = str(error).lower()
        
        # Point 11: Detect API Changes/Auth failures
        if any(x in err_msg for x in ["401", "unauthorized", "invalid_grant"]):
            logger.error(f"🚨 [GUARDIAN] Auth Failure in {module}. Disabling provider.")
            notify_error(module, "AUTH_FAILURE", "Refresh token may have expired. Manual intervention required.")
            return "FATAL"

        # Detect Quota exhaustion mid-run
        if any(x in err_msg for x in ["429", "quota", "limit reached"]):
            logger.engine(f"⚠️ [GUARDIAN] {module} hit quota. Triggering provider swap.")
            return "SWAP_PROVIDER"

        return "RETRY"

guardian = GhostGuardian()
