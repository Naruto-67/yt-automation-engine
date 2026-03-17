# engine/orchestrator.py
# Ghost Engine V26.0.0 — Multi-Channel Command & Control
import os
import sys
import glob
import yaml
import re
import traceback
from engine.logger import logger
from engine.config_manager import config_manager
from engine.database import db
from engine.models import VideoJob, JobState
from engine.job_runner import JobRunner
from engine.guardian import guardian
from engine.context import ctx
from scripts.discord_notifier import set_channel_context, notify_summary
from scripts.youtube_manager import get_youtube_client, get_actual_vault_count, get_channel_name
from scripts.dynamic_researcher import run_dynamic_research

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

class Orchestrator:
    def __init__(self):
        self.channels = config_manager.get_active_channels()

    def sync_channel_identity(self, channel_config, live_name: str):
        """
        V26: Synchronizes YAML 'name' with the actual YouTube handle to maintain 
        consistent branding across Discord and Logs. [cite: 151-153]
        """
        if not live_name or live_name == channel_config.channel_name:
            return
            
        logger.engine(f"🔄 Identity Sync: '{channel_config.channel_name}' → '{live_name}'")
        path = config_manager.channels_path
        temp_path = f"{path}.tmp"
        
        try:
            with open(path, "r", encoding="utf-8") as f: content = f.read()
            old_line = f'name: "{channel_config.channel_name}"'
            new_line = f'name: "{live_name}"'
            
            if old_line in content: 
                content = content.replace(old_line, new_line)
            else: 
                content = re.sub(rf'name:\s*[\'"]?{re.escape(channel_config.channel_name)}[\'"]?', f'name: "{live_name}"', content)
            
            with open(temp_path, "w", encoding="utf-8") as f: f.write(content)
            os.replace(temp_path, path)
            channel_config.channel_name = live_name
            config_manager.reload_channels()
        except Exception as e:
            logger.error(f"Identity sync failed safely: {e}")

    def cleanup(self):
        """Standard V26 workspace hygiene to prevent disk bloat. [cite: 154]"""
        logger.engine("🧹 Workspace cleanup...")
        patterns = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.png", "temp_*", "concat_list.txt", "temp_merged_*.mp4"]
        if not os.environ.get("GITHUB_ACTIONS") and not TEST_MODE: 
            patterns.append("final_*.mp4")
        for p in patterns:
            for f in glob.glob(p):
                try: os.remove(f)
                except: pass

    def run_pipeline(self):
        """Master Orchestration Loop. [cite: 155-170]"""
        if TEST_MODE: notify_summary(True, "🧪 **TEST MODE** — Production simulation initiated.")

        global_produced = 0  
        global_failed = False 

        for channel in self.channels:
            if TEST_MODE and global_produced >= 1: break
            
            # V26: Strict channel isolation 
            channel_produced = 0
            channel_failed = False
            
            set_channel_context(channel)
            ctx.set_channel_id(channel.channel_id)
            logger.engine(f"🚀 Processing: {channel.channel_name} (Niche: {channel.niche})")

            # YouTube Authentication
            if TEST_MODE:
                yt_client = None
            else:
                yt_client = get_youtube_client(channel)
                if not yt_client:
                    logger.error(f"Auth failed for {channel.channel_id}.")
                    notify_summary(False, f"🔴 Auth failure for `{channel.channel_id}`.")
                    continue

            # Identity Sync Logic [cite: 158]
            live_name = get_channel_name(yt_client) if yt_client else None
            if live_name: self.sync_channel_identity(channel, live_name.replace("@", ""))

            # Vault & Quota Checks [cite: 159-161]
            vault_count = get_actual_vault_count(yt_client) if yt_client else 0
            vault_max = config_manager.get_settings().get("vault", {}).get("max_videos", 14)
            if vault_count >= vault_max:
                logger.engine(f"🛑 Vault full ({vault_count}/{vault_max}). Skipping.")
                continue

            if not guardian.pre_flight_check():
                channel_failed = True; global_failed = True
                notify_summary(False, "❌ Run aborted by Quota Guardian.")
                continue

            # Auto-Research Trigger
            unprocessed = db.get_unprocessed_count(channel.channel_id)
            if unprocessed < 3: run_dynamic_research(channel, yt_client)

            # Job Batching 
            batch = []
            priority_states = [JobState.RENDERING, JobState.VISUAL_GENERATION, JobState.VOICE_GENERATION, JobState.SCRIPT_GENERATION, JobState.QUEUED]
            for state in priority_states:
                jobs_in_state = db.get_jobs_by_state(channel.channel_id, state, limit=4)
                batch.extend(jobs_in_state)

            max_videos = 1 if TEST_MODE else 4
            processed_this_run = 0

            for job in batch:
                if processed_this_run >= max_videos: break
                if not TEST_MODE and guardian.get_run_forecast() < 1:
                    logger.engine("🛑 [GUARDIAN] Quota depleted mid-run.")
                    break
                    
                self.cleanup()
                try:
                    runner = JobRunner(job, youtube_client=yt_client, channel_name=channel.channel_name, channel_config=channel)
                    success = runner.process()
                    if success: 
                        channel_produced += 1
                        global_produced += 1
                    else: 
                        channel_failed = True; global_failed = True
                    processed_this_run += 1
                except Exception as e:
                    channel_failed = True; global_failed = True
                    action = guardian.report_incident(job.state.name, e)
                    if action == "FATAL" and not TEST_MODE: break

            self.cleanup()
            
            # Status reporting [cite: 169-170]
            if channel_failed:
                notify_summary(False, f"❌ Pipeline cycle encountered errors. Produced **{channel_produced}** video(s).")
            elif channel_produced > 0:
                notify_summary(True, f"🌙 Pipeline cycle complete. Produced **{channel_produced}** video(s).")
                
        if global_failed and TEST_MODE: sys.exit(1)
