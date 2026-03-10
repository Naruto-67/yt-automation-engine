# engine/models.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime

class JobState(str, Enum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    SCRIPT_GENERATION = "script_generation"
    VOICE_GENERATION = "voice_generation"
    VISUAL_GENERATION = "visual_generation"
    RENDERING = "rendering"
    VAULTED = "vaulted"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"

class ChannelConfig(BaseModel):
    channel_id: str
    channel_name: str
    niche: str
    target_audience: str
    youtube_refresh_token_env: str
    youtube_client_id_env: str = ""
    youtube_client_secret_env: str = ""
    discord_webhook_env: str = ""
    creative_lenses: List[str] = Field(default_factory=list)

class VideoJob(BaseModel):
    id: Optional[int] = None
    channel_id: str
    topic: str
    niche: str
    state: JobState = JobState.QUEUED
    
    script: Optional[str] = None
    metadata: Optional[str] = None
    audio_path: Optional[str] = None
    image_paths: Optional[str] = None
    video_path: Optional[str] = None
    youtube_id: Optional[str] = None
    
    attempts: int = Field(default=0)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class FailureLog(BaseModel):
    job_id: int
    channel_id: str
    module: str
    error_message: str
    traceback: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
