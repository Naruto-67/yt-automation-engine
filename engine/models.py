# engine/models.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime

# The Job State Machine
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
    youtube_refresh_token_env: str  # e.g., "YOUTUBE_REFRESH_TOKEN_MAIN"

class VideoJob(BaseModel):
    id: Optional[int] = None
    channel_id: str
    topic: str
    niche: str
    state: JobState = JobState.QUEUED
    
    # Payload Data (Populated as the job moves through the state machine)
    script: Optional[str] = None
    metadata: Optional[Dict] = None
    audio_path: Optional[str] = None
    image_paths: Optional[List[str]] = None
    video_path: Optional[str] = None
    youtube_id: Optional[str] = None
    
    # State tracking
    attempts: int = Field(default=0)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class FailureLog(BaseModel):
    job_id: int
    channel_id: str
    module: str
    error_message: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
