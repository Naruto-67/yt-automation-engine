# engine/models.py
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
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
    # Niche is now optional during boot to allow discovery
    niche: Optional[str] = None 
    target_audience: str = "US"
    youtube_refresh_token_env: str
    # Default to a global webhook if the specific one is missing
    discord_webhook_env: str = "DISCORD_WEBHOOK_URL"
    active: bool = True

    @validator('channel_id', 'youtube_refresh_token_env')
    def validate_critical_fields(cls, v):
        if not v or len(v) < 3:
            raise ValueError("Critical ID or Token Env missing from configuration.")
        return v

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
    id: Optional[int] = None
    job_id: int
    channel_id: str
    module: str
    error_message: str
    traceback: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
