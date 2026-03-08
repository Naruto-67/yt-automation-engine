# engine/job_runner.py
import os
import time
import traceback
import json
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
        self.job = job
        self.max_attempts = 3
        self.base_filename = f"job_{self.job.id}_{self.job.channel_id.replace(' ', '_')}"

    def process(self):
        # 🚨 V5 CONTEXT INJECTION: Used by Guardian and DB fetchers down the stack.
        os.environ["CURRENT_CHANNEL_ID"] = self.job.channel_id
        
        logger.engine(f"Processing Job {self.job.id} | Topic: {self.job.topic} | State: {self.job.state.name}")

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
                if self.job.image_paths and all(os.path.exists(p) for p in json.loads(self.job.image_paths)):
                    self._transition_to(JobState.RENDERING)
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
        self.job.state = new_state
        self.job.updated_at = datetime.utcnow().isoformat()
        db.upsert_job(self.job)
        logger.engine(f"Job {self.job.id} -> {new_state.name}")

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
        script_text, prompts, pexels, weights, prov = generate_script(self.job.niche, self.job.topic)
        if not script_text: raise ValueError("Empty script returned.")

        meta_data, _ = generate_seo_metadata(self.job.niche, script_text)
        self.job.script = json.dumps({"text": script_text, "prompts": prompts, "pexels": pexels, "weights": weights, "provider": prov})
        self.job.metadata = json.dumps(meta_data)
        self._transition_to(JobState.VOICE_GENERATION)

    def _execute_voice_generation(self):
        logger.generation("Synthesizing audio...")
        script_data = json.loads(self.job.script)
        audio_base = f"temp_audio_{self.base_filename}"
        
        success, prov, duration = generate_audio(script_data["text"], output_base=audio_base)
        if not success: raise RuntimeError("TTS Pipeline collapsed.")
            
        self.job.audio_path = f"{audio_base}.wav"
        self._transition_to(JobState.VISUAL_GENERATION)

    def _execute_visual_generation(self):
        logger.generation("Generating visual assets...")
        script_data = json.loads(self.job.script)
        
        paths, prov = fetch_scene_images(script_data["prompts"], script_data["pexels"], base_filename=f"temp_vis_{self.base_filename}")
        if len(paths) < len(script_data["prompts"]): raise RuntimeError(f"Visual Desync.")

        self.job.image_paths = json.dumps(paths)
        self._transition_to(JobState.RENDERING)

    def _execute_rendering(self):
        logger.render("Final FFmpeg composite...")
        script_data = json.loads(self.job.script)
        img_paths = json.loads(self.job.image_paths)
        final_out = f"final_{self.base_filename}.mp4"
        
        success, duration, size = render_video(img_paths, self.job.audio_path, final_out, scene_weights=script_data["weights"], watermark_text=self.job.channel_id)
        if not success: raise RuntimeError("FFmpeg render failed.")

        self.job.video_path = final_out
        notify_production_success(
            niche=self.job.niche, topic=self.job.topic, script=script_data["text"], script_ai=script_data["provider"], seo_ai="V5 Engine",
            voice_ai="Kokoro", visual_ai="Cascade", metadata=json.loads(self.job.metadata), duration=duration, size=size
        )
        self._transition_to(JobState.VAULTED)
