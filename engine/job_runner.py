# engine/job_runner.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #4 — Accept partial visual success instead of hard-failing the entire job
#
# BUG: _execute_visual_generation raised RuntimeError("Visual Desync") if even
# ONE image failed: `if len(paths) < len(prompts): raise RuntimeError(...)`.
# This is wrong — the 4-tier cascade already has a gradient fallback, but if
# all 4 tiers failed for a single scene (e.g. Pexels rate-limited AND gradient
# errored), the entire job crashed and retried from scratch, including
# re-generating voice and re-running the script (wasting API calls and time).
#
# FIX: Accept partial success if ≥ 50% of scenes produced an image. Missing
# scenes get padded by duplicating the last successful image. This matches
# real behaviour — a 5-scene video with one broken image is still publishable,
# and a gradient duplicate is better than a wasted Gemini call + full retry.
#
# The 50% threshold is conservative. Even 1 image for a 1-scene video works.
# The pad logic always ensures render_video() receives exactly the expected
# number of paths — no downstream changes needed.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import time
import json
import traceback
from datetime import datetime
from engine.logger import logger
from engine.models import VideoJob, JobState, FailureLog
from engine.database import db

from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.generate_visuals import fetch_scene_images
from scripts.render_video import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.discord_notifier import notify_step, notify_production_success


class JobRunner:
    def __init__(self, job: VideoJob):
        self.job           = job
        self.max_attempts  = 3
        self.base_filename = f"job_{self.job.id}_{self.job.channel_id.replace(' ', '_')}"

    def process(self):
        os.environ["CURRENT_CHANNEL_ID"] = self.job.channel_id
        logger.engine(
            f"Processing Job {self.job.id} | Topic: {self.job.topic} | State: {self.job.state.name}"
        )

        try:
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
                if self.job.image_paths:
                    existing = json.loads(self.job.image_paths)
                    if existing and all(os.path.exists(p) for p in existing):
                        self._transition_to(JobState.RENDERING)
                    else:
                        self._execute_visual_generation()
                else:
                    self._execute_visual_generation()

            if self.job.state == JobState.RENDERING:
                if self.job.video_path and os.path.exists(self.job.video_path):
                    self._transition_to(JobState.VAULTED)
                else:
                    self._execute_rendering()

            if self.job.state == JobState.VAULTED:
                logger.success(f"Job {self.job.id} ready for YouTube Vault.")

        except Exception as e:
            self._handle_failure(str(e), traceback.format_exc())

    def _transition_to(self, new_state: JobState):
        self.job.state      = new_state
        self.job.updated_at = datetime.utcnow().isoformat()
        db.upsert_job(self.job)
        logger.engine(f"Job {self.job.id} -> {new_state.name}")

    def _handle_failure(self, error_msg: str, trace: str):
        self.job.attempts += 1
        db.log_failure(FailureLog(
            job_id=self.job.id, channel_id=self.job.channel_id,
            module=self.job.state.name, error_message=error_msg, traceback=trace,
        ))
        if self.job.attempts >= self.max_attempts:
            self._transition_to(JobState.FAILED)
            notify_step(
                self.job.topic, "FAILED",
                f"Critical crash after {self.max_attempts} attempts.", 0xe74c3c,
            )
        else:
            db.upsert_job(self.job)
            time.sleep(5)

    def _execute_script_generation(self):
        logger.generation("Drafting script...")
        script_text, prompts, pexels, weights, prov, voice, color = generate_script(
            self.job.niche, self.job.topic
        )
        if not script_text:
            raise ValueError("Empty script returned.")

        meta_data, _ = generate_seo_metadata(self.job.niche, script_text)
        self.job.script = json.dumps({
            "text": script_text, "prompts": prompts, "pexels": pexels,
            "weights": weights, "provider": prov,
            "target_voice": voice, "target_color": color,
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
            raise RuntimeError("TTS Pipeline collapsed.")

        self.job.audio_path = f"{audio_base}.wav"
        self._transition_to(JobState.VISUAL_GENERATION)

    def _execute_visual_generation(self):
        logger.generation("Generating visual assets...")
        script_data     = json.loads(self.job.script)
        expected_count  = len(script_data["prompts"])

        paths, prov = fetch_scene_images(
            script_data["prompts"],
            script_data["pexels"],
            base_filename=f"temp_vis_{self.base_filename}",
        )

        # ── FIX #4: Accept partial success (≥ 50%) instead of hard-failing ──
        # The old code crashed if even 1 image was missing. Now we pad missing
        # scenes by duplicating the last successful image so the render can
        # proceed. A 5-scene video with one duplicate is still publishable.
        if not paths:
            # Zero images returned — nothing we can do, let the retry handle it
            raise RuntimeError(
                f"Visual generation produced 0 images for {expected_count} scenes. "
                f"All 4 provider tiers failed."
            )

        min_acceptable = max(1, expected_count // 2)  # 50% floor, minimum 1
        if len(paths) < min_acceptable:
            raise RuntimeError(
                f"Visual generation too sparse: got {len(paths)}/{expected_count} images "
                f"(minimum acceptable: {min_acceptable}). Retrying."
            )

        # Pad to the expected count by repeating the last successful image
        if len(paths) < expected_count:
            shortage = expected_count - len(paths)
            pad_image = paths[-1]  # Duplicate last successful image
            paths.extend([pad_image] * shortage)
            logger.engine(
                f"⚠️ Visual padding: duplicated '{os.path.basename(pad_image)}' "
                f"x{shortage} to fill {expected_count} scenes (provider: {prov})"
            )
        # ─────────────────────────────────────────────────────────────────────

        self.job.image_paths = json.dumps(paths)
        self._transition_to(JobState.RENDERING)

    def _execute_rendering(self):
        logger.render("Final FFmpeg composite...")
        script_data  = json.loads(self.job.script)
        img_paths    = json.loads(self.job.image_paths)
        target_color = script_data.get("target_color", "&H00FFFFFF")
        final_out    = f"final_{self.base_filename}.mp4"

        success, duration, size = render_video(
            img_paths,
            self.job.audio_path,
            final_out,
            scene_weights=script_data["weights"],
            watermark_text=self.job.channel_id,
            subtitle_color=target_color,
        )
        if not success:
            raise RuntimeError("FFmpeg render failed.")

        self.job.video_path = final_out
        notify_production_success(
            niche=self.job.niche,
            topic=self.job.topic,
            script=script_data["text"],
            script_ai=script_data["provider"],
            seo_ai="V5 Engine",
            voice_ai=f"Kokoro ({script_data.get('target_voice', 'Auto')})",
            visual_ai="Cascade",
            metadata=json.loads(self.job.metadata),
            duration=duration,
            size=size,
        )
        self._transition_to(JobState.VAULTED)
