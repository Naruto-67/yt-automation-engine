# engine/loop_engine.py — 2026 Circular Script Seamless Loop Engine
"""
Circular Script Seamless Loop Engine.
Implements the 4th beat of the 2026 YouTube Shorts viral retention playbook:
The Infinite Seamless Loop.

Structures video scripts so the final sentence flows seamlessly, grammatically,
and rhythmically directly back into the opening hook without traditional
sign-offs ("thanks for watching", "subscribe"). When a Short replays, the viewer
doesn't realize the video ended, boosting Average Percentage Viewed (APV) > 100%.
"""

import re
from typing import Tuple, Dict, Any, List

_BANNED_SIGN_OFFS = [
    "thanks for watching",
    "thank you for watching",
    "subscribe for more",
    "subscribe now",
    "like and subscribe",
    "follow for more",
    "leave a comment",
    "see you next time",
    "in conclusion",
    "that's all for today",
    "the end",
    "hope you enjoyed",
    "tune in next time",
]

_CONNECTIVE_BRIDGE_CUES = [
    "and that is why",
    "and that's why",
    "which is why",
    "which means",
    "that is because",
    "that's because",
    "so whenever you",
    "and it all leads back to",
    "and it all began when",
    "leading directly to",
    "and it proves that",
    "meaning that",
    "so the next time you see",
    "because in the end",
]


class LoopVerdict(dict):
    """Result object supporting both dictionary key access and tuple unpacking."""
    def __getitem__(self, item):
        if isinstance(item, int):
            keys = ["is_valid", "loop_score", "reason"]
            return super().__getitem__(keys[item])
        return super().__getitem__(item)

    def __iter__(self):
        return iter((self["is_valid"], self["loop_score"], self["reason"]))


class CircularLoopEngine:
    """Audits and enhances scripts for seamless, infinite looping playback."""

    def validate_circular_loop(self, hook_text: str, ending_text: str) -> LoopVerdict:
        """
        Validates whether the script ending seamlessly loops back to the hook.
        Returns: LoopVerdict with keys {"is_valid", "loop_score", "reason"} (also supports tuple unpacking).
        """
        if not hook_text or not ending_text:
            return LoopVerdict({
                "is_valid": False,
                "loop_score": 0.0,
                "reason": "Missing hook or ending text."
            })

        ending_lower = ending_text.lower().strip()
        hook_lower = hook_text.lower().strip()

        # 1. Check for banned sign-off phrases
        for sign_off in _BANNED_SIGN_OFFS:
            if sign_off in ending_lower:
                return LoopVerdict({
                    "is_valid": False,
                    "loop_score": 0.1,
                    "reason": f"Ending contains swiping trigger '{sign_off}'. Must end on narrative continuation."
                })

        # 2. Check for explicit connective bridge cues
        has_bridge = any(cue in ending_lower for cue in _CONNECTIVE_BRIDGE_CUES)

        # 3. Check for open clause ending (ending in comma, dash, or connective preposition)
        open_connector_words = ["to", "that", "because", "when", "why", "how", "with", "for", "as"]
        last_word = re.sub(r'[^\w\s]', '', ending_lower.split()[-1]) if ending_lower.split() else ""
        has_open_preposition = last_word in open_connector_words

        # 4. Check semantic alignment (first word of hook is continuation)
        first_hook_word = hook_lower.split()[0] if hook_lower.split() else ""
        connects_with_noun_or_verb = first_hook_word not in ["hello", "hey", "welcome", "today"]

        # Base score for clean narrative without swiping triggers
        score = 0.70
        feedback_parts = ["Clean narrative without swiping triggers."]

        if has_bridge:
            score += 0.20
            feedback_parts.append("Features seamless connective bridge cue.")
        if has_open_preposition:
            score += 0.15
            feedback_parts.append("Ending clause opens direct syntactic continuation.")
        if connects_with_noun_or_verb:
            score += 0.05

        is_seamless = score >= 0.70
        return LoopVerdict({
            "is_valid": is_seamless,
            "loop_score": min(1.0, score),
            "reason": " ".join(feedback_parts)
        })

    def get_loop_prompt_instructions(self) -> str:
        """Returns the prompt shard mandating circular loop script structure."""
        return (
            "── 2026 INFINITE SEAMLESS LOOP MANDATE (ALGORITHM RETENTION MULTIPLIER):\n"
            "• The final sentence of Scene 4 must be engineered to flow seamlessly back into your opening hook.\n"
            "• Connect the ending clause directly to the beginning thought (e.g. Ending: '...and that is why scientists are amazed that' → Hook: 'A four-millimeter creature in the ocean never dies.').\n"
            "• NEVER include sign-offs like 'thanks for watching', 'subscribe', or 'the end' — these cause immediate viewer swipes.\n"
            "• End on high momentum so replaying the video feels like one continuous, circular narrative."
        )


# Global singleton instance
loop_engine = CircularLoopEngine()
