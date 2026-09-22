# engine/palette_engine.py — Ghost Engine V1.0
"""
Emotion-to-Palette Calibrator (PaletteEngine).

Solves the visual disconnect problem where subtitle glow, progress bar color,
watermark opacity, and caption presets default to static, generic colors regardless
of whether the video is an eerie horror mystery or a warm, wonder-filled discovery.

Maps (mood x content_type) -> precise visual styling attributes:
- subtitle_glow_hex (ASS &HAABBGGRR format)
- progress_bar_color (RGB hex string without #)
- watermark_opacity (float 0.0-1.0)
- caption_style_override (preset key from settings.yaml)
"""

from typing import Dict, Any
from engine.logger import logger


class PaletteEngine:
    """
    Calibrates color palettes, caption typography styles, and kinetic accents
    to match the emotional register and genre of each YouTube Short.
    """

    # 5 moods x 2 content types calibration table
    _PALETTE_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
        "wonder": {
            "factual": {
                "subtitle_glow_hex": "&H00FFD700",      # Cyan/Electric Blue in ASS &HAABBGGRR
                "progress_bar_color": "00E5FF",          # Vibrant Cyan neon
                "watermark_opacity": 0.35,
                "caption_style_override": "cinematic",
                "vibe_description": "Electric wonder & deep scientific awe",
            },
            "fictional": {
                "subtitle_glow_hex": "&H0000D7FF",      # Golden Amber
                "progress_bar_color": "FFD700",          # Warm Pixar Gold
                "watermark_opacity": 0.30,
                "caption_style_override": "storytelling",
                "vibe_description": "Magical fairy-tale & heartwarming discovery",
            },
        },
        "excitement": {
            "factual": {
                "subtitle_glow_hex": "&H0000D700",      # Vibrant Emerald Green
                "progress_bar_color": "00FF66",          # High-voltage neon green
                "watermark_opacity": 0.40,
                "caption_style_override": "dynamic_upper",
                "vibe_description": "Fast-paced breakthrough facts & high momentum",
            },
            "fictional": {
                "subtitle_glow_hex": "&H0000A5FF",      # Fiery Orange
                "progress_bar_color": "FF6B00",          # Action anime blazing orange
                "watermark_opacity": 0.35,
                "caption_style_override": "viral_impact",
                "vibe_description": "Heroic daring, escalation & breakthrough action",
            },
        },
        "horror": {
            "factual": {
                "subtitle_glow_hex": "&H000015FF",      # Crimson Red
                "progress_bar_color": "E60000",          # Danger Red
                "watermark_opacity": 0.25,
                "caption_style_override": "horror_tight",
                "vibe_description": "Unsettling reality, deep sea dark facts & eerie limits",
            },
            "fictional": {
                "subtitle_glow_hex": "&H00201080",      # Deep Shadow Crimson
                "progress_bar_color": "8B0000",          # Dark Blood Red
                "watermark_opacity": 0.20,
                "caption_style_override": "horror_tight",
                "vibe_description": "Supernatural dread & high-stakes survival horror",
            },
        },
        "warm": {
            "factual": {
                "subtitle_glow_hex": "&H0020A0FF",      # Amber Glow
                "progress_bar_color": "FFA000",          # Warm Sunset Amber
                "watermark_opacity": 0.35,
                "caption_style_override": "storytelling",
                "vibe_description": "Inspiring human resilience & animal bonds",
            },
            "fictional": {
                "subtitle_glow_hex": "&H001478FF",      # Warm Hearth Firelight
                "progress_bar_color": "FF8C00",          # Ghibli campfire orange
                "watermark_opacity": 0.30,
                "caption_style_override": "storytelling",
                "vibe_description": "Empathic moral lessons & heartfelt character moments",
            },
        },
        "neutral": {
            "factual": {
                "subtitle_glow_hex": "&H0000D700",      # Clean Green
                "progress_bar_color": "00E676",          # Mint accent
                "watermark_opacity": 0.35,
                "caption_style_override": "minimal_clean",
                "vibe_description": "Authoritative curiosity & crisp information",
            },
            "fictional": {
                "subtitle_glow_hex": "&H00FFD700",      # Soft Azure
                "progress_bar_color": "40C4FF",          # Sky Blue
                "watermark_opacity": 0.30,
                "caption_style_override": "cinematic",
                "vibe_description": "Balanced narrative worldbuilding",
            },
        },
    }

    def calibrate_palette(
        self,
        mood: str = "neutral",
        content_type: str = "factual"
    ) -> Dict[str, Any]:
        """
        Calibrate visual palette and styling attributes for the given mood and content type.

        Args:
            mood: "wonder" | "excitement" | "horror" | "warm" | "neutral"
            content_type: "factual" | "fictional"

        Returns:
            dict containing:
                subtitle_glow_hex: ASS format color code
                progress_bar_color: Hex color string (RGB)
                watermark_opacity: float 0.0 to 1.0
                caption_style_override: preset name
                vibe_description: explanatory tag
        """
        mood_key = (mood or "neutral").strip().lower()
        if mood_key not in self._PALETTE_MAP:
            mood_key = "neutral"

        ct_key = (content_type or "factual").strip().lower()
        if ct_key not in ("factual", "fictional"):
            ct_key = "factual"

        config = self._PALETTE_MAP[mood_key][ct_key].copy()
        logger.debug(
            f"[PALETTE] Calibrated for mood='{mood_key}', content_type='{ct_key}' "
            f"-> glow={config['subtitle_glow_hex']}, bar={config['progress_bar_color']}"
        )
        return config


# Singleton instance
palette_engine = PaletteEngine()

