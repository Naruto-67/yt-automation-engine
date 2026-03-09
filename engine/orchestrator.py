# engine/orchestrator.py — Ghost Engine V6
import os
import glob
import yaml
from engine.logger import logger
from engine.config_manager import config_manager
from engine.database import db
from engine.models import JobState
from engine.job_runner import JobRunner
from engine.guardian import guardian
from scripts.discord_notifier import set_channel_context, notify_summary
from scripts.youtube_manager import (
    get_youtube_client, get_actual_vault_count, get_channel_name
)
from scripts.dynamic_researcher import run_dynamic_research

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


class Orchestrator:
    def __init__(self):
        self.channels = config_manager.get_active_channels()

    def sync_channel_identity(self, channel_config, live_name: str):
        """Auto-updates channels.yaml if the display name changed on YouTube."""
        if not live_name or live_name == channel_config.channel_name:
            return
        logger.engine(
            f"🔄 Identity Sync: '{channel_config.channel_name}' → '{live_name}'"
        )
        path = config_manager.channels_path
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        for ch in data.get("channels", []):
            if ch.get("id") == channel_config.channel_id:
                ch["name"] = live_name
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        channel_config.channel_name = live_name

    def cleanup(self):
        logger.engine("🧹 Workspace cleanup...")
        patterns = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.png",
                    "temp_*", "concat_list.txt", "temp_merged_*.mp4"]
        for p in patterns:
            for f in glob.glob(p):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def run_pipeline(self):
        if TEST_MODE:
            notify_summary(True, "🧪 **TEST MODE** — Global 1-video limit active.")

        global_produced = 0

        for channel in self.channels:
            if TEST_MODE and global_produced >= 1:
                break

            # Set Discord context for this channel's webhook
            set_channel_context(channel)
            os.environ["CURRENT_CHANNEL_ID"] = channel.channel_id

            # ── Auth ──────────────────────────────────────────────────────────
            yt_client = get_youtube_client(channel)
            if not yt_client and not TEST_MODE:
                logger.error(f"Auth failed for {channel.channel_id}. Skipping.")
                notify_summary(False,
                    f"🔴 Auth failure for `{channel.channel_id}` — "
                    f"check `{channel.youtube_refresh_token_env}` secret.")
                continue

            # ── Identity sync ─────────────────────────────────────────────────
            if yt_client and not TEST_MODE:
                live_name = get_channel_name(yt_client)
                if live_name:
                    self.sync_channel_identity(channel, live_name.replace("@", ""))

            logger.engine(f"🚀 Processing: {channel.channel_name}")

            # ── Vault gate ───────────────────────────────────────────────────
            vault_count = get_actual_vault_count(yt_client) if not TEST_MODE else 5
            from engine.config_manager import config_manager as cm
            vault_max = cm.get_settings().get("vault", {}).get("max_videos", 14)
            if vault_count >= vault_max:
                logger.engine(f"🛑 Vault full ({vault_count}/{vault_max}). Skipping.")
                continue

            # ── Pre-flight guardian check ────────────────────────────────────
            if not guardian.pre_flight_check():
                logger.error(f"Guardian halted run for {channel.channel_id}.")
                break

            # ── Research if topic queue is low ───────────────────────────────
            unprocessed = db.get_unprocessed_count(channel.channel_id)
            if unprocessed < 3:
                run_dynamic_research(channel, yt_client)

            # ── Build production batch ───────────────────────────────────────
            batch = []
            for state in [JobState.RENDERING, JobState.VOICE_GENERATION,
                          JobState.VISUAL_GENERATION, JobState.QUEUED]:
                batch.extend(db.get_jobs_by_state(channel.channel_id, state, limit=2))

            max_videos = 1 if TEST_MODE else 4
            for job in batch[:max_videos]:
                self.cleanup()
                try:
                    runner = JobRunner(
                        job,
                        youtube_client=yt_client,
                        channel_name=channel.channel_name
                    )
                    runner.process()
                    global_produced += 1
                except Exception as e:
                    guardian.report_incident(job.state.name, e)

        self.cleanup()
        notify_summary(
            True,
            f"🌙 Pipeline cycle complete. "
            f"Produced **{global_produced}** video(s) this run."
        )
