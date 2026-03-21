# engine/guardian.py — Ghost Engine V13.1
import os
import json
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_error, notify_summary, notify_quota_warning, notify_provider_swap
from engine.logger import logger
from engine.config_manager import config_manager
from engine.context import ctx
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
            "gemini_calls":   costs.get("gemini_calls", 3),
            "image_calls":    costs.get("image_calls", 7)
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
                    "date":     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "channels": self.channel_health
                }, f)
        except Exception as e:
            logger.error(f"Failed to save guardian health: {e}")

    def get_run_forecast(self):
        state  = quota_manager._get_active_state()
        yt_rem = quota_manager.LIMITS["youtube"] - state.get("youtube_points", 0)

        limit_yt = yt_rem // self.COST_PER_VIDEO["youtube_points"]

        logger.engine(f"🔮 FORECAST: System can support ~{limit_yt} more videos today based on YouTube quota.")
        return int(limit_yt)

    def is_safe_mode(self):
        channel_id = ctx.get_channel_id()
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

        # ── Cloudflare quota monitoring (unchanged) ───────────────────────────
        cf_usage = state.get("cf_images", 0)
        cf_limit = quota_manager.LIMITS.get("cloudflare", 95)

        if cf_usage > (cf_limit * 0.8) and cf_usage < (cf_limit * self.SAFE_MODE_THRESHOLD):
            notify_quota_warning("Cloudflare", cf_usage, cf_limit)

        if (cf_usage / max(cf_limit, 1)) > self.SAFE_MODE_THRESHOLD:
            self._trigger_safe_mode("GLOBAL", "Cloudflare Quota Critical")

        # ── BUG #7 FIX: HuggingFace quota was completely unmonitored. ─────────
        # The original code only checked cf_images, so even when HF was fully
        # exhausted (hf_images >= 45) or silently 403-ing on every scene, the
        # guardian never fired a Discord warning and never triggered safe_mode.
        # This is now mirrored for HF using the same warn/trigger thresholds.
        hf_usage = state.get("hf_images", 0)
        hf_limit = quota_manager.LIMITS.get("huggingface", 45)

        if hf_usage > (hf_limit * 0.8) and hf_usage < (hf_limit * self.SAFE_MODE_THRESHOLD):
            notify_quota_warning("HuggingFace", hf_usage, hf_limit)
            logger.engine(f"⚠️ [GUARDIAN] HuggingFace quota at {hf_usage}/{hf_limit} — approaching daily limit.")

        if hf_limit > 0 and (hf_usage / hf_limit) > self.SAFE_MODE_THRESHOLD:
            self._trigger_safe_mode("GLOBAL", "HuggingFace Quota Critical")

        # ── Combined image quota check: if BOTH AI image tiers are exhausted ──
        # safe_mode ensures we skip AI generation entirely and go straight to
        # Pexels — no point attempting CF or HF if both are known-exhausted.
        both_exhausted = (
            quota_manager.is_provider_exhausted("cloudflare") and
            quota_manager.is_provider_exhausted("huggingface")
        )
        if both_exhausted:
            logger.engine("⚠️ [GUARDIAN] Both Cloudflare and HuggingFace image providers exhausted. Activating safe_mode.")
            notify_quota_warning("All AI Image Providers", cf_usage + hf_usage, cf_limit + hf_limit)
            self._trigger_safe_mode("GLOBAL", "All AI Image Providers Exhausted")

        return True

    def _trigger_safe_mode(self, target_id, reason):
        if target_id not in self.channel_health:
            self.channel_health[target_id] = {}

        if not self.channel_health[target_id].get("safe_mode"):
            self.channel_health[target_id]["safe_mode"] = True
            self._save_health()
            logger.engine(f"⚠️ [GUARDIAN] Safe Mode activated for {target_id}: {reason}")
            notify_summary(True, f"🛡️ **Safe Mode Engaged** for {target_id}.\nBypassing custom AI imagery to conserve quota.\nReason: {reason}")

    def report_incident(self, module, error):
        err_msg    = str(error).lower()
        channel_id = ctx.get_channel_id()

        if any(x in err_msg for x in ["401", "unauthorized", "invalid_grant"]):
            logger.error(f"🚨 [GUARDIAN] Auth Failure for {channel_id}.")
            notify_error(module, "AUTH_FAILURE", f"The token for {channel_id} has expired or been revoked.")
            return "FATAL"

        if "youtube" in str(error).lower() or "upload" in module.lower():
            if any(x in err_msg for x in ["403", "quota", "exceeded"]):
                logger.error(f"🚨 [GUARDIAN] YouTube Quota Exceeded for {channel_id}. Syncing remote ban to local DB.")
                quota_manager.consume_points("youtube", 99999)
                notify_error(module, "YT_QUOTA_EXCEEDED", "YouTube 10,000pt limit reached. Halting channel for the day.")
                return "FATAL"

        # ── BUG #7 FIX (continued): HF/CF auth errors should also be reported
        # as provider-level incidents so the guardian can log and notify,
        # rather than silently falling through to Pexels every run.
        if any(x in err_msg for x in ["hf auth error", "cf auth error"]):
            logger.error(f"🚨 [GUARDIAN] AI Image Provider auth failure in {module}: {error}")
            notify_error(module, "IMAGE_AUTH_FAILURE",
                         f"Image generation auth failed: {error}. "
                         f"Check HF_TOKEN / CF_API_TOKEN secrets.")
            return "SWAP_PROVIDER"

        if any(x in err_msg for x in ["429", "quota", "limit reached"]):
            self._trigger_safe_mode("GLOBAL", "Mid-run API strike")
            return "SWAP_PROVIDER"

        return "RETRY"

    def report_swap(self, module, old_prov, new_prov):
        logger.engine(f"🔄 Failover in {module}: {old_prov} -> {new_prov}")
        notify_provider_swap(module, old_prov, new_prov)

guardian = GhostGuardian()
