# engine/orchestrator.py — Ghost Engine V6.1
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
from scripts.youtube_manager import get_youtube_client, get_actual_vault_count, get_channel_name
from scripts.dynamic_researcher import run_dynamic_research

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

class Orchestrator:
    def __init__(self):
        self.channels = config_manager.get_active_channels()

    def sync_channel_identity(self, channel_config, live_name: str):
        if not live_name or live_name == channel_config.channel_name:
            return
            
        logger.engine(f"🔄 Identity Sync: '{channel_config.channel_name}' → '{live_name}'")
        path = config_manager.channels_path
        temp_path = f"{path}.tmp"
        
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            
        for ch in data.get("channels", []):
            if ch.get("id") == channel_config.channel_id:
                ch["name"] = live_name
                
        # BUG-19 Fix: Atomic write to prevent YAML corruption
        with open(temp_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
            
        os.replace(temp_path, path)
        channel_config.channel_name = live_name
        config_manager.reload_channels()

    def cleanup(self):
        logger.engine("🧹 Workspace cleanup...")
        patterns = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.png", "temp_*", "concat_list.txt", "temp_merged_*.mp4"]
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

            set_channel_context(channel)
            os.environ["CURRENT_CHANNEL_ID"] = channel.channel_id

            yt_client = get_youtube_client(channel)
            if not yt_client and not TEST_MODE:
                logger.error(f"Auth failed for {channel.channel_id}. Skipping.")
                notify_summary(False, f"🔴 Auth failure for `{channel.channel_id}` — check `{channel.youtube_refresh_token_env}` secret.")
                continue

            if yt_client and not TEST_MODE:
                live_name = get_channel_name(yt_client)
                if live_name:
                    self.sync_channel_identity(channel, live_name.replace("@", ""))

            logger.engine(f"🚀 Processing: {channel.channel_name}")

            vault_count = get_actual_vault_count(yt_client) if not TEST_MODE else 5
            vault_max = config_manager.get_settings().get("vault", {}).get("max_videos", 14)
            if vault_count >= vault_max:
                logger.engine(f"🛑 Vault full ({vault_count}/{vault_max}). Skipping.")
                continue

            if not guardian.pre_flight_check():
                logger.error(f"Guardian halted run for {channel.channel_id}.")
                break

            unprocessed = db.get_unprocessed_count(channel.channel_id)
            if unprocessed < 3:
                run_dynamic_research(channel, yt_client)

            # BUG-16 Fix: Correct Batch Ordering. 
            # We sort by attempts ascending first, so fresh jobs run before stuck (attempts > 0) jobs.
            batch = []
            for state in [JobState.QUEUED, JobState.SCRIPT_GENERATION, JobState.VISUAL_GENERATION, JobState.VOICE_GENERATION, JobState.RENDERING]:
                jobs_in_state = db.get_jobs_by_state(channel.channel_id, state, limit=4)
                # Sort to ensure clean jobs run before retries
                jobs_in_state.sort(key=lambda j: j.attempts)
                batch.extend(jobs_in_state)

            max_videos = 1 if TEST_MODE else 4
            processed_this_run = 0

            for job in batch:
                if processed_this_run >= max_videos:
                    break
                self.cleanup()
                try:
                    runner = JobRunner(job, youtube_client=yt_client, channel_name=channel.channel_name)
                    runner.process()
                    global_produced += 1
                    processed_this_run += 1
                except Exception as e:
                    guardian.report_incident(job.state.name, e)

        self.cleanup()
        notify_summary(True, f"🌙 Pipeline cycle complete. Produced **{global_produced}** video(s) this run.")
