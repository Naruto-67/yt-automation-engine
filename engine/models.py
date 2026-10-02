"""
engine/models.py — Pipeline Data Contracts & Pydantic Models (v2.0)
Defines strict serialization schemas for v2.0 inter-stage artifacts (spec.json, clips_manifest.json)
while maintaining backward-compatible data classes for database/guardian operations.
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field


# ─── V2.0 SINGLE-CHANNEL STOCK VIDEO CONTRACTS ───────────────────────────────

class WordTimestamp(BaseModel):
    """Word-level timing information extracted from Edge-TTS WebSocket stream."""
    word: str
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")


class SceneSpec(BaseModel):
    """Specification for an individual scene in the generated video."""
    scene_id: int
    spoken_text: str = Field(..., description="Display text used for on-screen captions")
    phonetic_text: str = Field(..., description="Sanitized phonetic text fed into TTS")
    stock_video_query: str = Field(..., description="Semantic search query for stock video APIs")
    duration_seconds: float = Field(default=0.0, description="Measured duration of audio in seconds")
    word_timestamps: List[WordTimestamp] = Field(default_factory=list, description="Word-by-word timing")


class SEOMetadata(BaseModel):
    """SEO and packaging metadata for YouTube upload."""
    title: str
    description: str
    tags: List[str]


class SpecOutput(BaseModel):
    """Stage 1 output contract written to output/spec.json."""
    topic: str
    video_type: str = Field(default="short", description="'short' (9:16) or 'long' (16:9)")
    sub_format: str = Field(default="core_brainblud", description="'core_brainblud' or 'listicle'")
    seo: SEOMetadata
    scenes: List[SceneSpec]
    total_duration_seconds: float = 0.0
    audio_path: Optional[str] = "output/narration.mp3"
    thought_process: Optional[Dict[str, Any]] = None


class ClipItem(BaseModel):
    """Stock video clip match from Pexels or Pixabay."""
    scene_id: int
    query: str
    video_id: str
    download_url: str
    provider: str = Field(..., description="'pexels' or 'pixabay'")
    duration: float = 0.0
    width: int = 1080
    height: int = 1920


class ClipsManifest(BaseModel):
    """Stage 2 output contract written to output/clips_manifest.json."""
    topic: str
    video_type: str
    clips: List[ClipItem]


class BrandingConfig(BaseModel):
    """Channel watermark branding options."""
    enabled: bool = True
    watermark_text: str = "@BrainBlud"
    opacity: float = 0.40
    position: str = "top_right"
    font_size: int = 26
    font_family: str = "Montserrat-SemiBold"


class ChannelConfigModel(BaseModel):
    """Validated channel configuration schema for v2.0."""
    name: str
    handle: str
    niche: str
    language: str = "en-US"
    voice_provider: str = "edge-tts"
    voice_id: str = "en-US-ChristopherNeural"
    branding: BrandingConfig = Field(default_factory=BrandingConfig)
    upload_privacy: str = "private"
    category_id: str = "27"


# ─── LEGACY ENGINE MODELS (Backward Compatibility) ───────────────────────────

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
    channel_id: str = "CH_01"
    channel_name: str = "BrainBlud"
    niche: str = "psychology_and_facts"
    target_audience: str = ""
    youtube_refresh_token_env: str = "YOUTUBE_REFRESH_TOKEN"
    youtube_client_id_env: str = "YOUTUBE_CLIENT_ID"
    youtube_client_secret_env: str = "YOUTUBE_CLIENT_SECRET"
    discord_webhook_env: str = "DISCORD_WEBHOOK"
    creative_lenses: List[str] = Field(default_factory=list)
    category_id: str = "27"
    language: str = "en"
    locale: str = "en-US"
    tts_locale: str = "en-US"
    content_type: str = "factual"
    brand_voice: str = ""
    personality: List[str] = Field(default_factory=list)
    visual_style_card: Dict[str, Any] = Field(default_factory=dict)
    narrator_persona: Dict[str, Any] = Field(default_factory=dict)


class VideoJob(BaseModel):
    id: Optional[int] = None
    channel_id: str = "CH_01"
    topic: str = ""
    niche: str = ""
    state: JobState = JobState.QUEUED
    script: Optional[str] = None
    metadata: Optional[str] = None
    audio_path: Optional[str] = None
    image_paths: Optional[str] = None
    video_path: Optional[str] = None
    youtube_id: Optional[str] = None
    attempts: int = Field(default=0)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FailureLog(BaseModel):
    job_id: int
    channel_id: str
    module: str
    error_message: str
    traceback: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
