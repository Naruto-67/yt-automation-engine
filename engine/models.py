# engine/models.py — Ghost Engine V6
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List
from datetime import datetime
from enum import Enum


class JobState(str, Enum):
    QUEUED             = "queued"
    SCRIPT_GENERATION  = "script_generation"
    VOICE_GENERATION   = "voice_generation"
    VISUAL_GENERATION  = "visual_generation"
    RENDERING          = "rendering"
    VAULTED            = "vaulted"
    PUBLISHED          = "published"
    FAILED             = "failed"


class ChannelConfig(BaseModel):
    # ── FIX: Pydantic field aliases to match YAML keys 'id' and 'name' ────────
    model_config = ConfigDict(populate_by_name=True)

    channel_id:   str = Field(alias="id")
    channel_name: str = Field(alias="name")

    # Niche is optional — system will auto-discover if missing
    niche:          Optional[str] = None
    target_audience: str = "US"

    # ── Per-channel GCP project credentials (Option A: separate quotas) ───────
    youtube_client_id_env:     str  # Env var name holding this channel's GCP client_id
    youtube_client_secret_env: str  # Env var name holding this channel's GCP client_secret
    youtube_refresh_token_env: str  # Env var name holding this channel's OAuth refresh token

    # Discord: each channel posts to its own webhook
    discord_webhook_env: str = "DISCORD_WEBHOOK_URL"

    active: bool = True

    @field_validator("channel_id", "youtube_client_id_env",
                     "youtube_client_secret_env", "youtube_refresh_token_env")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        if not v or len(v.strip()) < 3:
            raise ValueError(f"Required channel field is missing or too short: '{v}'")
        return v.strip()


class VideoJob(BaseModel):
    id:         Optional[int] = None
    channel_id: str
    topic:      str
    niche:      str
    state:      JobState = JobState.QUEUED

    script:      Optional[str] = None  # JSON blob: text, prompts, voice, color, etc.
    metadata:    Optional[str] = None  # JSON blob: title, description, tags
    audio_path:  Optional[str] = None
    image_paths: Optional[str] = None  # JSON list of paths
    video_path:  Optional[str] = None
    youtube_id:  Optional[str] = None

    attempts:   int = Field(default=0)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class FailureLog(BaseModel):
    id:            Optional[int] = None
    job_id:        int
    channel_id:    str
    module:        str
    error_message: str
    traceback:     Optional[str] = None
    timestamp:     str = Field(default_factory=lambda: datetime.utcnow().isoformat())
