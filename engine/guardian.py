import os
from engine.database import db
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_error, notify_summary

class GhostGuardian:
    """The system health monitor and quota forecaster."""
    
    @staticmethod
    def pre_flight_check(channel_id):
        """
        Predicts if a run should proceed.
        Requires ~1800 points per video (1600 upload + 200 metadata/playlist).
        """
        state = quota_manager._get_active_state()
        yt_used = state.get("youtube_points_used", 0)
        yt_limit = 9500 # Safety margin
        
        remaining = yt_limit - yt_used
        potential_videos = remaining // 1800
        
        if potential_videos < 1:
            print(f"🛑 [GUARDIAN] Critical: Insufficient YouTube Quota ({remaining} pts).")
            return False, "Quota Exhausted"
            
        return True, f"Clear for {potential_videos} videos"

    @staticmethod
    def detect_instability(module, error):
        """Logic for Point 10: Safe Mode Execution."""
        error_str = str(error).lower()
        if "rate limit" in error_str or "quota" in error_str:
            print(f"⚠️ [GUARDIAN] Instability in {module}. Activating Safe Mode...")
            os.environ["SAFE_MODE"] = "True"
            return True
        return False

guardian = GhostGuardian()
