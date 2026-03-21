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

    def _get_test_topics(self) -> dict:
        """
        Load per-channel test topics from settings.yaml.
        Returns {channel_id: topic_string}
        Falls back to safe generic topics if settings block is missing.
        """
        settings     = config_manager.get_settings()
        test_topics  = settings.get("test_mode", {}).get("test_topics", {})
        fallbacks    = {
            "CH_01": "A small leaf discovers it holds an entire forgotten world on its surface",
            "CH_02": "The human brain generates enough electricity to power a small LED light bulb",
        }
        # Merge: settings values take priority over built-in fallbacks
        return {**fallbacks, **test_topics}

    def run_pipeline(self):
        if TEST_MODE: notify_summary(True, "🧪 **TEST MODE** — End-to-End system simulation initiated.")

        global_produced = 0  
        global_failed = False  # 🚨 FIX: Initialized here to prevent NameError on sys.exit

        for channel in self.channels:
            # ── In TEST_MODE, produce exactly one video per channel ────────────
            # The `global_produced >= 1` guard was removed: in the previous
            # implementation it caused the second channel to be skipped entirely,
            # meaning only CH_01 ever got a dry-run test video. We now let both
            # channels run their full pipeline. `max_videos = 1` below already
            # limits each channel to one video.
            
            # 🚨 V25 FIX: Isolate tracking variables per channel
            channel_produced = 0
            channel_failed = False
            
            set_channel_context(channel)
            ctx.set_channel_id(channel.channel_id)
            logger.engine(f"🚀 Processing: {channel.channel_name}")

            if TEST_MODE:
                logger.engine(f"🧪 [TEST MODE] Bypassing YouTube Auth. Full pipeline executing with real AI/FFmpeg.")
                yt_client = None
            else:
                yt_client = get_youtube_client(channel)
                if not yt_client:
                    logger.error(f"Auth failed for {channel.channel_id}. Skipping.")
                    notify_summary(False, f"🔴 Auth failure for `{channel.channel_id}` — check `{channel.youtube_refresh_token_env}` secret.")
                    continue

            live_name = get_channel_name(yt_client) if yt_client else None
            if live_name: self.sync_channel_identity(channel, live_name.replace("@", ""))

            # ── VAULT CAPACITY CHECK ──────────────────────────────────────────
            # BUG FIX: Previous implementation always set max_videos=4 regardless
            # of how many slots were actually available in the vault. This caused
            # vault overflow (e.g. 13/14 → produced 4 → vault became 17/14).
            #
            # FIXED LOGIC:
            #   slots_available = vault_max - vault_count
            #   max_videos = min(4, slots_available)
            #
            # In TEST_MODE: vault_count=0 (no YouTube auth), max_videos=1.
            vault_count = get_actual_vault_count(yt_client) if yt_client else 0
            vault_max   = config_manager.get_settings().get("vault", {}).get("max_videos", 14)

            if not TEST_MODE and vault_count >= vault_max:
                logger.engine(f"🛑 Vault full ({vault_count}/{vault_max}). Skipping {channel.channel_id}.")
                continue

            slots_available = vault_max - vault_count
            logger.engine(f"📦 Vault: {vault_count}/{vault_max} — {slots_available} slot(s) available.")

            # max_videos: in TEST_MODE always 1; in production capped by actual vault space.
            # max(1, slots_available) ensures we never try 0 (vault_full guard above handles that case).
            max_videos = 1 if TEST_MODE else min(4, max(1, slots_available))
            logger.engine(f"🎬 Will produce up to {max_videos} video(s) for {channel.channel_id}.")

            if not TEST_MODE and not guardian.pre_flight_check():
                logger.error(f"Guardian halted run for {channel.channel_id}.")
                channel_failed = True
                global_failed = True
                notify_summary(False, "❌ Run aborted by Quota Guardian. API limits reached.")
                continue

            # ── DRY RUN PATH: synthetic in-memory jobs, zero DB interaction ───
            if TEST_MODE:
                test_topics = self._get_test_topics()
                test_topic  = test_topics.get(channel.channel_id, f"Amazing fact about {channel.niche}")

                logger.engine(
                    f"🧪 [TEST MODE] Creating synthetic in-memory job for {channel.channel_id}:\n"
                    f"   Topic: {test_topic}"
                )

                # Synthetic VideoJob — id=-1 is sentinel: never inserted to DB
                synthetic_job = VideoJob(
                    id=-1,
                    channel_id=channel.channel_id,
                    topic=test_topic,
                    niche=channel.niche,
                    state=JobState.QUEUED,
                )

                self.cleanup()
                try:
                    # dry_run=True: JobRunner will not call db.upsert_job() at any point
                    runner  = JobRunner(
                        synthetic_job,
                        youtube_client=None,
                        channel_name=channel.channel_name,
                        channel_config=channel,
                        dry_run=True,
                    )
                    success = runner.process()
                    if success:
                        channel_produced += 1
                        global_produced  += 1
                    else:
                        channel_failed = True
                        global_failed  = True
                except Exception as e:
                    channel_failed = True
                    global_failed  = True
                    trace = traceback.format_exc()
                    print(f"\n🚨 [ORCHESTRATOR ERROR] Dry-run job failed for {channel.channel_id}:\n{trace}\n")

                self.cleanup()

                if channel_failed:
                    notify_summary(False, f"❌ [TEST MODE] Dry-run failed for `{channel.channel_id}`.")
                elif channel_produced > 0:
                    notify_summary(True, f"✅ [TEST MODE] Dry-run complete. Produced **{channel_produced}** test video(s) for `{channel.channel_id}`.")
                continue   # ← skip the production path below for this channel

            # ── PRODUCTION PATH ───────────────────────────────────────────────
            unprocessed = db.get_unprocessed_count(channel.channel_id)
            if unprocessed < 3: run_dynamic_research(channel, yt_client)

            batch = []
            priority_states = [JobState.RENDERING, JobState.VISUAL_GENERATION, JobState.VOICE_GENERATION, JobState.SCRIPT_GENERATION, JobState.QUEUED]
            
            for state in priority_states:
                jobs_in_state = db.get_jobs_by_state(channel.channel_id, state, limit=4)
                jobs_in_state.sort(key=lambda j: j.attempts) 
                batch.extend(jobs_in_state)

            processed_this_run = 0

            for job in batch:
                if processed_this_run >= max_videos: break
                if guardian.get_run_forecast() < 1:
                    logger.engine("🛑 [GUARDIAN] Quota depleted mid-run. Halting batch to protect AI resources.")
                    break
                    
                self.cleanup()
                try:
                    runner = JobRunner(
                        job,
                        youtube_client=yt_client,
                        channel_name=channel.channel_name,
                        channel_config=channel,
                        dry_run=False,   # production: always write to DB
                    )
                    success = runner.process()
                    if success: 
                        channel_produced += 1
                        global_produced += 1
                    else: 
                        channel_failed = True
                        global_failed = True
                    processed_this_run += 1
                except Exception as e:
                    channel_failed = True
                    global_failed = True
                    trace = traceback.format_exc()
                    print(f"\n🚨 [ORCHESTRATOR ERROR] Job Runner failed:\n{trace}\n")
                    action = guardian.report_incident(job.state.name, e)
                    if action == "FATAL":
                        logger.error(f"🛑 [ORCHESTRATOR] Fatal incident reported. Halting batch for {channel.channel_id}.")
                        break

            self.cleanup()
            
            if channel_failed:
                notify_summary(False, f"❌ Pipeline cycle encountered critical errors. Produced **{channel_produced}** video(s) for this channel.")
            elif channel_produced > 0:
                notify_summary(True, f"🌙 Pipeline cycle complete. Produced **{channel_produced}** video(s) for this channel.")
                
        if global_failed and TEST_MODE: sys.exit(1)
