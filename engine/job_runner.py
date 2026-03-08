# engine/job_runner.py
import os
import time
import traceback
import json
from datetime import datetime
from engine.logger import logger
from engine.models import VideoJob, JobState, FailureLog
from engine.database import db

# Import existing V4.2 scripts
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.generate_visuals import fetch_scene_images
from scripts.render_video import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.discord_notifier import notify_step, notify_production_success  # 🚨 RESTORED

class JobRunner:
    def __init__(self, job: VideoJob):
        self.job = job
        self.max_attempts = 3
        self.base_filename = f"job_{self.job.id}_{self.job.channel_id}"

    def process(self):
        """Advances the job through the state machine. Safe to interrupt at any point."""
        logger.engine(f"Processing Job {self.job.id} for {self.job.channel_id} | Current State: {self.job.state.name}")

        try:
            if self.job.state == JobState.QUEUED:
                self._transition_to(JobState.SCRIPT_GENERATION)

            if self.job.state == JobState.SCRIPT_GENERATION:
                self._execute_script_generation()

            if self.job.state == JobState.VOICE_GENERATION:
                self._execute_voice_generation()

            if self.job.state == JobState.VISUAL_GENERATION:
                self._execute_visual_generation()

            if self.job.state == JobState.RENDERING:
                self._execute_rendering()

            if self.job.state == JobState.VAULTED:
                logger.success(f"Job {self.job.id} is fully rendered and vaulted. Awaiting Publisher.")

        except Exception as e:
            self._handle_failure(str(e), traceback.format_exc())

    def _transition_to(self, new_state: JobState):
        self.job.state = new_state
        self.job.updated_at = datetime.utcnow().isoformat()
        db.upsert_job(self.job)
        logger.engine(f"Job {self.job.id} transitioned to -> {new_state.name}")

    def _handle_failure(self, error_msg: str, trace: str):
        self.job.attempts += 1
        logger.error(f"Job {self.job.id} failed at {self.job.state.name} (Attempt {self.job.attempts}/{self.max_attempts}): {error_msg}")
        
        db.log_failure(FailureLog(
            job_id=self.job.id,
            channel_id=self.job.channel_id,
            module=self.job.state.name,
            error_message=trace
        ))

        if self.job.attempts >= self.max_attempts:
            self._transition_to(JobState.FAILED)
            logger.error(f"Job {self.job.id} permanently quarantined.")
            notify_step(self.job.topic, "Quarantined", "Topic failed 3 times. Permanently removed from queue.", 0x000000)
        else:
            db.upsert_job(self.job)
            time.sleep(10) 

    def _execute_script_generation(self):
        logger.generation("Executing Script Generation...")
        notify_step(self.job.topic, "Drafting Script", "Asking AI for narrative constraints...", 0x95a5a6)
        
        script_text, image_prompts, pexels_queries, scene_weights, prov = generate_script(self.job.niche, self.job.topic)
        
        if not script_text:
            raise ValueError("Script Generation returned empty payload.")

        metadata, _ = generate_seo_metadata(self.job.niche, script_text)

        self.job.script = json.dumps({
            "text": script_text,
            "image_prompts": image_prompts,
            "pexels_queries": pexels_queries,
            "scene_weights": scene_weights,
            "provider": prov
        })
        self.job.metadata = metadata
        self._transition_to(JobState.VOICE_GENERATION)

    def _execute_voice_generation(self):
        logger.generation("Executing Voice Generation...")
        notify_step(self.job.topic, "Voice Generation", "Synthesizing ultra-realistic audio...", 0x3498db)
        
        script_data = json.loads(self.job.script)
        audio_base = f"temp_audio_{self.base_filename}"
        
        success, prov, duration = generate_audio(script_data["text"], output_base=audio_base)
        if not success:
            raise RuntimeError("Voice Generation Pipeline Failed.")
            
        self.job.audio_path = f"{audio_base}.wav"
        
        if not self.job.metadata: self.job.metadata = {}
        self.job.metadata["voice_provider"] = prov
        self.job.metadata["video_duration"] = duration
        
        self._transition_to(JobState.VISUAL_GENERATION)

    def _execute_visual_generation(self):
        logger.generation("Executing Visual Generation...")
        notify_step(self.job.topic, "Visual Generation", "Sourcing 4-Tier cascade images...", 0x3498db)
        
        script_data = json.loads(self.job.script)
        
        paths, prov = fetch_scene_images(
            script_data["image_prompts"], 
            script_data["pexels_queries"], 
            base_filename=f"temp_scene_{self.base_filename}"
        )
        
        if len(paths) < len(script_data["image_prompts"]):
            raise RuntimeError(f"Visual Desync: Got {len(paths)}/{len(script_data['image_prompts'])} images.")

        self.job.image_paths = paths
        self.job.metadata["visual_provider"] = prov
        
        self._transition_to(JobState.RENDERING)

    def _execute_rendering(self):
        logger.render("Executing FFmpeg Master Render...")
        notify_step(self.job.topic, "Rendering", "Compiling Video via FFmpeg...", 0x9b59b6)
        
        script_data = json.loads(self.job.script)
        final_out = f"final_{self.base_filename}.mp4"
        
        success, duration, size = render_video(
            self.job.image_paths, 
            self.job.audio_path, 
            final_out, 
            scene_weights=script_data["scene_weights"], 
            watermark_text=self.job.channel_id 
        )
        
        if not success:
            raise RuntimeError("FFmpeg rendering collapsed.")

        self.job.video_path = final_out
        self.job.metadata["video_size"] = size
        
        # 🚨 RESTORED: Send the final Discord embed with the full video details!
        is_test = os.environ.get("TEST_MODE", "False") == "True"
        notify_production_success(
            niche=self.job.niche,
            topic=self.job.topic,
            script=script_data["text"],
            script_ai=script_data.get("provider", "Unknown"),
            seo_ai="V5 Engine",
            voice_ai=self.job.metadata.get("voice_provider", "Kokoro"),
            visual_ai=self.job.metadata.get("visual_provider", "Cascade"),
            metadata=self.job.metadata,
            duration=duration,
            size=size,
            status="Rendered & Verified (Test Mode)" if is_test else "Rendered Successfully"
        )
        
        self._transition_to(JobState.VAULTED)
