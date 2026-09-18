# engine/delivery_promise.py — OpenMontage Delivery Promise Framework
"""
Delivery Promise Classifier & Governance Engine.
Adapted from calesthio/OpenMontage (lib/delivery_promise.py).

Prevents the silent downgrade failure mode where an animated storytelling
channel receives live-action stock footage (e.g. lipstick/shopping mall bug),
or a factual channel receives cartoon imagery.

Classifies the channel's production promise and enforces strict rules on
which media generation/sourcing tiers are permitted.
"""

from enum import Enum
from typing import Dict, Any, List, Optional


class PromiseType(Enum):
    ANIMATION_LED = "animation_led"          # 3D/Anime/Pixar storytelling (CH_01)
    SOURCE_OR_PHOTO_LED = "source_or_photo_led"  # Photorealistic science/history facts (CH_02)
    DATA_EXPLAINER = "data_explainer"        # Educational diagrams & stats
    HYBRID = "hybrid"                        # Mixed media


PROMISE_RULES: Dict[PromiseType, Dict[str, Any]] = {
    PromiseType.ANIMATION_LED: {
        "stock_video_allowed": False,       # NEVER allow real-human stock video
        "stock_photo_allowed": False,       # NEVER allow real-human stock photos
        "requires_ai_generation": True,     # FLUX / SDXL with 3D animation prompts
        "allowed_providers": [
            "Cloudflare FLUX API",
            "HuggingFace FLUX",
            "Pollinations.ai",
            "Local Render",
        ],
        "description": "3D Pixar/anime digital animated storytelling. Live-action stock footage is strictly prohibited.",
    },
    PromiseType.SOURCE_OR_PHOTO_LED: {
        "stock_video_allowed": True,        # Pexels/Pixabay b-roll allowed for real science/nature
        "stock_photo_allowed": True,
        "requires_ai_generation": False,    # Can use AI or stock
        "allowed_providers": [
            "Cloudflare FLUX API",
            "HuggingFace FLUX",
            "Pixabay Video",
            "Pollinations.ai",
            "Pexels Stock",
            "Local Render",
        ],
        "description": "Photorealistic science and historical facts. Cinematic b-roll and macro photography allowed.",
    },
    PromiseType.DATA_EXPLAINER: {
        "stock_video_allowed": True,
        "stock_photo_allowed": True,
        "requires_ai_generation": False,
        "allowed_providers": ["Cloudflare FLUX API", "HuggingFace FLUX", "Pexels Stock", "Local Render"],
        "description": "Educational data explanations and historical records.",
    },
    PromiseType.HYBRID: {
        "stock_video_allowed": True,
        "stock_photo_allowed": True,
        "requires_ai_generation": True,
        "allowed_providers": ["Cloudflare FLUX API", "HuggingFace FLUX", "Pixabay Video", "Pollinations.ai", "Pexels Stock", "Local Render"],
        "description": "Balanced multi-format presentation.",
    },
}


class DeliveryPromise:
    """Represents a locked contract for a channel's production pipeline."""

    def __init__(self, channel_id: str, content_type: str, niche: str):
        self.channel_id = channel_id
        self.content_type = content_type
        self.niche = niche
        self.promise_type = self._classify()
        self.rules = PROMISE_RULES[self.promise_type]

    def _classify(self) -> PromiseType:
        ct = (self.content_type or "").lower()
        n = (self.niche or "").lower()

        if ct == "fictional" or any(k in n for k in ["pixar", "anime", "story", "fictional", "moral"]):
            return PromiseType.ANIMATION_LED
        if any(k in n for k in ["fact", "curious", "science", "history", "educational", "trivia"]):
            return PromiseType.SOURCE_OR_PHOTO_LED
        if any(k in n for k in ["data", "chart", "tech"]):
            return PromiseType.DATA_EXPLAINER
        return PromiseType.HYBRID

    @property
    def allows_stock_video(self) -> bool:
        return self.rules["stock_video_allowed"]

    @property
    def allows_stock_photos(self) -> bool:
        return self.rules["stock_photo_allowed"]

    def validate_provider(self, provider_name: str) -> bool:
        """Check whether a visual provider respects this channel's promise."""
        allowed = self.rules.get("allowed_providers", [])
        return any(a.lower() in provider_name.lower() for a in allowed)


def get_delivery_promise(channel_config: Any) -> DeliveryPromise:
    """Convenience factory to instantiate a locked DeliveryPromise from channel config."""
    channel_id = getattr(channel_config, "channel_id", "CH_01")
    content_type = getattr(channel_config, "content_type", "factual")
    niche = getattr(channel_config, "niche", "")
    return DeliveryPromise(channel_id=channel_id, content_type=content_type, niche=niche)

