# engine/orchestrator.py
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
        if not live_name or live_name == channel_config.channel_name:
            return
            
        logger.engine(f"🔄 Identity Sync: '{channel_config.channel_name}' → '{live_name}'")
        path = config_manager.channels_path
        temp_path = f"{path}.tmp"
        
        try:
            with open(path, "r", encoding="utf-8") as f: content = f.read()
            old_line = f'name: "{channel_config.channel_name}"'
            new_line = f'name: "{live_name}"'
            if old_line in content: content = content.replace(old_line, new_line)
            else: content = re.sub(rf'name:\s*[\'"]?{re.escape(channel_config.channel_name)}[\'"]?', f'name: "{live_name}"', content)
            with open(temp_path, "w", encoding="utf-8") as f: f.write(content)
            os.replace(temp_path, path)
            channel_config.channel_name = live_name
            config_manager.reload_channels()
        except Exception as e:
            trace = traceback.format_exc()
            logger.error(f"Identity sync failed safely:\n{trace}")

    def cleanup(self):
        logger.engine("🧹 Workspace cleanup...")
        patterns = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.png", "temp_*", "concat_list.txt", "temp_merged_*.mp4"]
        if not os.environ.get("GITHUB_ACTIONS") and not TEST_MODE: patterns.append("final_*.mp4")
        for p in patterns:
            for f in glob.glob(p):
                try: os.remove(f)
                except: pass

    def run_pipeline(self):
        if TEST_MODE: notify_summary(True, "🧪 **TEST MODE** — End-to-End system simulation initiated.")

        global_produced = 0  # Still tracks global state for TEST_MODE break logic

        for channel in self.channels:
            if TEST_MODE and global_produced >= 1: break
            
            # 🚨 V25 FIX: Isolate tracking variables per channel for accurate Discord reporting
            channel_produced = 0
            channel_failed = False
            
            set_channel_context(channel)
            ctx.set_channel_id(channel.channel_id)
            logger.engine(f"🚀 Processing: {channel.channel_name}")

            if TEST_MODE:
                logger.engine(f"🧪 [TEST MODE] Bypassing YouTube Auth. Executing full logic simulation.")
                yt_client = None
            else:
                yt_client = get_youtube_client(channel)
                if not yt_client:
                    logger.error(f"Auth failed for {channel.channel_id}. Skipping.")
                    notify_summary(False, f"🔴 Auth failure for `{channel.channel_id}` — check `{channel.youtube_refresh_token_env}` secret.")
                    continue

            live_name = get_channel_name(yt_client) if yt_client else None
            if live_name: self.sync_channel_identity(channel, live_name.replace("@", ""))

            vault_count = get_actual_vault_count(yt_client) if yt_client else (0 if TEST_MODE else 0)
            vault_max = config_manager.get_settings().get("vault", {}).get("max_videos", 14)
            if vault_count >= vault_max:
                logger.engine(f"🛑 Vault full ({vault_count}/{vault_max}). Skipping.")
                continue

            if not guardian.pre_flight_check():
                logger.error(f"Guardian halted run for {channel.channel_id}.")
                channel_failed = True
                notify_summary(False, "❌ Run aborted by Quota Guardian. API limits reached.")
                continue

            unprocessed = db.get_unprocessed_count(channel.channel_id)
            if unprocessed < 3: run_dynamic_research(channel, yt_client)

            batch = []
            priority_states = [JobState.RENDERING, JobState.VISUAL_GENERATION, JobState.VOICE_GENERATION, JobState.SCRIPT_GENERATION, JobState.QUEUED]
            
            for state in priority_states:
                jobs_in_state = db.get_jobs_by_state(channel.channel_id, state, limit=4)
                jobs_in_state.sort(key=lambda j: j.attempts) 
                batch.extend(jobs_in_state)

            max_videos = 1 if TEST_MODE else 4
            processed_this_run = 0

            for job in batch:
                if processed_this_run >= max_videos: break
                if not TEST_MODE and guardian.get_run_forecast() < 1:
                    logger.engine("🛑 [GUARDIAN] Quota depleted mid-run. Halting batch to protect AI resources.")
                    break
                    
                self.cleanup()
                try:
                    runner = JobRunner(job, youtube_client=yt_client, channel_name=channel.channel_name)
                    success = runner.process()
                    if success: 
                        channel_produced += 1
                        global_produced += 1
                    else: 
                        channel_failed = True
                    processed_this_run += 1
                except Exception as e:
                    channel_failed = True
                    trace = traceback.format_exc()
                    print(f"\n🚨 [ORCHESTRATOR ERROR] Job Runner failed:\n{trace}\n")
                    action = guardian.report_incident(job.state.name, e)
                    if action == "FATAL" and not TEST_MODE:
                        logger.error(f"🛑 [ORCHESTRATOR] Fatal incident reported. Halting batch for {channel.channel_id}.")
                        break

            self.cleanup()
            
            # 🚨 V25 FIX: Send the notification *here* inside the loop, so the payload targets the specific channel webhook with its specific numbers.
            if channel_failed:
                notify_summary(False, f"❌ Pipeline cycle encountered critical errors. Produced **{channel_produced}** video(s) for this channel.")
            elif channel_produced > 0:
                notify_summary(True, f"🌙 Pipeline cycle complete. Produced **{channel_produced}** video(s) for this channel.")
                
        if global_failed and TEST_MODE: sys.exit(1)
