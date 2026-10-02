"""
engine/models.py — Pipeline Data Contracts & Pydantic Models (v2.0)
Defines strict serialization schemas for inter-stage artifacts (spec.json, clips_manifest.json).
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


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
    """Validated channel configuration schema."""
    name: str
    handle: str
    niche: str
    language: str = "en-US"
    voice_provider: str = "edge-tts"
    voice_id: str = "en-US-ChristopherNeural"
    branding: BrandingConfig = Field(default_factory=BrandingConfig)
    upload_privacy: str = "private"
    category_id: str = "27"
