# engine/job_runner.py — Ghost Engine V6.4
import os
import time
import shutil
import traceback
import json
from datetime import datetime
from engine.logger import logger
from engine.models import VideoJob, JobState, FailureLog
from engine.database import db

from scripts.generate_script   import generate_script
from scripts.generate_voice    import generate_audio
from scripts.generate_visuals  import fetch_scene_images
from scripts.render_video      import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.discord_notifier  import notify_step, notify_production_success, notify_vault_secure

class JobRunner:
    def __init__(self, job: VideoJob, youtube_client=None, channel_name: str = ""):
        self.job          = job
        self.youtube      = youtube_client
        self.channel_name = channel_name or job.channel_id
        self.max_attempts = 3
        self.base_filename = f"job_{job.id}_{job.channel_id.replace(' ', '_')}"
        
        # Instance variables to hold metrics for the Discord webhook
        self.final_duration = 0.0
        self.final_size_mb  = 0.0

    def process(self):
        os.environ["CURRENT_CHANNEL_ID"] = self.job.channel_id
        logger.engine(f"Processing Job {self.job.id} | Topic: {self.job.topic} | State: {self.job.state.name}")

        try:
            # ── GOD-TIER FIX: Ephemeral VM State Rewind ────────────────────────────────
            # GitHub Actions wipes intermediate files (.wav, .jpg) between runs.
            # If the DB state resumed an interrupted job, we must verify physical files exist.
            # If missing, smoothly rewind the state machine to regenerate them from the DB script.
            if self.job.state in [JobState.VISUAL_GENERATION, JobState.RENDERING]:
                if not self.job.audio_path or not os.path.exists(self.job.audio_path):
                    logger.engine(f"⚠️ [RECOVERY] Job {self.job.id} physical audio missing. Rewinding to VOICE_GENERATION...")
                    self._transition_to(JobState.VOICE_GENERATION)

            if self.job.state == JobState.RENDERING:
                paths = json.loads(self.job.image_paths) if self.job.image_paths else []
                if not paths or not all(os.path.exists(p) for p in paths):
                    logger.engine(f"⚠️ [RECOVERY] Job {self.job.id} physical images missing. Rewinding to VISUAL_GENERATION...")
                    self._transition_to(JobState.VISUAL_GENERATION)
            # ─────────────────────────────────────────────────────────────────────────

            if self.job.state == JobState.QUEUED:
                self._transition_to(JobState.SCRIPT_GENERATION)

            if self.job.state == JobState.SCRIPT_GENERATION:
                if self.job.script:
                    self._transition_to(JobState.VOICE_GENERATION)
                else:
                    self._execute_script_generation()

            if self.job.state == JobState.VOICE_GENERATION:
                if self.job.audio_path and os.path.exists(self.job.audio_path):
                    self._transition_to(JobState.VISUAL_GENERATION)
                else:
                    self._execute_voice_generation()

            if self.job.state == JobState.VISUAL_GENERATION:
                paths = json.loads(self.job.image_paths) if self.job.image_paths else []
                if paths and all(os.path.exists(p) for p in paths):
                    self._transition_to(JobState.RENDERING)
                else:
                    self._execute_visual_generation()

            if self.job.state == JobState.RENDERING:
                if self.job.video_path and os.path.exists(self.job.video_path):
                    self._execute_upload()
                else:
                    self._execute_rendering()

            if self.job.state == JobState.VAULTED:
                logger.success(f"Job {self.job.id} vaulted. YouTube ID: {self.job.youtube_id}")

        except Exception as e:
            self._handle_failure(str(e), traceback.format_exc())

    def _transition_to(self, new_state: JobState):
        self.job.state      = new_state
        self.job.updated_at = datetime.utcnow().isoformat()
        db.upsert_job(self.job)
        logger.engine(f"Job {self.job.id} → {new_state.name}")

    def _handle_failure(self, error_msg: str, trace: str):
        self.job.attempts += 1
        db.log_failure(FailureLog(
            job_id=self.job.id, channel_id=self.job.channel_id,
            module=self.job.state.name, error_message=error_msg, traceback=trace
        ))
        if self.job.attempts >= self.max_attempts:
            self._transition_to(JobState.FAILED)
            notify_step(self.job.topic, "FAILED", f"Critical crash after {self.max_attempts} attempts.", 0xe74c3c)
        else:
            db.upsert_job(self.job)
            time.sleep(5)

    def _execute_script_generation(self):
        logger.generation("Drafting script...")
        script_text, prompts, pexels, weights, prov, voice, color = generate_script(
            self.job.niche, self.job.topic
        )
        if not script_text:
            raise ValueError("Empty script returned from generator.")

        try:
            meta_data, _ = generate_seo_metadata(self.job.niche, script_text)
        except Exception as e:
            logger.error(f"SEO Generation failed: {e}. Using fallback metadata.")
            meta_data = {"title": f"{self.job.niche} #shorts"[:95], "description": "Mind blowing facts!", "tags": ["shorts", self.job.niche]}

        self.job.script = json.dumps({
            "text": script_text, "prompts": prompts, "pexels": pexels,
            "weights": weights, "provider": prov,
            "target_voice": voice, "target_color": color
        })
        self.job.metadata = json.dumps(meta_data)
        self._transition_to(JobState.VOICE_GENERATION)

    def _execute_voice_generation(self):
        logger.generation("Synthesizing audio...")
        script_data  = json.loads(self.job.script)
        audio_base   = f"temp_audio_{self.base_filename}"
        target_voice = script_data.get("target_voice", "am_adam")

        success, prov, duration = generate_audio(
            script_data["text"], output_base=audio_base, target_voice=target_voice
        )
        if not success:
            raise RuntimeError("TTS pipeline collapsed — all providers failed.")

        self.job.audio_path = f"{audio_base}.wav"
        self._transition_to(JobState.VISUAL_GENERATION)

    def _execute_visual_generation(self):
        logger.generation("Sourcing scene images...")
        script_data = json.loads(self.job.script)
        prompts     = script_data.get("prompts", [])
        pexels      = script_data.get("pexels", [])

        if not prompts:
            raise ValueError("No image prompts available in script data.")

        images, provider = fetch_scene_images(prompts, pexels, base_filename=f"temp_scene_{self.base_filename}")
        min_acceptable = max(1, len(prompts) // 2)
        
        if len(images) < min_acceptable:
            raise RuntimeError(f"Visual generation critically failed: {len(images)}/{len(prompts)} images.")

        while len(images) < len(prompts):
            images.append(images[-1]) 

        self.job.image_paths = json.dumps(images)
        self._transition_to(JobState.RENDERING)

    def _execute_rendering(self):
        logger.generation("Rendering final video...")
        script_data = json.loads(self.job.script)
        images      = json.loads(self.job.image_paths)
        weights     = script_data.get("weights", [])
        color       = script_data.get("target_color")

        scene_count = len(images)
        required_gb = max(2.0, (scene_count * 0.3) + 0.5)
        free_gb     = shutil.disk_usage("/").free / (1024 ** 3)
        if free_gb < required_gb:
            raise RuntimeError(f"Disk space too low: {free_gb:.1f} GB free, need {required_gb:.1f} GB.")

        output_path = f"final_{self.base_filename}.mp4"
        watermark   = self.channel_name or self.job.channel_id

        success, duration, size_mb = render_video(
            image_paths=images, audio_path=self.job.audio_path, output_path=output_path,
            scene_weights=weights, watermark_text=watermark, subtitle_color=color
        )
        
        if not success:
            raise RuntimeError("FFmpeg render failed — output not produced.")

        self.final_duration = duration
        self.final_size_mb  = size_mb
        self.job.video_path = output_path
        
        logger.success(f"Rendered: {output_path} ({size_mb:.1f} MB, {duration:.1f}s)")
        notify_step(self.job.topic, "RENDERED", f"└ Size: {size_mb:.1f} MB | Duration: {duration:.1f}s | Channel: {self.channel_name}", 0x9b59b6)
        
        self._execute_upload()

    def _execute_upload(self):
        if not self.youtube:
            raise RuntimeError("No YouTube client available for upload.")
            
        if not self.job.video_path or not os.path.exists(self.job.video_path):
            raise RuntimeError(f"Video file not found at: {self.job.video_path}")

        logger.generation("Uploading to YouTube vault...")
        from scripts.youtube_manager import upload_to_youtube_vault, get_or_create_playlist
        metadata = json.loads(self.job.metadata) if self.job.metadata else {}

        success, video_id = upload_to_youtube_vault(self.youtube, self.job.video_path, self.job.topic, metadata, self.job.niche)
        
        if not success or not video_id:
            raise RuntimeError("YouTube vault upload failed — no video_id returned.")

        self.job.youtube_id = video_id
        vault_id = get_or_create_playlist(self.youtube, "Vault Backup")

        self._transition_to(JobState.VAULTED)
        notify_vault_secure(self.job.topic, video_id, vault_id or "unknown")

        script_data = json.loads(self.job.script) if self.job.script else {}
        notify_production_success(
            niche=self.job.niche,
            topic=self.job.topic,
            script=script_data.get("text", ""),
            script_ai=script_data.get("provider", "Unknown"),
            seo_ai="Gemini/Groq",
            voice_ai=script_data.get("target_voice", "am_adam"),
            visual_ai="4-Tier Cascade",
            metadata=metadata,
            duration=self.final_duration,
            size=self.final_size_mb
        )
