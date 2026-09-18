# engine/slideshow_risk.py — OpenMontage 6-Dimension Slideshow Risk Scorer
"""
OpenMontage Slideshow Risk Scorer & Prompt Remedy Engine.
Adapted from calesthio/OpenMontage (lib/slideshow_risk.py).

Scores image prompts across 6 dimensions that predict whether a Short will
feel like a static PowerPoint slideshow rather than a dynamic, directed video:
  1. repetition: same framing/composition recurring across scenes
  2. decorative_visuals: prompts decorate rather than communicate scene actions
  3. weak_motion: absence of dynamic camera motion keywords
  4. weak_shot_intent: lack of shot scale variety (wide, medium, close-up)
  5. typography_overreliance: prompt asks image generator to render text
  6. unsupported_cinematic_claims: claims impossible motion for a still frame

Provides audit_and_remedy_prompts() to score and automatically enhance prompts
with varied camera lenses and motions before visual generation.
"""

import re
from typing import List, Dict, Any, Tuple

# Lens and framing rotations for remedies
_REMEDY_LENSES = [
    "cinematic 35mm wide establishing angle, deep depth of field",
    "intimate 50mm prime eye-level perspective, natural bokeh",
    "dramatic 24mm low-angle tilt-up, towering perspective",
    "expressive 85mm portrait medium close-up, creamy shallow focus",
    "intense 100mm macro telephoto close-up, tactile textures",
]

_REMEDY_MOTIONS = [
    "slow steady forward push-in, parallax depth",
    "subtle dynamic tracking pan across the foreground",
    "cinematic rising pedestal motion revealing the background",
    "steady dolly-in focus shift toward the subject",
    "low sweeping slider motion emphasizing scale",
]


def score_slideshow_risk(prompts: List[str]) -> Dict[str, Any]:
    """
    Scores a sequence of visual prompts across 6 dimensions.
    Returns composite score (0.0 to 1.0, lower is better) and detailed breakdown.
    """
    if not prompts:
        return {"average": 1.0, "verdict": "fail", "dimensions": {}}

    total_scenes = len(prompts)
    dim_scores: Dict[str, float] = {}

    # 1. Repetition (detect identical framing/keywords across consecutive scenes)
    framing_keywords = ["wide", "close-up", "macro", "medium", "aerial", "eye-level", "low-angle"]
    framing_sequence = []
    for p in prompts:
        p_lower = p.lower()
        matched = [k for k in framing_keywords if k in p_lower]
        framing_sequence.append(matched[0] if matched else "unspecified")

    consecutive_repeats = sum(
        1 for i in range(len(framing_sequence) - 1)
        if framing_sequence[i] == framing_sequence[i + 1] and framing_sequence[i] != "unspecified"
    )
    dim_scores["repetition"] = round(consecutive_repeats / max(1, total_scenes - 1), 2)

    # 2. Decorative Visuals (vague generic scenes vs concrete narrative focus)
    vague_markers = ["concept of", "abstract", "symbolizing", "representation of", "background"]
    vague_count = sum(1 for p in prompts if any(v in p.lower() for v in vague_markers))
    dim_scores["decorative_visuals"] = round(vague_count / total_scenes, 2)

    # 3. Weak Motion (lack of dynamic camera movement or parallax cues)
    motion_cues = ["push-in", "dolly", "tracking", "tilt", "pan", "pedestal", "motion", "cinematic angle", "parallax"]
    lacking_motion = sum(1 for p in prompts if not any(m in p.lower() for m in motion_cues))
    dim_scores["weak_motion"] = round(lacking_motion / total_scenes, 2)

    # 4. Weak Shot Intent (shot scale diversity)
    unique_framings = len(set(framing_sequence)) - (1 if "unspecified" in framing_sequence else 0)
    shot_intent_risk = max(0.0, 1.0 - (unique_framings / min(4, total_scenes)))
    dim_scores["weak_shot_intent"] = round(shot_intent_risk, 2)

    # 5. Typography Overreliance (image prompt contains instructions to write words)
    text_cues = ["letters", "text", "words", "signboard says", "title", "spelling", "written"]
    text_count = sum(1 for p in prompts if any(tc in p.lower() for tc in text_cues))
    dim_scores["typography_overreliance"] = round(text_count / total_scenes, 2)

    # 6. Unsupported Cinematic Claims (demanding 60fps video camera moves in a still prompt)
    impossible_stills = ["slow-motion explosion", "rapid zoom out", "spins 360 degrees", "running across screen"]
    impossible_count = sum(1 for p in prompts if any(ic in p.lower() for ic in impossible_stills))
    dim_scores["unsupported_cinematic_claims"] = round(impossible_count / total_scenes, 2)

    avg_score = round(sum(dim_scores.values()) / len(dim_scores), 2)

    if avg_score < 0.25:
        verdict = "strong"
    elif avg_score < 0.45:
        verdict = "acceptable"
    elif avg_score < 0.65:
        verdict = "revise"
    else:
        verdict = "fail"

    return {
        "average": avg_score,
        "verdict": verdict,
        "dimensions": dim_scores,
    }


def audit_and_remedy_prompts(prompts: List[str], is_fictional: bool = False) -> Tuple[List[str], Dict[str, Any]]:
    """
    Audits prompts with the 6-dimension scorer.
    If risk > 0.35, injects dynamic camera lenses and movements so the resulting
    visuals feature diverse, cinematic framing rather than repetitive flat stills.
    """
    report = score_slideshow_risk(prompts)
    if report["average"] <= 0.35:
        return prompts, report

    remedied = []
    total = len(prompts)

    for i, p in enumerate(prompts):
        lens = _REMEDY_LENSES[i % len(_REMEDY_LENSES)]
        motion = _REMEDY_MOTIONS[i % len(_REMEDY_MOTIONS)]

        # Strip any accidental typography requests
        cleaned = re.sub(r'\b(with text|with words saying|writing).*?(,|$)', '', p, flags=re.IGNORECASE).strip()

        # Add style modifier if fictional
        style_mod = "3D Pixar-style digital animation render, " if is_fictional and "pixar" not in cleaned.lower() else ""

        # Prepend lens and movement framing
        new_prompt = f"{style_mod}{lens}, {motion}, {cleaned}"
        remedied.append(new_prompt)

    re_report = score_slideshow_risk(remedied)
    re_report["remedied"] = True
    re_report["initial_score"] = report["average"]
    return remedied, re_report

