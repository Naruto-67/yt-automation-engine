# engine/orchestrator.py
import os
import glob
import yaml
from engine.logger import logger
from engine.config_manager import config_manager
from engine.database import db
from engine.models import JobState
from engine.job_runner import JobRunner
from engine.guardian import guardian
from scripts.dynamic_researcher import run_dynamic_research
from scripts.youtube_manager import get_youtube_client, get_actual_vault_count, get_channel_name, upload_to_youtube_vault
from scripts.discord_notifier import notify_summary

# POINT 10: Enforce test mode limits
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

class Orchestrator:
    def __init__(self):
        self.channels = config_manager.get_active_channels()

    def sync_channel_identity(self, channel_config, live_name):
        """Auto-updates config/channels.yaml if the name was changed on the YouTube Dashboard."""
        if not live_name or live_name == channel_config.channel_name:
            return

        logger.engine(f"🔄 Identity Sync: YAML '{channel_config.channel_name}' -> Live '{live_name}'")
        
        path = config_manager.channels_path
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        for ch in data.get('channels', []):
            if ch['id'] == channel_config.channel_id:
                ch['name'] = live_name
        
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
        
        channel_config.channel_name = live_name

    def cleanup(self):
        logger.engine("🧹 Global Workspace Cleanup...")
        patterns = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.png", "temp_*", "final_job_*.mp4"]
        for p in patterns:
            for f in glob.glob(p):
                try: os.remove(f)
                except: pass

    def run_pipeline(self):
        if TEST_MODE:
            notify_summary(True, "🧪 **TEST MODE ACTIVE**\nGlobal 1-video limit per run enabled.")

        global_processed = 0
        for channel in self.channels:
            if TEST_MODE and global_processed >= 1:
                break

            # 🚨 Context Switching: This isolates webhooks and database queries
            os.environ["CURRENT_CHANNEL_ID"] = channel.channel_id
            os.environ["CURRENT_DISCORD_WEBHOOK_ENV"] = channel.discord_webhook_env

            yt_client = get_youtube_client(channel.youtube_refresh_token_env)
            if not yt_client and not TEST_MODE:
                logger.error(f"Auth failed for {channel.channel_id}. Skipping.")
                continue

            # Auto-Sync Identity (Dashboard -> Local Code)
            if yt_client and not TEST_MODE:
                live_name = get_channel_name(yt_client).replace("@", "")
                self.sync_channel_identity(channel, live_name)

            logger.engine(f"🚀 Processing: {channel.channel_name}")
            
            # Vault Check
            vault_count = get_actual_vault_count(yt_client) if not TEST_MODE else 5
            if vault_count >= 14:
                logger.engine(f"🛑 Vault Full ({vault_count}/14). Skipping.")
                continue

            # Research if low
            queued = db.get_jobs_by_state(channel.channel_id, JobState.QUEUED)
            if len(queued) < 3:
                run_dynamic_research(channel, yt_client)

            # Build Batch
            batch = []
            for state in [JobState.RENDERING, JobState.VOICE_GENERATION, JobState.QUEUED]:
                batch.extend(db.get_jobs_by_state(channel.channel_id, state, limit=2))
            
            for job in batch[:1 if TEST_MODE else 4]:
                self.cleanup()
                try:
                    runner = JobRunner(job)
                    runner.process()
                    global_processed += 1
                except Exception as e:
                    guardian.report_incident(job.state.name, e)

        self.cleanup()
        notify_summary(True, f"🌙 Pipeline cycle complete. Processed {global_processed} video(s).")
