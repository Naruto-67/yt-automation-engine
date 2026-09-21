"""
engine/vision_critic.py — Vision Critic Pre-Flight Frame Inspector

Free-tier multimodal vision inspector leveraging Gemini 3.x Flash
(gemini-flash-lite-latest / gemini-3.5-flash-lite / gemini-3.6-flash) with local deterministic heuristic
fallbacks (PIL/entropy/aspect ratio) to audit generated visual frames before
compositing in FFmpeg.

Key Capabilities:
1. Multimodal Evaluation: Evaluates anatomical integrity, limb counts, prompt relevance,
   and 9:16 vertical composition.
2. Auto-Remedy Hinting: If an image exhibits AI distortion (score < 6.0), generates a
   precise remedy hint to re-roll the prompt with targeted negative constraints.
3. Deterministic Fallback: Runs heuristic validation (dimensions, file size, variance)
   when offline, in test mode, or when vision API quota is unavailable.
4. Decision Ledger: Automatically records all visual quality gate verdicts to CHAI
   Append-Only Decision Log.
"""

import os
import sys
import json
import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

logger = logging.getLogger("yt_engine.vision_critic")


class VisionCritic:
    """Pre-flight visual inspector auditing candidate frames before rendering."""

    def __init__(self, min_pass_score: float = 6.0):
        self.min_pass_score = min_pass_score

    def _heuristic_check(self, image_path: str) -> Dict[str, Any]:
        """Local deterministic fallback verifying file integrity and geometry."""
        if not os.path.exists(image_path):
            return {
                "approved": False,
                "score": 0.0,
                "remedy_hint": "Image file not found on disk.",
                "reasons": ["File does not exist"],
                "engine": "heuristic_fallback"
            }

        file_size = os.path.getsize(image_path)
        if file_size < 15_000:  # Under 15KB is likely corrupt or a blank placeholder
            return {
                "approved": False,
                "score": 3.0,
                "remedy_hint": "Regenerate with higher detail; asset file size too small (<15KB).",
                "reasons": [f"File size too small ({file_size} bytes)"],
                "engine": "heuristic_fallback"
            }

        # Check with PIL if available
        try:
            from PIL import Image
            with Image.open(image_path) as img:
                w, h = img.size
                aspect = w / h if h > 0 else 1.0
                
                # Check for landscape aspect ratio (should be vertical 9:16 ~ 0.56)
                is_vertical = h >= w
                reasons = [f"Dimensions: {w}x{h} (aspect: {aspect:.2f})"]
                
                score = 8.0
                remedy_hint = ""
                
                if aspect > 0.8:
                    score -= 2.0
                    reasons.append("Image is not native 9:16 vertical; will require cropping.")
                    remedy_hint = "Ensure prompt specifies 9:16 vertical orientation, tall portrait."

                # Check color variance / blankness
                if img.mode != "RGB":
                    img_rgb = img.convert("RGB")
                else:
                    img_rgb = img

                extrema = img_rgb.getextrema()
                # If all channels have zero or near-zero range, it's a solid/blank color
                total_range = sum((hi - lo) for lo, hi in extrema)
                if total_range < 30:
                    return {
                        "approved": False,
                        "score": 1.0,
                        "remedy_hint": "Regenerate image; frame is solid or nearly blank.",
                        "reasons": ["Extremely low color variance / solid blank frame"],
                        "engine": "heuristic_fallback"
                    }

                return {
                    "approved": score >= self.min_pass_score,
                    "score": score,
                    "remedy_hint": remedy_hint,
                    "reasons": reasons,
                    "engine": "heuristic_fallback"
                }
        except Exception as e:
            logger.debug(f"PIL heuristic check skipped: {e}")
            # If PIL is not installed, pass if file size > 25KB
            return {
                "approved": file_size >= 25_000,
                "score": 7.0 if file_size >= 25_000 else 4.0,
                "remedy_hint": "Check image dimensions and prompt framing." if file_size < 25_000 else "",
                "reasons": [f"File size: {file_size} bytes (PIL unavailable)"],
                "engine": "heuristic_fallback"
            }

    def evaluate_frame(
        self,
        image_path: str,
        prompt: str,
        scene_text: str = "",
        channel_id: str = "GLOBAL"
    ) -> Dict[str, Any]:
        """
        Audits a generated frame via Gemini Flash Vision (free tier)
        or falls back to deterministic heuristic inspection.
        """
        # 1. First run deterministic local check
        local_result = self._heuristic_check(image_path)
        if not local_result["approved"] and local_result["score"] <= 3.0:
            self._log_verdict(channel_id, image_path, local_result)
            return local_result

        # 2. Try Gemini Flash Vision if credentials exist
        gemini_api_key = (
            os.environ.get("GEMINI_API_KEY") or
            os.environ.get("GOOGLE_API_KEY")
        )

        if not gemini_api_key:
            self._log_verdict(channel_id, image_path, local_result)
            return local_result

        try:
            critique = self._evaluate_with_gemini(image_path, prompt, scene_text, gemini_api_key)
            if critique:
                self._log_verdict(channel_id, image_path, critique)
                return critique
        except Exception as e:
            logger.debug(f"Gemini Flash Vision evaluation failed: {e}")

        # If API call failed or timed out, fall back gracefully to local heuristic
        self._log_verdict(channel_id, image_path, local_result)
        return local_result

    def _evaluate_with_gemini(
        self,
        image_path: str,
        prompt: str,
        scene_text: str,
        api_key: str
    ) -> Optional[Dict[str, Any]]:
        """Invokes Gemini Flash Vision to score frame quality."""
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        mime_type = "image/jpeg"
        if image_path.lower().endswith(".png"):
            mime_type = "image/png"
        elif image_path.lower().endswith(".webp"):
            mime_type = "image/webp"

        eval_prompt = f"""You are a strict pre-flight visual quality inspector for viral YouTube Shorts.
Inspect this generated frame for a vertical video scene.
Original scene prompt: "{prompt}"
Scene narrative text: "{scene_text}"

Audit the following criteria:
1. Anatomical Integrity: Check for mangled hands, unnatural extra limbs, warped eyes, or nightmarish AI artifacts.
2. Prompt & Scene Relevance: Does the visual depict the core action/subject cleanly?
3. Composition: Is it well-framed for 9:16 vertical video without awkward subject cutoffs?

Return ONLY a valid JSON object in this exact schema:
{{
  "approved": true,
  "score": 8.5,
  "remedy_hint": "",
  "reasons": ["Natural anatomy", "Accurate 9:16 composition", "Matches narrative"]
}}
If score is below 6.0, set approved to false and provide a 1-sentence remedy_hint to fix the prompt."""

        # Attempt with google-genai SDK (v1 / modern)
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options={"timeout": 60000})

            # Candidate multimodal vision models (pure standard defaults, no temperature)
            vision_candidates = [
                "gemini-flash-lite-latest",
                "gemini-3.5-flash-lite",
                "gemini-3.6-flash"
            ]

            gen_cfg = types.GenerateContentConfig(
                response_mime_type="application/json",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                http_options={"timeout": 60000}
            )

            for target_model in vision_candidates:
                try:
                    response = client.models.generate_content(
                        model=target_model,
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                            eval_prompt
                        ],
                        config=gen_cfg
                    )
                    raw_text = response.text or ""
                    clean_json = re.sub(r"```json\s*", "", raw_text)
                    clean_json = re.sub(r"```\s*", "", clean_json).strip()

                    start = clean_json.find('{')
                    end = clean_json.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        data = json.loads(clean_json[start:end + 1])
                        score = float(data.get("score", 7.0))
                        return {
                            "approved": bool(data.get("approved", score >= self.min_pass_score)),
                            "score": score,
                            "remedy_hint": str(data.get("remedy_hint", "")),
                            "reasons": data.get("reasons", []),
                            "engine": target_model
                        }
                except Exception as candidate_err:
                    logger.debug(f"Vision audit on {target_model} failed: {candidate_err}")
                    continue

        except Exception as sdk_err:
            logger.debug(f"google.genai SDK vision call initialization failed: {sdk_err}")

        return None

    def _log_verdict(self, channel_id: str, image_path: str, verdict: Dict[str, Any]):
        """Logs audit outcome to CHAI Append-Only Decision Log."""
        try:
            from engine.decision_log import decision_log
            decision_log.record(
                category="QUALITY_GATE",
                decision=f"Vision Critic Frame Inspection ({'PASS' if verdict.get('approved') else 'FAIL'})",
                chosen=f"Score: {verdict.get('score', 0):.1f} via {verdict.get('engine', 'heuristic')}",
                options_considered=["Gemini Flash Vision", "Heuristic Geometry Validator"],
                channel_id=channel_id,
                extra={
                    "image": os.path.basename(image_path),
                    "approved": verdict.get("approved", True),
                    "score": verdict.get("score", 0),
                    "remedy_hint": verdict.get("remedy_hint", ""),
                    "reasons": verdict.get("reasons", [])
                }
            )
        except Exception as e:
            logger.debug(f"Failed to record vision critic decision: {e}")


# Singleton instance
vision_critic = VisionCritic()

