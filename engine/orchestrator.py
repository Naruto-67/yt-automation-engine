# engine/orchestrator.py
import os
import glob
import time
from engine.logger import logger
from engine.config_manager import config_manager
from engine.database import db
from engine.models import JobState
from engine.job_runner import JobRunner
from engine.guardian import guardian
from scripts.dynamic_researcher import run_dynamic_research
from scripts.youtube_manager import get_youtube_client, get_actual_vault_count, get_channel_name, upload_to_youtube_vault
from scripts.discord_notifier import notify_summary, notify_step

# 🧙‍♀️ POINT 10: THE TEST SWITCH
# Set via environment variable in GitHub Actions
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

class Orchestrator:
    def __init__(self):
        self.channels = config_manager.get_active_channels()
        os.environ["TEST_MODE"] = str(TEST_MODE)

    def global_garbage_collector(self):
        """POINT 20: Standardized cleanup to prevent disk bloat and desync."""
        logger.engine("🧹 Initializing Global Garbage Collection...")
        extensions = [
            "*.wav", "*.srt", "*.ass", "*.jpg", "*.jpeg", "*.png", 
            "temp_*", "concat_list.txt", "temp_anim_*.mp4", "temp_merged*.mp4"
        ]
        for pattern in extensions:
            for file in glob.glob(pattern):
                try: 
                    os.remove(file)
                except: 
                    pass

    def run_pipeline(self):
        """The Multi-Channel Dispatcher Loop."""
        if TEST_MODE:
            logger.engine("🧪 TEST MODE ACTIVE: 1-video global limit enforced. No uploads.")
            notify_summary(True, "🧪 **TEST MODE ACTIVE**\nVideos will render but YouTube uploads are disabled.")

        self.global_garbage_collector()
        global_videos_processed = 0

        for channel in self.channels:
            # POINT 10: Test Mode Global Limit
            if TEST_MODE and global_videos_processed >= 1:
                logger.engine("🧪 [TEST MODE] Global 1-video limit reached. Halting.")
                break

            logger.engine(f"🚀 Commencing Production: {channel.channel_name}")
            
            # 1. Auth & Vault Check (Point 16)
            yt_client = get_youtube_client(channel.youtube_refresh_token_env)
            if not yt_client and not TEST_MODE:
                logger.error(f"Auth failed for {channel.channel_name}. Skipping.")
                continue
                
            vault_count = get_actual_vault_count(yt_client) if not TEST_MODE else 5
            logger.engine(f"🏦 Vault Status: {vault_count}/14")
            
            if vault_count >= 14:
                logger.engine(f"🛑 Vault full for {channel.channel_name}. Skipping.")
                continue

            # 2. Queue Management & Research (Point 11)
            queued_jobs = db.get_jobs_by_state(channel.channel_id, JobState.QUEUED, limit=20)
            if len(queued_jobs) < 4:
                logger.research(f"⚠️ Queue low ({len(queued_jobs)}). Triggering Research...")
                run_dynamic_research(channel, yt_client)
            
            # 3. Fetch IDEMPOTENT batch (Point 5)
            # Prioritize jobs already in progress (e.g. Rendering or Voice)
            pending_jobs = []
            states_to_resume = [
                JobState.RENDERING, 
                JobState.VISUAL_GENERATION, 
                JobState.VOICE_GENERATION, 
                JobState.SCRIPT_GENERATION,
                JobState.QUEUED
            ]
            
            for state in states_to_resume:
                pending_jobs.extend(db.get_jobs_by_state(channel.channel_id, state, limit=4))
            
            # Remove duplicates while maintaining order
            seen_ids = set()
            batch = []
            for j in pending_jobs:
                if j.id not in seen_ids:
                    batch.append(j)
                    seen_ids.add(j.id)

            if TEST_MODE:
                batch = batch[:1]
            else:
                batch = batch[:4] # Standard 4-video daily burst

            # 4. Process Batch
            yt_display_name = get_channel_name(yt_client).replace("@", "") if not TEST_MODE else channel.channel_name

            for job in batch:
                self.global_garbage_collector()
                
                runner = JobRunner(job)
                # Map actual YouTube name for watermarking
                runner.job.channel_id = yt_display_name 
                
                runner.process()
                global_videos_processed += 1
                
                # 5. Vaulting Logic (Point 16)
                if runner.job.state == JobState.VAULTED and runner.job.video_path:
                    if not TEST_MODE:
                        logger.publish(f"Vaulting Video {runner.job.id}...")
                        
                        # Load metadata for upload
                        metadata = {}
                        if runner.job.metadata:
                            try: metadata = json.loads(runner.job.metadata)
                            except: pass

                        success, video_id = upload_to_youtube_vault(
                            yt_client,
                            runner.job.video_path,
                            runner.job.topic,
                            metadata,
                            runner.job.niche
                        )
                        
                        if success:
                            runner.job.youtube_id = video_id
                            db.upsert_job(runner.job)
                            notify_step(runner.job.topic, "Vaulted", f"Success to **{channel.channel_name}**.", 0x2ecc71)
                    else:
                        logger.publish(f"🧪 [TEST] Flagging '{runner.job.topic}' as vaulted.")
                        runner.job.youtube_id = "test_mode_dummy_id"
                        db.upsert_job(runner.job)
                
                if TEST_MODE: break # Stop after 1 job in test mode

        self.global_garbage_collector()
        notify_summary(True, f"📊 **Cycle Complete**\nProcessed {global_videos_processed} video(s). System standing down.")
