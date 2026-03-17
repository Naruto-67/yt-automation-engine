# engine/job_runner.py
# Ghost Engine V26.0.0 — Pipeline Orchestration & Creative Data Flow
import os
import time
import shutil
import traceback
import json
from datetime import datetime
from engine.logger import logger
from engine.models import VideoJob, JobState, FailureLog
from engine.database import db
from engine.context import ctx

from scripts.generate_script   import generate_script
from scripts.generate_voice    import generate_audio
from scripts.generate_visuals  import fetch_scene_images
from scripts.render_video      import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.discord_notifier  import notify_step, notify_production_success, notify_vault_secure

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


class JobRunner:
    def __init__(self, job: VideoJob, youtube_client=None, channel_name: str = "", channel_config=None):
        self.job            = job
        self.youtube        = youtube_client
        self.channel_name   = channel_name or job.channel_id
        self.channel_config = channel_config   # ChannelConfig — contains personality and niche metadata
        self.max_attempts   = 3
        self.base_filename  = f"job_{job.id}_{job.channel_id.replace(' ', '_')}"
        self.final_duration = 0.0
        self.final_size_mb  = 0.0

    def process(self) -> bool:
        ctx.set_channel_id(self.job.channel_id)
        logger.engine(f"Processing Job {self.job.id} | Topic: {self.job.topic} | State: {self.job.state.name}")

        try:
            # Recovery logic for interrupted jobs [cite: 159-161]
            if self.job.state in [JobState.VISUAL_GENERATION, JobState.RENDERING]:
                if not self.job.audio_path or not os.path.exists(self.job.audio_path):
                    logger.engine(f"⚠️ [RECOVERY] Job {self.job.id} physical audio missing. Rewinding...")
                    self._transition_to(JobState.VOICE_GENERATION)

            if self.job.state == JobState.RENDERING:
                paths = json.loads(self.job.image_paths) if self.job.image_paths else []
                if not paths or not all(os.path.exists(p) for p in paths):
                    logger.engine(f"⚠️ [RECOVERY] Job {self.job.id} physical images missing. Rewinding...")
                    self._transition_to(JobState.VISUAL_GENERATION)

            # Standard pipeline flow [cite: 161-165]
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
            trace = traceback.format_exc()
            self._handle_failure(str(e), trace)

        return self.job.state == JobState.VAULTED

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
        from engine.guardian import guardian
        guardian.report_incident(self.job.state.name, error_msg)

        if self.job.attempts >= self.max_attempts:
            self._transition_to(JobState.FAILED)
            notify_step(self.job.topic, "FAILED", f"Critical crash after {self.max_attempts} attempts.", 0xe74c3c)
        else:
            db.upsert_job(self.job)
            time.sleep(5)

    def _execute_script_generation(self):
        logger.generation("Drafting V26 Humanized Script...")
        # V26: Passing personality from channel config and handling rich metadata [cite: 169-173]
        script_text, prompts, pexels, weights, prov, meta = generate_script(
            self.job.niche, self.job.topic, personality=self.channel_config.personality
        )
        if not script_text:
            raise ValueError("Empty script returned from generator.")

        try:
            meta_data, _ = generate_seo_metadata(self.job.niche, script_text)
        except Exception as e:
            logger.error(f"SEO Generation failed: {e}. Using fallback metadata.")
            meta_data = {
                "title":       f"{self.job.niche} #shorts"[:95],
                "description": "Amazing Facts!",
                "tags":        ["shorts", self.job.niche],
            }

        # V26: Store all creative metadata in the job script field [cite: 172-173]
        self.job.script = json.dumps({
            "text":          script_text,
            "prompts":       prompts,
            "pexels":        pexels,
            "weights":       weights,
            "provider":      prov,
            "target_voice":  meta.get("voice_actor", "am_adam"),
            "glow_color":    meta.get("glow_color", "&H0000D700"),
            "mood":          meta.get("mood", "NEUTRAL"),
            "music_tag":     meta.get("music_tag", "upbeat_curiosity"),
            "caption_style": meta.get("caption_style", "NEON_HORNET")
        })
        self.job.metadata = json.dumps(meta_data)
        self._transition_to(JobState.VOICE_GENERATION)

    def _execute_voice_generation(self):
        logger.generation("Synthesizing V26 Prosody Audio...")
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
        logger.generation("Sourcing scene visuals...")
        script_data = json.loads(self.job.script)
        prompts     = script_data.get("prompts", [])
        pexels      = script_data.get("pexels",  [])

        if not prompts:
            raise ValueError("No image prompts available.")

        images, provider = fetch_scene_images(prompts, pexels, base_filename=f"temp_scene_{self.base_filename}")
        min_acceptable = max(1, len(prompts) // 2)

        if len(images) < min_acceptable:
            raise RuntimeError(f"Visual generation failed: {len(images)}/{len(prompts)} images.")

        while len(images) < len(prompts):
            images.append(images[-1])

        self.job.image_paths = json.dumps(images)
        self._transition_to(JobState.RENDERING)

    def _execute_rendering(self):
        logger.generation("Rendering V26 Multi-Layer Video...")
        script_data = json.loads(self.job.script)
        images      = json.loads(self.job.image_paths)
        weights     = script_data.get("weights", [])

        # V26: Extracting dynamic creative metadata for the renderer [cite: 178-181]
        glow_color    = script_data.get("glow_color")
        mood          = script_data.get("mood")
        music_tag     = script_data.get("music_tag")
        caption_style = script_data.get("caption_style")

        scene_count = len(images)
        required_gb = max(2.0, (scene_count * 0.3) + 0.5)
        free_gb     = shutil.disk_usage("/").free / (1024 ** 3)
        if free_gb < required_gb:
            raise RuntimeError(f"Disk space too low: {free_gb:.1f} GB free.")

        output_path = f"final_{self.base_filename}.mp4"
        watermark   = self.channel_name or self.job.channel_id

        # Passing new creative parameters to render_video (to be updated in Step 3)
        success, duration, size_mb = render_video(
            image_paths=images,
            audio_path=self.job.audio_path,
            output_path=output_path,
            scene_weights=weights,
            watermark_text=watermark,
            glow_color=glow_color,
            # V26: New mood and music parameters for the Step 3 mixer
            mood=mood,
            music_tag=music_tag,
            caption_style=caption_style
        )

        if not success:
            raise RuntimeError("FFmpeg render failed.")

        self.final_duration = duration
        self.final_size_mb  = size_mb
        self.job.video_path = output_path

        logger.success(f"Rendered: {output_path} ({size_mb:.1f} MB, {duration:.1f}s)")
        notify_step(self.job.topic, "RENDERED", f"Size: {size_mb:.1f} MB | Duration: {duration:.1f}s", 0x9b59b6)

        self._execute_upload()

    def _execute_upload(self):
        metadata    = json.loads(self.job.metadata)    if self.job.metadata else {}
        script_data = json.loads(self.job.script)      if self.job.script   else {}

        if TEST_MODE:
            logger.success("🧪 [TEST MODE] Bypassing Upload.")
            self.job.youtube_id = "test_mode_dummy_video_id"
            self._transition_to(JobState.VAULTED)
            notify_vault_secure(self.job.topic, self.job.youtube_id, "Test_Playlist_ID")
            notify_production_success(
                niche=self.job.niche, topic=self.job.topic,
                script=script_data.get("text", ""),
                script_ai=script_data.get("provider", "Unknown"), seo_ai="Gemini/Groq",
                voice_ai=script_data.get("target_voice", "am_adam"), visual_ai="4-Tier Cascade",
                metadata=metadata, duration=self.final_duration, size=self.final_size_mb,
                video_id=self.job.youtube_id
            )
            return

        if not self.youtube:
            raise RuntimeError("No YouTube client available.")
        if not self.job.video_path or not os.path.exists(self.job.video_path):
            raise RuntimeError(f"Video file not found at: {self.job.video_path}")

        logger.generation("Uploading to YouTube vault...")
        from scripts.youtube_manager import upload_to_youtube_vault, get_or_create_playlist

        success, video_id_or_error = upload_to_youtube_vault(
            self.youtube, self.job.video_path, self.job.topic, metadata,
            self.job.niche, channel_config=self.channel_config
        )
        if not success:
            raise RuntimeError(f"YouTube upload failed: {video_id_or_error}")

        self.job.youtube_id = video_id_or_error
        vault_id            = get_or_create_playlist(self.youtube, "Vault Backup")

        self._transition_to(JobState.VAULTED)
        notify_vault_secure(self.job.topic, self.job.youtube_id, vault_id or "unknown")

        try:
            if os.path.exists(self.job.video_path) and not os.environ.get("GITHUB_ACTIONS"):
                os.remove(self.job.video_path)
        except Exception:
            pass

        notify_production_success(
            niche=self.job.niche, topic=self.job.topic,
            script=script_data.get("text", ""),
            script_ai=script_data.get("provider", "Unknown"), seo_ai="Gemini/Groq",
            voice_ai=script_data.get("target_voice", "am_adam"), visual_ai="4-Tier Cascade",
            metadata=metadata, duration=self.final_duration, size=self.final_size_mb,
            video_id=self.job.youtube_id
        )
