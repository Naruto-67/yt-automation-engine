# engine/orchestrator.py
import glob
import os
import time
from engine.logger import logger
from engine.config_manager import config_manager
from engine.database import db
from engine.models import JobState
from engine.job_runner import JobRunner
from scripts.dynamic_researcher import run_dynamic_research
from scripts.youtube_manager import get_youtube_client, get_actual_vault_count, upload_to_youtube_vault, get_channel_name
from scripts.discord_notifier import notify_summary, notify_step

# 🧙‍♀️ THE TEST SWITCH ────────────────────────────────────────────────────────
TEST_MODE = True  # Set to False when you are ready to officially launch!
# ─────────────────────────────────────────────────────────────────────────

os.environ["TEST_MODE"] = str(TEST_MODE)

class Orchestrator:
    def __init__(self):
        self.channels = config_manager.get_active_channels()

    def global_garbage_collector(self):
        logger.engine("🧹 Initializing Global Garbage Collection...")
        extensions = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.jpeg", "*.JPEG", "*.png", "temp_*", "concat_list.txt"]
        for ext in extensions:
            for file in glob.glob(ext):
                try: os.remove(file)
                except: pass
                
        for file in glob.glob("temp_anim_*.mp4"):
            try: os.remove(file)
            except: pass
            
        for file in glob.glob("temp_merged*.mp4"):
            try: os.remove(file)
            except: pass

    def run_pipeline(self):
        logger.engine("☀️ System Wake. V5.0 Multi-Channel Orchestrator Initialized.")
        if TEST_MODE:
            logger.engine("🧪 TEST MODE ACTIVE: Videos will be generated but NOT uploaded to YouTube.")
            notify_summary(True, "🧪 **TEST MODE ACTIVE**\nMulti-Channel Engine running. Videos will be rendered but YouTube uploads are disabled.")

        self.global_garbage_collector()

        global_videos_processed = 0  # 🚨 SOLVED: Global counter to stop after 1 total video across all channels

        for channel in self.channels:
            if TEST_MODE and global_videos_processed >= 1:
                logger.engine("🧪 [TEST MODE] Global 1-video limit reached. Halting pipeline.")
                break

            logger.engine(f"--- 🚀 Commencing Production Cycle for {channel.channel_name} ---")
            
            yt_client = get_youtube_client(channel.youtube_refresh_token_env)
            if not yt_client and not TEST_MODE:
                logger.error(f"Failed to authenticate YouTube for {channel.channel_name}. Skipping to next channel.")
                continue
                
            vault_count = get_actual_vault_count(yt_client) if not TEST_MODE else 5
            logger.engine(f"🏦 {channel.channel_name} Vault Status: {vault_count}/14 videos.")
            
            if vault_count >= 14:
                logger.engine(f"🛑 Vault full for {channel.channel_name}. Halting production to conserve APIs.")
                continue

            queued_jobs = db.get_jobs_by_state(channel.channel_id, JobState.QUEUED, limit=20)
            if len(queued_jobs) < 4:
                logger.research(f"⚠️ Queue critically low ({len(queued_jobs)}). Triggering Emergency Researcher...")
                if not TEST_MODE:
                    run_dynamic_research(channel, yt_client)
                else:
                    logger.research("🧪 [TEST MODE] Skipping actual YouTube metadata pull, running researcher...")
                    run_dynamic_research(channel, yt_client)
            
            pending_jobs = (
                db.get_jobs_by_state(channel.channel_id, JobState.QUEUED, limit=4) +
                db.get_jobs_by_state(channel.channel_id, JobState.SCRIPT_GENERATION, limit=4) +
                db.get_jobs_by_state(channel.channel_id, JobState.VOICE_GENERATION, limit=4) +
                db.get_jobs_by_state(channel.channel_id, JobState.VISUAL_GENERATION, limit=4) +
                db.get_jobs_by_state(channel.channel_id, JobState.RENDERING, limit=4)
            )
            
            pending_jobs.sort(key=lambda x: x.created_at)
            
            if TEST_MODE:
                batch = pending_jobs[:1]
            else:
                batch = pending_jobs[:4] 
            
            if not batch:
                logger.engine(f"No pending jobs found for {channel.channel_name}. Proceeding to next.")
                continue

            yt_channel_display_name = get_channel_name(yt_client).replace("@", "") if not TEST_MODE else channel.channel_name

            for job in batch:
                self.global_garbage_collector()
                
                runner = JobRunner(job)
                runner.job.channel_id = yt_channel_display_name 
                
                runner.process()
                global_videos_processed += 1  # Increment global counter
                
                if runner.job.state == JobState.VAULTED and runner.job.video_path and not runner.job.youtube_id:
                    if not TEST_MODE:
                        logger.publish(f"Uploading Video {runner.job.id} to {channel.channel_name} Vault...")
                        
                        upload_success, video_id = upload_to_youtube_vault(
                            yt_client,
                            runner.job.video_path,
                            runner.job.topic,
                            runner.job.metadata,
                            runner.job.niche
                        )
                        
                        if upload_success:
                            runner.job.youtube_id = video_id
                            db.upsert_job(runner.job)
                            notify_step(runner.job.topic, "Upload Complete", f"Successfully vaulted to **{channel.channel_name}**.", 0x2ecc71)
                        else:
                            logger.error(f"Failed to vault {runner.job.topic} to {channel.channel_name}")
                    else:
                        logger.publish(f"🧪 [TEST MODE] Skipping YouTube upload for '{runner.job.topic}'. Flagging as virtually vaulted.")
                        runner.job.youtube_id = "test_mode_dummy_id"
                        db.upsert_job(runner.job)
                        
            self.global_garbage_collector()

        notify_summary(True, f"🌙 **System Sleep**\nMulti-Channel Pipeline cycle complete. Runner shutting down.")
