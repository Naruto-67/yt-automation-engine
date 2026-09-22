# engine/job_runner.py
import os
import time
import shutil
import traceback
import json
from datetime import datetime, timezone
from engine.logger import logger, print_phase_box
from engine.models import VideoJob, JobState, FailureLog
from engine.database import db
from engine.context import ctx

from scripts.generate_script   import generate_script
from scripts.generate_voice    import generate_audio
from scripts.generate_visuals  import fetch_scene_images
from scripts.render_video      import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.generate_thumbnail import generate_thumbnail, upload_thumbnail
from scripts.discord_notifier  import notify_step, notify_production_success, notify_vault_secure, notify_stage_progress
from engine.self_learning      import self_learning
from engine.decision_log       import decision_log
from engine.delivery_promise   import get_delivery_promise



class JobRunner:
    def __init__(self, job: VideoJob, youtube_client=None, channel_name: str = "",
                 channel_config=None, dry_run: bool = False):
        self.job            = job
        self.youtube        = youtube_client
        self.channel_name   = channel_name or job.channel_id
        self.channel_config = channel_config   # ChannelConfig — used for category_id, language etc.
        self.dry_run        = dry_run          # True in is_test_mode() — no DB reads/writes
        self.max_attempts   = 3
        self.base_filename  = f"job_{job.id}_{job.channel_id.replace(' ', '_')}"
        self.final_duration = 0.0
        self.final_size_mb  = 0.0

    def process(self) -> bool:
        ctx.set_channel_id(self.job.channel_id)
        from scripts.discord_notifier import set_channel_context
        if self.channel_config:
            set_channel_context(self.channel_config)
            
        logger.engine(
            f"Processing Job {self.job.id} | Topic: {self.job.topic} | "
            f"State: {self.job.state.name}"
            + (" [DRY RUN — no DB writes]" if self.dry_run else "")
        )

        try:
            if self.job.state in [JobState.VISUAL_GENERATION, JobState.RENDERING]:
                if not self.job.audio_path or not os.path.exists(self.job.audio_path):
                    logger.engine(f"⚠️ [RECOVERY] Job {self.job.id} physical audio missing. Rewinding to VOICE_GENERATION...")
                    self._transition_to(JobState.VOICE_GENERATION)

            if self.job.state == JobState.RENDERING:
                paths = json.loads(self.job.image_paths) if self.job.image_paths else []
                if not paths or not all(os.path.exists(p) for p in paths):
                    logger.engine(f"⚠️ [RECOVERY] Job {self.job.id} physical images missing. Rewinding to VISUAL_GENERATION...")
                    self._transition_to(JobState.VISUAL_GENERATION)

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
                try:
                    notify_stage_progress("VAULT_COMPLETE", {
                        "topic": self.job.topic,
                        "duration": getattr(self, "final_duration", 0.0),
                    })
                except Exception:
                    pass

        except Exception as e:
            trace = traceback.format_exc()
            print(f"\n🚨 [CRITICAL ERROR] JobRunner crashed on topic '{self.job.topic}':")
            print(f"└ Exact Exception: {type(e).__name__}: {e}")
            print(f"└ Traceback:\n{trace}\n")
            self._handle_failure(str(e), trace)

        return self.job.state == JobState.VAULTED

    def _transition_to(self, new_state: JobState):
        self.job.state      = new_state
        self.job.updated_at = datetime.now(timezone.utc).isoformat()
        # ── DRY RUN GUARD: no DB writes in test mode ──────────────────────────
        if not self.dry_run:
            db.upsert_job(self.job)
        logger.engine(f"Job {self.job.id} → {new_state.name}")

    def _handle_failure(self, error_msg: str, trace: str):
        self.job.attempts += 1
        # ── DRY RUN GUARD: no DB writes in test mode ──────────────────────────
        if not self.dry_run:
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
            # Only persist attempt count to DB in production mode
            if not self.dry_run:
                db.upsert_job(self.job)
            time.sleep(5)

    def _execute_script_generation(self):
        print_phase_box(3, "Script Generation & AI Routing", self.job.channel_id)
        logger.generation("Drafting script...")
        try:
            notify_stage_progress("SCRIPT_STARTED", {"topic": self.job.topic})
        except Exception:
            pass
        # generate_script now returns a 9-tuple including mood and caption_style
        (
            script_text, prompts, pexels, weights, prov,
            voice, glow_color, mood, caption_style
        ) = generate_script(self.job.niche, self.job.topic)

        if not script_text:
            raise ValueError("Empty script returned from generator.")

        try:
            meta_data, seo_prov = generate_seo_metadata(self.job.niche, script_text, channel_config=self.channel_config)
            meta_data["_seo_ai"] = seo_prov
        except Exception as e:
            logger.error(f"SEO Generation failed: {e}. Using fallback metadata.")
            meta_data = {
                "title":       f"{self.job.niche} #shorts"[:95],
                "description": "Mind blowing facts!",
                "tags":        ["shorts", self.job.niche],
                "_seo_ai":     "Fallback",
            }

        # ── P2.3: Emotion-to-Palette Calibrator ──────────────────────────────
        content_type = getattr(self.channel_config, "content_type", "factual") if self.channel_config else "factual"
        from engine.palette_engine import palette_engine
        palette = palette_engine.calibrate_palette(mood=mood, content_type=content_type)

        self.job.script = json.dumps({
            "text":          script_text,
            "prompts":       prompts,
            "pexels":        pexels,
            "weights":       weights,
            "provider":      prov,
            "target_voice":  voice,
            "glow_color":    glow_color,    # caption neon halo color (ASS &HAABBGGRR)
            "mood":          mood,          # emotional register for voice + music + watermark
            "caption_style": caption_style, # visual subtitle preset key
            "palette":       palette,       # calibrated palette for styling
        })
        self.job.metadata = json.dumps(meta_data)

        # ── P2.4: Episodic Memory Logging ────────────────────────────────────
        try:
            from engine.episodic_memory import episodic_memory
            import re
            sentences = [s.strip() for s in re.split(r'[.!?]+', script_text) if s.strip()]
            hook_s = sentences[0] if sentences else ""
            episodic_memory.log_video(
                channel_id=self.job.channel_id,
                topic=self.job.topic,
                hook=hook_s,
                script_summary=script_text[:300],
                quality_score=7.0,
                critic_scores=palette or {},
                metadata=meta_data,
            )
            from engine.knowledge_graph import knowledge_graph
            knowledge_graph.add_covered(
                channel_id=self.job.channel_id,
                topic=self.job.topic,
                pillar=meta_data.get("pillar") or "general"
            )
        except Exception as em_err:
            logger.debug(f"Episodic memory / KG logging skipped: {em_err}")

        try:
            notify_stage_progress("SCRIPT_LOCKED", {
                "topic": self.job.topic,
                "word_count": len(script_text.split()),
                "provider": prov,
                "voice": voice,
            })
        except Exception:
            pass

        self._transition_to(JobState.VOICE_GENERATION)

    def _execute_voice_generation(self):
        script_data  = json.loads(self.job.script)
        audio_base   = f"temp_audio_{self.base_filename}"
        target_voice = script_data.get("target_voice", "am_adam")
        mood         = script_data.get("mood", "neutral")
        print_phase_box(4, "Voice Synthesis & Timing Calibration", self.job.channel_id)
        logger.generation("Synthesizing audio...")
        try:
            notify_stage_progress("VOICE_STARTED", {"topic": self.job.topic, "voice": target_voice})
        except Exception:
            pass

        channel_lang = getattr(self.channel_config, "language", "en") if self.channel_config else "en"
        channel_tts_locale = getattr(self.channel_config, "tts_locale", "en-US") if self.channel_config else "en-US"

        success, prov, duration = generate_audio(
            script_data["text"],
            output_base=audio_base,
            target_voice=target_voice,
            mood=mood,               # ← emotion injection based on mood
            tts_locale=channel_tts_locale,
            language=channel_lang,
        )
        if not success:
            raise RuntimeError("TTS pipeline collapsed — all providers failed.")

        self.job.audio_path = f"{audio_base}.wav"
        self._transition_to(JobState.VISUAL_GENERATION)

    def _execute_visual_generation(self):
        script_data = json.loads(self.job.script)
        prompts     = script_data.get("prompts", [])
        pexels      = script_data.get("pexels",  [])

        if not prompts:
            raise ValueError("No image prompts available in script data.")

        content_type = getattr(self.channel_config, "content_type", "factual") if self.channel_config else "factual"
        print_phase_box(5, "Visual Sourcing & Master Video Rendering", self.job.channel_id)
        logger.generation("Sourcing scene images...")
        try:
            notify_stage_progress("VISUALS_STARTED", {"topic": self.job.topic})
        except Exception:
            pass

        images, provider = fetch_scene_images(
            prompts,
            pexels,
            base_filename=f"temp_scene_{self.base_filename}",
            content_type=content_type,
            channel_id=self.job.channel_id,
        )
        self._visual_provider = provider
        min_acceptable = max(1, len(prompts) // 2)

        if len(images) < min_acceptable:
            raise RuntimeError(
                f"Visual generation critically failed: {len(images)}/{len(prompts)} images. "
                f"Last provider: {provider}"
            )

        while len(images) < len(prompts):
            images.append(images[-1])

        self.job.image_paths = json.dumps(images)
        self._transition_to(JobState.RENDERING)


    def _execute_rendering(self):
        script_data = json.loads(self.job.script)
        images      = json.loads(self.job.image_paths)
        weights     = script_data.get("weights", [])

        # Resolve glow_color — accept legacy 'target_color' key from old jobs
        # so that any QUEUED/RENDERING jobs created before this update still work.
        glow_color = (
            script_data.get("glow_color")
            or script_data.get("target_color")
            or None
        )

        # mood and caption_style — both .get() with safe defaults so old jobs
        # that predate these fields still render correctly using base style.
        mood          = script_data.get("mood",          "neutral")
        caption_style = script_data.get("caption_style", None)
        palette       = script_data.get("palette",       None)

        logger.generation("Rendering final video...")
        try:
            notify_stage_progress("RENDER_STARTED", {"topic": self.job.topic})
        except Exception:
            pass

        scene_count = len(images)
        required_gb = max(2.0, (scene_count * 0.3) + 0.5)
        free_gb     = shutil.disk_usage("/").free / (1024 ** 3)
        if free_gb < required_gb:
            raise RuntimeError(
                f"Disk space too low: {free_gb:.1f} GB free, need {required_gb:.1f} GB."
            )

        output_path = f"final_{self.base_filename}.mp4"
        watermark   = self.channel_name or self.job.channel_id

        success, duration, size_mb = render_video(
            image_paths=images,
            audio_path=self.job.audio_path,
            output_path=output_path,
            scene_weights=weights,
            watermark_text=watermark,
            glow_color=glow_color,
            mood=mood,               # ← dynamic watermark + background music
            caption_style=caption_style,  # ← dynamic caption style preset
            palette=palette,         # ← calibrated styling palette
        )

        if not success:
            raise RuntimeError("FFmpeg render failed — output not produced.")

        self.final_duration = duration
        self.final_size_mb  = size_mb
        self.job.video_path = output_path

        logger.success(f"Rendered: {output_path} ({size_mb:.1f} MB, {duration:.1f}s)")
        notify_step(self.job.topic, "RENDERED", f"Size: {size_mb:.1f} MB | Duration: {duration:.1f}s", 0x9b59b6)

        # ── Thumbnail generation (non-fatal) ──────────────────────────────────
        try:
            images   = json.loads(self.job.image_paths) if self.job.image_paths else []
            metadata = json.loads(self.job.metadata)    if self.job.metadata    else {}
            title    = metadata.get("title", self.job.topic)
            thumb_path = f"thumbnail_{self.base_filename}.jpg"
            self._thumbnail_path = generate_thumbnail(images, title, output_path=thumb_path)
        except Exception:
            self._thumbnail_path = None

        self._execute_upload()

    def _execute_upload(self):
        print_phase_box(6, "Vaulting, Memory Sync & Discord Reporting", self.job.channel_id)
        metadata    = json.loads(self.job.metadata)    if self.job.metadata else {}
        script_data = json.loads(self.job.script)      if self.job.script   else {}

        self._record_success_in_learning_engine(script_data)

        script_ai = script_data.get("provider", "Unknown AI")
        seo_ai = metadata.get("_seo_ai", "Gemini/Groq")
        visual_ai = getattr(self, "_visual_provider", "Visual Cascade")

        if is_test_mode():
            logger.success("🧪 [TEST MODE] Bypassing YouTube Upload. Simulating success.")
            self.job.youtube_id = "test_mode_dummy_video_id"
            # ── DRY RUN GUARD: _transition_to handles the DB write guard internally ──
            self._transition_to(JobState.VAULTED)
            notify_vault_secure(self.job.topic, self.job.youtube_id, "Test_Playlist_ID")

            notify_production_success(
                niche=self.job.niche, topic=self.job.topic,
                script=script_data.get("text", ""),
                script_ai=script_ai, seo_ai=seo_ai,
                voice_ai=script_data.get("target_voice", "am_adam"), visual_ai=visual_ai,
                metadata=metadata, duration=self.final_duration, size=self.final_size_mb,
                video_id=self.job.youtube_id
            )
            return

        if not self.youtube:
            raise RuntimeError("No YouTube client available for upload.")
        if not self.job.video_path or not os.path.exists(self.job.video_path):
            raise RuntimeError(f"Video file not found at: {self.job.video_path}")

        logger.generation("Uploading to YouTube vault...")
        from scripts.youtube_manager import upload_to_youtube_vault, get_or_create_playlist

        success, video_id_or_error = upload_to_youtube_vault(
            self.youtube, self.job.video_path, self.job.topic, metadata,
            self.job.niche, channel_config=self.channel_config
        )
        if not success:
            raise RuntimeError(f"YouTube vault upload API failed: {video_id_or_error}")

        self.job.youtube_id = video_id_or_error
        vault_id            = get_or_create_playlist(self.youtube, "Vault Backup")

        self._transition_to(JobState.VAULTED)
        notify_vault_secure(self.job.topic, self.job.youtube_id, vault_id or "unknown")

        # ── Thumbnail upload (non-fatal) ──────────────────────────────────────
        # Tries to set a custom thumbnail. Requires youtube.force-ssl scope OR
        # channel verification (10K+ lifetime views). Fails silently if missing.
        thumbnail_path = getattr(self, "_thumbnail_path", None)
        if thumbnail_path:
            upload_thumbnail(self.youtube, self.job.youtube_id, thumbnail_path)

        try:
            if os.path.exists(self.job.video_path) and not os.environ.get("GITHUB_ACTIONS"):
                os.remove(self.job.video_path)
        except Exception:
            pass

        notify_production_success(
            niche=self.job.niche, topic=self.job.topic,
            script=script_data.get("text", ""),
            script_ai=script_ai, seo_ai=seo_ai,
            voice_ai=script_data.get("target_voice", "am_adam"), visual_ai=visual_ai,
            metadata=metadata, duration=self.final_duration, size=self.final_size_mb,
            video_id=self.job.youtube_id
        )

    def _record_success_in_learning_engine(self, script_data: dict):
        """Persist successful execution to self-learning memory and decision log."""
        from engine.context import is_test_mode
        if self.dry_run or is_test_mode():
            logger.engine("🧪 [TEST MODE] Bypassing self-learning and decision log updates.")
            return

        try:
            content_type = getattr(self.channel_config, "content_type", "factual") if self.channel_config else "factual"
            pillar = getattr(self.channel_config, "primary_pillar", "default") if self.channel_config else "default"
            visual_style = getattr(self.channel_config, "visual_style", "cinematic") if self.channel_config else "cinematic"

            self_learning.record_successful_trajectory(
                channel_id=self.job.channel_id,
                topic=self.job.topic,
                script_text=script_data.get("text", ""),
                scenes=script_data.get("scenes", []),
                content_type=content_type,
                pillar=pillar,
                performance_score=8.5,
                visual_style=visual_style,
            )
            decision_log.record(
                category="PRODUCTION_CYCLE",
                decision="Completed full video pipeline and saved trajectory",
                chosen=self.job.youtube_id or "vaulted",
                channel_id=self.job.channel_id,
                job_id=self.job.id,
                extra={"topic": self.job.topic, "duration": self.final_duration, "size_mb": self.final_size_mb},
            )
        except Exception as e:
            logger.debug(f"Self-learning record failed (non-fatal): {e}")



