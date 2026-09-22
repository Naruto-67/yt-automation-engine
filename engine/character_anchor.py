# engine/character_anchor.py — Ghost Engine V1.0
"""
Character Visual Anchor Engine.

Solves the visual drift problem in fictional YouTube Shorts:
- Fixed style card (per channel in channels.yaml) → consistent art style across ALL videos
- Per-video character lock (extracted from script by one LLM call) → consistent protagonist WITHIN a video

Without this, the image model imagines the same character differently in each scene.
With this, every scene prompt starts with the same locked character descriptor.
"""
import re
import os
import yaml
from engine.logger import logger


def load_config_prompts() -> dict:
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class CharacterAnchorEngine:
    """
    Two-layer visual consistency system for fictional channels.

    Layer 1 — Style Card (channel-level, permanent):
        Stored in channels.yaml under `visual_style_card`.
        Defines the art style, render engine, and color treatment.
        Never changes between videos — this is what makes the channel visually recognisable.

    Layer 2 — Character Lock (per-video, extracted from script):
        One LLM call extracts: protagonist name, estimated age, hair description,
        clothing, and posture/expression. This descriptor is prepended to EVERY
        scene image prompt so all 4 scenes show the same character.
    """

    # Extraction prompt — designed to be short (minimal quota use)
    _EXTRACT_SYSTEM = (
        "You are a visual character descriptor. Extract the protagonist's physical appearance "
        "from a script in one compact sentence. Return ONLY the descriptor string, nothing else."
    )

    _EXTRACT_USER = (
        "Script: \"{script_text}\"\n\n"
        "Describe the protagonist's visual appearance in ONE sentence covering: "
        "name (if given), approximate age, hair color and style, clothing/outfit, "
        "and dominant expression or posture. "
        "Example: 'Kael, a 16-year-old boy with short dark hair, a worn leather jacket, "
        "and determined eyes mid-stride.' "
        "If no clear protagonist exists, return: 'No protagonist — use environment-focused composition.' "
        "Return ONLY the descriptor sentence."
    )

    def extract_character_lock(
        self,
        script_text: str,
        topic: str,
        channel_id: str = "",
    ) -> str | None:
        """
        Extract a character lock descriptor from the script using one LLM call.

        Returns:
            str: A compact one-sentence character descriptor, or None if extraction fails.
        """
        if not script_text or not script_text.strip():
            return None

        try:
            from scripts.quota_manager import quota_manager

            user_msg = self._EXTRACT_USER.format(script_text=script_text[:1200])
            raw, provider = quota_manager.generate_text(
                user_msg,
                task_type="analysis",
                system_prompt=self._EXTRACT_SYSTEM,
            )

            if not raw or not raw.strip():
                logger.debug("[CHARACTER ANCHOR] Empty LLM response — skipping character lock.")
                return None

            # Strip any accidental JSON, quotes, or markdown the LLM adds
            lock = raw.strip().strip('"').strip("'").strip()

            # Sanity check: must be a single sentence (not multi-paragraph)
            if len(lock) > 300:
                lock = lock[:300].rsplit('.', 1)[0].strip() + '.'

            # If the model says there's no protagonist, skip anchoring
            if "no protagonist" in lock.lower():
                logger.debug(f"[CHARACTER ANCHOR] No protagonist detected for topic: {topic}")
                return None

            print(f"   🎭 [CHARACTER ANCHOR] Lock extracted via {provider}: {lock[:80]}...")
            return lock

        except Exception as e:
            logger.debug(f"[CHARACTER ANCHOR] Extraction failed: {e}")
            return None

    def build_anchored_prompt(
        self,
        base_image_prompt: str,
        character_lock: str | None,
        style_card: dict | None,
        scene_index: int = 0,
    ) -> str:
        """
        Prepend the style card and character lock to an image prompt.

        Args:
            base_image_prompt: The original scene image prompt from the LLM.
            character_lock: The one-sentence character descriptor (or None).
            style_card: The channel's visual_style_card dict from channels.yaml (or None).
            scene_index: 0-based scene number (used for logging).

        Returns:
            str: The enhanced image prompt with character consistency prefix.
        """
        prefix_parts = []

        # ── Style card prefix ────────────────────────────────────────────────
        if style_card and isinstance(style_card, dict):
            art_style     = style_card.get("art_style", "")
            render_engine = style_card.get("render_engine", "")
            color_treat   = style_card.get("color_treatment", "")

            style_parts = [p for p in [art_style, render_engine, color_treat] if p]
            if style_parts:
                prefix_parts.append("STYLE: " + ", ".join(style_parts))

        # ── Character lock prefix ────────────────────────────────────────────
        if character_lock and "no protagonist" not in character_lock.lower():
            prefix_parts.append(f"CHARACTER (maintain exact appearance): {character_lock}")

        if not prefix_parts:
            return base_image_prompt

        anchor_prefix = " | ".join(prefix_parts)
        anchored = f"[LOCKED: {anchor_prefix}] {base_image_prompt}"

        logger.debug(f"[CHARACTER ANCHOR] Scene {scene_index + 1} anchored ({len(anchored)} chars).")
        return anchored

    def get_style_card(self, channel_id: str) -> dict | None:
        """
        Read the visual_style_card for a channel from channels.yaml.

        Returns:
            dict | None: The style card dict, or None if not configured.
        """
        try:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            channels_path = os.path.join(root_dir, "config", "channels.yaml")
            with open(channels_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            for ch in data.get("channels", []):
                if ch.get("id") == channel_id:
                    style_card = ch.get("visual_style_card")
                    if style_card and isinstance(style_card, dict):
                        return style_card
                    return None

        except Exception as e:
            logger.debug(f"[CHARACTER ANCHOR] Could not load style card for {channel_id}: {e}")
        return None

    def apply_to_all_scenes(
        self,
        script_text: str,
        topic: str,
        channel_id: str,
        image_prompts: list[str],
        content_type: str = "fictional",
    ) -> list[str]:
        """
        Full pipeline: extract character lock → apply to all scene prompts.

        Only activates for fictional channels. Factual channels skip silently.

        Args:
            script_text: The full script text (all scenes joined).
            topic: The video topic (for logging).
            channel_id: The channel ID (e.g. "CH_01").
            image_prompts: List of scene image prompts to anchor.
            content_type: "fictional" or "factual".

        Returns:
            list[str]: Enhanced image prompts (or originals if anchoring skipped).
        """
        # Only anchor fictional channels — factual channels use photorealistic prompts
        if content_type != "fictional":
            return image_prompts

        if not image_prompts:
            return image_prompts

        # Load style card
        style_card = self.get_style_card(channel_id)

        # Extract character lock
        character_lock = self.extract_character_lock(script_text, topic, channel_id)

        if not character_lock and not style_card:
            logger.debug("[CHARACTER ANCHOR] No style card or character lock available — returning original prompts.")
            return image_prompts

        # Apply to all scenes
        anchored_prompts = []
        for i, prompt in enumerate(image_prompts):
            anchored = self.build_anchored_prompt(
                base_image_prompt=prompt,
                character_lock=character_lock,
                style_card=style_card,
                scene_index=i,
            )
            anchored_prompts.append(anchored)

        print(f"   🎭 [CHARACTER ANCHOR] Applied to {len(anchored_prompts)} scenes | Channel: {channel_id} | Topic: {topic[:50]}")
        return anchored_prompts


# Module-level singleton
character_anchor = CharacterAnchorEngine()
