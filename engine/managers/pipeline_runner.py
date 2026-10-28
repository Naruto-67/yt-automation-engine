from __future__ import annotations

import os
import sys
import re
import yaml
import json
import random
import hashlib
import datetime
import argparse
import pathlib
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.managers.health_manager import HealthManager
from engine.managers.llm_manager import LLMManager
from engine.managers.competitor_spy import CompetitorSpy
from engine.managers.topic_inspector import TopicInspector
from engine.managers.voice_normalizer import VoiceNormalizer
from engine.models import SpecOutput, SceneSpec, SEOMetadata, WordTimestamp


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_yaml(path: str, data: Dict[str, Any]) -> None:
    """Write YAML preserving key order. Creates a .bak backup first."""
    p = pathlib.Path(path)
    if p.exists():
        try:
            p.with_suffix(".yaml.bak").write_bytes(p.read_bytes())
        except Exception:
            pass
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


# ─── THOUGHT CACHE HELPERS ────────────────────────────────────────────────────

_CHANNEL_CONFIG_PATH = "config/channel_config.yaml"
_MEMORY_THOUGHT_CACHE_PATH = os.path.join("memory", "thought_cache.json")


def is_test_run() -> bool:
    """Returns True if running in test mode."""
    return (
        os.environ.get("TEST_MODE", "").lower() in ("true", "1") or
        os.environ.get("GHOST_ENGINE_ENABLED", "").lower() == "test"
    )


def _hash_line(line: str) -> str:
    """SHA-256 hash of a normalised spoken line (stripped, lowercased, no punctuation)."""
    normalised = re.sub(r"[^\w\s]", "", line.strip().lower())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _load_thought_cache(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cache = cfg.setdefault("thought_cache", {"max_entries": 200, "entries": []})
    if os.path.exists(_MEMORY_THOUGHT_CACHE_PATH):
        try:
            with open(_MEMORY_THOUGHT_CACHE_PATH, "r", encoding="utf-8") as f:
                mem_cache = json.load(f)
            existing_hashes = {e.get("hash") for e in cache.get("entries", [])}
            for e in mem_cache.get("entries", []):
                if e.get("hash") not in existing_hashes:
                    cache["entries"].append(e)
                    existing_hashes.add(e.get("hash"))
        except Exception:
            pass
    return cache


def _is_duplicate(line: str, cache_cfg: Dict[str, Any]) -> bool:
    lh = _hash_line(line)
    return any(item.get("hash") == lh for item in cache_cfg.get("entries", []))


def _add_to_cache(line: str, cache_cfg: Dict[str, Any]) -> None:
    """Append hash of *line* and evict oldest entries beyond max_entries."""
    lh = _hash_line(line)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entries: List[Dict] = cache_cfg.setdefault("entries", [])
    # Don't double-register an entry from the same run
    if not any(e.get("hash") == lh for e in entries):
        entries.append({"hash": lh, "ts": now_iso})
    max_sz = cache_cfg.get("max_entries", 200)
    if len(entries) > max_sz:
        cache_cfg["entries"] = entries[-max_sz:]


def is_dangling_or_incomplete_sentence(text: str) -> Tuple[bool, str]:
    """
    Checks whether a spoken text line is an unfinished sentence or dangling fragment.
    Enforces script and scene completion:
    - Rejects malformed punctuation endings such as double or quadruple ellipses ('…...', '....').
    - Rejects trailing dangling subordinate clauses ending in an ellipsis without an independent clause
      (e.g., 'So the next time your mind rewinds...', 'The next time you blink...').
    - Rejects fragments ending in dangling conjunctions or prepositions.
    """
    clean = text.strip()
    if not clean:
        return True, "Empty spoken text"

    # 1. Corrupted or duplicated ellipsis punctuation (e.g. '…...', '....', ',...')
    if re.search(r"[…\.]{4,}", clean) or "….." in clean or clean.endswith(",...") or clean.endswith(",…"):
        return True, "Malformed or duplicated ellipsis punctuation"

    lower = clean.lower()
    stripped_trailing = re.sub(r"[\.\s…]+$", "", clean).strip().lower()
    words = stripped_trailing.split()

    # 2. Trailing dangling conjunction or preposition
    dangling_endings = [
        "and", "but", "or", "because", "so", "with", "to", "that", "which", "where", "as", "if", "when"
    ]
    if words and words[-1] in dangling_endings:
        return True, f"Trailing dangling word: '{words[-1]}'"

    # 3. Unfinished introductory dependent clauses ending in ellipsis or truncated (< 8 words)
    intro_dependent_starters = [
        "so the next time", "the next time", "next time",
        "whenever you", "when you", "if you ever", "because when",
        "as if you", "just like when", "while you"
    ]
    ends_in_ellipsis = clean.endswith("...") or clean.endswith("…")
    for starter in intro_dependent_starters:
        if lower.startswith(starter):
            has_clause_break = any(p in clean for p in [",", "—", ";", " - "])
            # If it has no clause break and is short (< 8 words), or ends in ellipsis without main clause
            if not has_clause_break and (len(words) < 8 or ends_in_ellipsis):
                return True, f"Unfinished subordinate clause ending in dangling ellipsis: '{starter}...'"

    return False, ""


def _validate_iscg_scenes_boundary(scenes: Any) -> None:
    """
    Validates iterative Shorts scene output at the pipeline boundary.
    Enforces that scenes is a non-empty list of dictionaries, each containing
    a valid, non-empty, non-whitespace spoken_text string, and rejects incomplete
    or dangling trailing fragments.
    """
    if not isinstance(scenes, list):
        raise ValueError(
            f"Iterative script generation must produce a list of scenes, got: {type(scenes).__name__}"
        )
    if not scenes:
        raise ValueError("Iterative script generation produced an empty scene array.")
    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(
                f"Scene {idx + 1} is not a dictionary: got {type(scene).__name__}"
            )
        if "spoken_text" not in scene:
            raise ValueError(f"Scene {idx + 1} is missing required 'spoken_text' field")
        spoken = scene["spoken_text"]
        if not isinstance(spoken, str):
            raise ValueError(
                f"Scene {idx + 1} 'spoken_text' must be a string, got {type(spoken).__name__}"
            )
        if not spoken.strip():
            raise ValueError(f"Scene {idx + 1} has empty or whitespace-only 'spoken_text'")

        is_dangling, reason = is_dangling_or_incomplete_sentence(spoken)
        if is_dangling:
            raise ValueError(
                f"Script completion validation failed: Scene {idx + 1} has an incomplete or dangling ending ({reason}): '{spoken}'"
            )


# ─── FUZZY SEMANTIC DEDUPLICATION (JACCARD) ───────────────────────────────────

def are_thoughts_similar(text_a: str, text_b: str, threshold: float = 0.45) -> bool:
    """
    Calculates Jaccard similarity of content words between two sentences.
    Catches 1-word differences (e.g. 'just to be blocked by you' vs 'to be blocked by you')
    and minor punctuation/case variations.
    """
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "it", "to", "for", "of",
        "in", "on", "at", "by", "that", "this", "you", "your", "just", "so",
        "be", "with", "and", "or", "as", "if", "its", "then", "from"
    }
    words_a = {w for w in re.findall(r"\b\w+\b", text_a.lower()) if w not in stopwords}
    words_b = {w for w in re.findall(r"\b\w+\b", text_b.lower()) if w not in stopwords}
    if not words_a or not words_b:
        return False
    return (len(words_a & words_b) / len(words_a | words_b)) >= threshold


# ─── YOUTUBE POLICY SAFETY WORD GATE ──────────────────────────────────────────

YOUTUBE_POLICY_BANNED_WORDS = {
    "suicide", "kill yourself", "slaughter", "murder", "terrorist", "nazi",
    "rape", "pedophile", "child abuse", "behead", "massacre"
}


# ─── PROMPT RULES HELPER ──────────────────────────────────────────────────────

def apply_prompt_rules(system_prompt: str, user_prompt: str, channel_cfg: Dict[str, Any]) -> tuple:
    """
    Augments the generated prompts with any channel-specific rules from channel_config.yaml.
    Supports both prompt_settings and legacy prompt_rules sections.
    Guarantees idempotency: repeated calls will not accumulate duplicate instructions.
    """
    rules = channel_cfg.get("prompt_settings", channel_cfg.get("prompt_rules", {}))

    # 1. Enforce virality reminder
    if rules.get("enforce_virality", True):
        virality_clause = (
            "VIRALITY ENFORCEMENT: Every scene must be instantly shareable, "
            "psychologically shocking, and optimised for maximum scroll-stop retention."
        )
        if virality_clause not in system_prompt:
            system_prompt += f"\n\n{virality_clause}"

    # 2. Extra freeform user instruction
    extra = (rules.get("extra_instructions") or "").strip()
    if extra:
        extra_clause = f"ADDITIONAL CHANNEL INSTRUCTION: {extra}"
        if extra_clause not in user_prompt:
            user_prompt += f"\n\n{extra_clause}"

    # 3. Extra banned phrases
    banned: List[str] = rules.get("banned_phrases", [])
    if banned:
        joined = ", ".join(f'"{p}"' for p in banned)
        banned_clause = f"EXTRA BANNED PHRASES (channel-specific): {joined}. Never use these."
        if banned_clause not in system_prompt:
            system_prompt += f"\n\n{banned_clause}"

    return system_prompt, user_prompt


def apply_prompt_rules_to_config(prompts_cfg: Dict[str, Any], channel_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies channel-specific prompt rules (virality enforcement, extra instructions,
    and banned phrases) from channel_config.yaml to active Shorts prompt templates.
    Guarantees idempotency: repeated calls will not accumulate duplicate instructions.
    """
    if not isinstance(prompts_cfg, dict):
        return prompts_cfg

    import copy
    patched = copy.deepcopy(prompts_cfg)
    rules = channel_cfg.get("prompt_settings", channel_cfg.get("prompt_rules", {}))
    extra = (rules.get("extra_instructions") or "").strip()

    # Active creative prompts for YouTube Shorts
    active_keys = ["triplet_anchor_scenes", "thought_scene", "paired_anchor_scene"]
    for key in active_keys:
        if key in patched and isinstance(patched[key], dict):
            entry = patched[key]
            sys_p = entry.get("system_prompt", "")
            sys_p, _ = apply_prompt_rules(sys_p, "", channel_cfg)
            if extra:
                extra_clause = f"ADDITIONAL CHANNEL INSTRUCTION: {extra}"
                if extra_clause not in sys_p:
                    sys_p += f"\n\n{extra_clause}"
            entry["system_prompt"] = sys_p

    if "script_gen" in patched and isinstance(patched["script_gen"], dict):
        entry = patched["script_gen"]
        sys_p = entry.get("system_prompt", "")
        usr_p = entry.get("user_template", "")
        sys_p, usr_p = apply_prompt_rules(sys_p, usr_p, channel_cfg)
        entry["system_prompt"] = sys_p
        entry["user_template"] = usr_p

    # Active editorial revision prompt for YouTube Shorts:
    # Propagates channel-specific banned phrases and extra instructions without
    # injecting generic virality language (which conflicts with grounded editorial repairs).
    if "editorial_revision" in patched:
        entry = patched["editorial_revision"]
        is_dict = isinstance(entry, dict)
        sys_p = (entry.get("system_prompt", "") if is_dict else entry) if (is_dict or isinstance(entry, str)) else ""
        if sys_p and isinstance(sys_p, str):
            banned = rules.get("banned_phrases", [])
            if banned:
                joined = ", ".join(f'"{p}"' for p in banned if p)
                if joined:
                    banned_clause = f"EXTRA BANNED PHRASES (channel-specific): {joined}. Never use these."
                    if banned_clause not in sys_p:
                        sys_p += f"\n\n{banned_clause}"
            if extra:
                extra_clause = f"ADDITIONAL CHANNEL INSTRUCTION: {extra}"
                if extra_clause not in sys_p:
                    sys_p += f"\n\n{extra_clause}"
            if is_dict:
                entry["system_prompt"] = sys_p
            else:
                patched["editorial_revision"] = sys_p

    # Active SEO metadata generation prompt for YouTube Shorts:
    # Propagates channel-specific banned phrases and extra instructions without
    # injecting generic virality language (preserving accurate and grounded metadata).
    if "seo_gen" in patched:
        entry = patched["seo_gen"]
        is_dict = isinstance(entry, dict)
        sys_p = (entry.get("system_prompt", "") if is_dict else entry) if (is_dict or isinstance(entry, str)) else ""
        if sys_p and isinstance(sys_p, str):
            banned = rules.get("banned_phrases", [])
            if banned:
                joined = ", ".join(f'"{p}"' for p in banned if p)
                if joined:
                    banned_clause = f"EXTRA BANNED PHRASES (channel-specific): {joined}. Never use these."
                    if banned_clause not in sys_p:
                        sys_p += f"\n\n{banned_clause}"
            if extra:
                extra_clause = f"ADDITIONAL CHANNEL INSTRUCTION: {extra}"
                if extra_clause not in sys_p:
                    sys_p += f"\n\n{extra_clause}"
            if is_dict:
                entry["system_prompt"] = sys_p
            else:
                patched["seo_gen"] = sys_p

    # Active audio voiceover polisher prompt for YouTube Shorts:
    # Propagates channel-specific banned phrases and extra instructions without
    # injecting generic virality language (preserving natural conversational voice).
    if "script_polish" in patched:
        entry = patched["script_polish"]
        is_dict = isinstance(entry, dict)
        sys_p = (entry.get("system_prompt", "") if is_dict else entry) if (is_dict or isinstance(entry, str)) else ""
        if sys_p and isinstance(sys_p, str):
            banned = rules.get("banned_phrases", [])
            if banned:
                joined = ", ".join(f'"{p}"' for p in banned if p)
                if joined:
                    banned_clause = f"EXTRA BANNED PHRASES (channel-specific): {joined}. Never use these."
                    if banned_clause not in sys_p:
                        sys_p += f"\n\n{banned_clause}"
            if extra:
                extra_clause = f"ADDITIONAL CHANNEL INSTRUCTION: {extra}"
                if extra_clause not in sys_p:
                    sys_p += f"\n\n{extra_clause}"
            if is_dict:
                entry["system_prompt"] = sys_p
            else:
                patched["script_polish"] = sys_p

    return patched


# ─── SEO KEYWORD EXTRACTOR ────────────────────────────────────────────────────

def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """
    Lightweight noun/keyword extractor using only stdlib (no spaCy / NLTK required).
    Splits on whitespace, strips punctuation, removes stopwords, and deduplicates.
    """
    STOPWORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "is", "it", "this", "that", "you", "your", "i", "we",
        "they", "he", "she", "are", "was", "were", "be", "been", "have", "has",
        "had", "do", "does", "did", "not", "so", "as", "if", "by", "from",
        "can", "will", "just", "its", "into", "than", "then", "there", "when",
        "which", "who", "what", "how", "why", "any", "all", "also", "because",
        "more", "most", "over", "about", "after", "before", "every", "never",
        "only", "same", "our", "my", "their", "would", "could", "should",
    }
    words = re.findall(r"[a-zA-Z]{4,}", text)
    seen: set = set()
    keywords: List[str] = []
    for w in words:
        lw = w.lower()
        if lw not in STOPWORDS and lw not in seen:
            seen.add(lw)
            keywords.append(lw)
        if len(keywords) >= max_keywords:
            break
    return keywords


# ─── SHORT SCRIPT CALIBRATOR & WORD BUDGET GUARD ──────────────────────────────

def calibrate_and_guard_script(
    raw_scenes: List[Dict[str, Any]],
    prompt_settings: Dict[str, Any],
    target_duration: float = 55.0
) -> List[Dict[str, Any]]:
    """
    Calibrates, re-segments, trims, and guards scene scripts for Shorts before TTS synthesis.

    Guarantees:
    - Multi-sentence scenes are re-segmented into individual standalone thoughts.
    - Over-budget scripts (>185 words) are trimmed safely without losing Hook or Loop bridge.
    - Under-budget scripts (<145 words or <9 middle scenes) raise ValueError; canned thought injection is prohibited.
    - Duplicate scenes within the script raise ValueError; canned thought substitution is prohibited.
    - Loop outro repeating hook raises ValueError; canned bridge injection is prohibited.
    - Hook is clean (no leading punctuation, capitalized).
    - Loop bridge ends with continuation ellipsis '...'.
    """
    if not raw_scenes:
        return raw_scenes

    if len(raw_scenes) < 3:
        raise ValueError(
            f"Script calibration failed: insufficient scene count (expected at least 3 scenes, got {len(raw_scenes)}). Canned thought injection is prohibited."
        )

    # 1. Clean Hook opening
    raw_scenes[0]["spoken_text"] = re.sub(r"^[\.\s…\-]+", "", raw_scenes[0].get("spoken_text", "")).strip()
    if raw_scenes[0]["spoken_text"] and raw_scenes[0]["spoken_text"][0].islower():
        raw_scenes[0]["spoken_text"] = raw_scenes[0]["spoken_text"][0].upper() + raw_scenes[0]["spoken_text"][1:]

    # 2. Re-segment multi-sentence scenes if scene count is low (< 11)
    if len(raw_scenes) < 11:
        split_scenes = []
        for sc in raw_scenes:
            txt = sc.get("spoken_text", "").strip()
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', txt) if s.strip()]
            if len(sentences) > 1 and len(split_scenes) < 13:
                for s_txt in sentences:
                    split_scenes.append({
                        "scene_id": len(split_scenes) + 1,
                        "spoken_text": s_txt,
                        "stock_video_query": sc.get("stock_video_query", "mind bending psychological realization")
                    })
            else:
                split_scenes.append(sc)
        if len(split_scenes) > len(raw_scenes):
            print(f"✂️ [SCRIPT RESEGMENT] Re-segmented {len(raw_scenes)} multi-sentence scenes into {len(split_scenes)} individual thought scenes.", flush=True)
            raw_scenes = split_scenes

    # 3. Separate loop scene from middle scenes
    loop_scene = raw_scenes[-1]
    mid_scenes = list(raw_scenes[:-1])

    def _calc_words(s_list, loop_sc):
        return sum(len(s.get("spoken_text", "").split()) for s in s_list) + len(loop_sc.get("spoken_text", "").split())

    total_words = _calc_words(mid_scenes, loop_scene)

    # 4. Dynamic Word Budget Trimming (Guaranteed <= 180 words to keep under 59s ceiling)
    if total_words > 185:
        orig_words = total_words
        orig_count = len(mid_scenes) + 1
        while len(mid_scenes) > 10 and total_words > 175:
            popped = mid_scenes.pop()
            total_words -= len(popped.get("spoken_text", "").split())

        if total_words > 185:
            for sc in mid_scenes[1:]:  # preserve hook
                w_list = sc.get("spoken_text", "").split()
                if len(w_list) > 15:
                    sc["spoken_text"] = " ".join(w_list[:15]).rstrip(",;:- ") + "."
                    total_words = _calc_words(mid_scenes, loop_scene)
                    if total_words <= 175:
                        break

        print(f"✂️ [SCRIPT TRIM] Trimmed over-budget script from {orig_words} words ({orig_count} scenes) down to {total_words} words ({len(mid_scenes) + 1} scenes) for natural pacing.", flush=True)

    # 5. Enforce Word & Scene Budget (Under-budget check - canned expansion strictly prohibited)
    elif total_words < 145 or len(mid_scenes) < 9:
        raise ValueError(
            f"Script calibration failed: insufficient generated content ({total_words} words across {len(mid_scenes) + 1} scenes; expected minimum 145 words and 10 scenes). Canned thought injection is prohibited."
        )

    # 6. Reassemble & Intra-Script Deduplication Check
    raw_scenes = mid_scenes + [loop_scene]
    deduped_scenes = []
    for idx, s in enumerate(raw_scenes):
        is_duplicate = any(are_thoughts_similar(s.get("spoken_text", ""), prev.get("spoken_text", "")) for prev in deduped_scenes)
        if is_duplicate and s != raw_scenes[-1] and s != raw_scenes[0]:
            raise ValueError(
                f"Script calibration failed: duplicate scene detected in script at Scene {idx + 1}: '{s.get('spoken_text', '')[:60]}...'. Canned thought substitution is prohibited."
            )
        deduped_scenes.append(s)
    raw_scenes = deduped_scenes

    # 6b. Guard against Loop Outro repeating Scene 1 Hook
    if len(raw_scenes) >= 2:
        from engine.managers.editorial_critic import check_loop_repeats_hook
        repeats, reason = check_loop_repeats_hook(raw_scenes[-1].get("spoken_text", ""), raw_scenes[0].get("spoken_text", ""))
        if repeats or are_thoughts_similar(raw_scenes[-1].get("spoken_text", ""), raw_scenes[0].get("spoken_text", "")):
            raise ValueError(
                f"Script calibration failed: loop outro repeats words from hook ({reason}). Canned bridge injection is prohibited."
            )

    # 7. Seamless circular loop ending
    last_text = raw_scenes[-1]["spoken_text"].rstrip(".!? ")
    if not last_text.endswith("..."):
        raw_scenes[-1]["spoken_text"] = f"{last_text}..."

    # 8. Re-index scene_id sequentially
    for i, sc in enumerate(raw_scenes):
        sc["scene_id"] = i + 1

    final_words = sum(len(s.get("spoken_text", "").split()) for s in raw_scenes)
    print(f"🎯 [SCRIPT CALIBRATED] Final script locked at {len(raw_scenes)} scenes and {final_words} words (~{final_words / 3.25:.1f}s expected narration).", flush=True)
    return raw_scenes


# ─── CLAIM FACTUALITY POLICY & REWRITE HELPERS (SHORTS ONLY) ─────────────────

class FactualityPolicyStatus(str, Enum):
    """Integration-level decision status for Shorts factuality inspection."""
    PASSED = "PASSED"
    PASSED_WITH_UNVERIFIED = "PASSED_WITH_UNVERIFIED"
    REJECTED_CONTRADICTION = "REJECTED_CONTRADICTION"
    REJECTED_HIGH_RISK_UNVERIFIED = "REJECTED_HIGH_RISK_UNVERIFIED"
    REJECTED_MEDIUM_RISK_UNVERIFIED = "REJECTED_MEDIUM_RISK_UNVERIFIED"
    VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"


_LAST_CLAIM_INSPECTION_REPORT: Any = None
_LAST_FACTUALITY_DECISION: Optional[Tuple[FactualityPolicyStatus, str]] = None


def get_last_claim_report() -> Any:
    """Returns the in-memory claim inspection report from the most recent run."""
    return _LAST_CLAIM_INSPECTION_REPORT


def get_last_factuality_decision() -> Optional[Tuple[FactualityPolicyStatus, str]]:
    """Returns the in-memory factuality policy decision from the most recent run."""
    return _LAST_FACTUALITY_DECISION


def evaluate_shorts_factuality_policy(
    report: Any
) -> Tuple[FactualityPolicyStatus, str, List[Tuple[int, Any]]]:
    """
    Evaluates an in-memory ClaimInspectionReport against the strict Shorts risk policy.
    Distinguishes evidence-backed vs model-assessed contradictions, enforces fail-closed
    behavior on high/medium risk unverified claims, and permits low-risk empirical claims
    under PASSED_WITH_UNVERIFIED.

    Returns:
        (status, reason_string, list_of_affected_claims_as_(scene_id, claim_record))
    """
    from engine.managers.claim_inspector import VerificationOutcome, RiskLevel

    claims = getattr(report, "claims", []) or []
    if not claims:
        return FactualityPolicyStatus.PASSED, "No claims to evaluate", []

    # 1. Contradicted claims (highest priority failure)
    contradicted_claims = [
        c for c in claims if getattr(c, "outcome", "") == VerificationOutcome.CONTRADICTED.value
    ]
    if contradicted_claims:
        affected = [(getattr(c, "scene_id", 1) or 1, c) for c in contradicted_claims]
        ev_backed = [c for c in contradicted_claims if getattr(c, "evidence", None)]
        model_assessed = [c for c in contradicted_claims if not getattr(c, "evidence", None)]
        if ev_backed:
            c_first = ev_backed[0]
            reason = (
                f"Evidence-backed contradiction in Scene {getattr(c_first, 'scene_id', 1)}: "
                f"{getattr(c_first, 'rationale', '')}"
            )
        else:
            c_first = model_assessed[0]
            reason = (
                f"Model-assessed contradiction in Scene {getattr(c_first, 'scene_id', 1)}: "
                f"{getattr(c_first, 'rationale', '')}"
            )
        return FactualityPolicyStatus.REJECTED_CONTRADICTION, reason, affected

    # 2. High-Risk unverified or unavailable claims (medical, toxicity, safety)
    high_risk_non_supported = [
        c for c in claims
        if getattr(c, "risk_level", "") == RiskLevel.HIGH.value
        and getattr(c, "outcome", "") not in (
            VerificationOutcome.SUPPORTED.value,
            VerificationOutcome.NOT_APPLICABLE.value
        )
    ]
    if high_risk_non_supported:
        affected = [(getattr(c, "scene_id", 1) or 1, c) for c in high_risk_non_supported]
        unavail = [
            c for c in high_risk_non_supported
            if getattr(c, "outcome", "") == VerificationOutcome.VERIFICATION_UNAVAILABLE.value
        ]
        if unavail:
            c_first = unavail[0]
            reason = (
                f"Verification service unavailable for high-risk claim in Scene {getattr(c_first, 'scene_id', 1)}: "
                f"{getattr(c_first, 'error_reason', '') or getattr(c_first, 'rationale', '')}"
            )
            return FactualityPolicyStatus.VERIFICATION_UNAVAILABLE, reason, affected
        c_first = high_risk_non_supported[0]
        reason = (
            f"High-risk empirical claim unverifiable in Scene {getattr(c_first, 'scene_id', 1)}: "
            f"{getattr(c_first, 'rationale', '')}"
        )
        return FactualityPolicyStatus.REJECTED_HIGH_RISK_UNVERIFIED, reason, affected

    # 3. Medium-Risk unverified or unavailable claims (quantitative stats, percentages, dates)
    med_risk_non_supported = [
        c for c in claims
        if getattr(c, "risk_level", "") == RiskLevel.MEDIUM.value
        and getattr(c, "outcome", "") not in (
            VerificationOutcome.SUPPORTED.value,
            VerificationOutcome.NOT_APPLICABLE.value
        )
    ]
    if med_risk_non_supported:
        affected = [(getattr(c, "scene_id", 1) or 1, c) for c in med_risk_non_supported]
        unavail = [
            c for c in med_risk_non_supported
            if getattr(c, "outcome", "") == VerificationOutcome.VERIFICATION_UNAVAILABLE.value
        ]
        if unavail:
            c_first = unavail[0]
            reason = (
                f"Verification service unavailable for medium-risk claim in Scene {getattr(c_first, 'scene_id', 1)}: "
                f"{getattr(c_first, 'error_reason', '') or getattr(c_first, 'rationale', '')}"
            )
            return FactualityPolicyStatus.VERIFICATION_UNAVAILABLE, reason, affected
        c_first = med_risk_non_supported[0]
        reason = (
            f"Medium-risk quantitative/date claim unverifiable in Scene {getattr(c_first, 'scene_id', 1)}: "
            f"{getattr(c_first, 'rationale', '')}"
        )
        return FactualityPolicyStatus.REJECTED_MEDIUM_RISK_UNVERIFIED, reason, affected

    # 4. Low-Risk unverified, ambiguous, or unavailable claims (everyday observations)
    low_risk_unverified = [
        c for c in claims
        if getattr(c, "risk_level", "") == RiskLevel.LOW.value
        and getattr(c, "outcome", "") in (
            VerificationOutcome.UNVERIFIABLE.value,
            VerificationOutcome.VERIFICATION_UNAVAILABLE.value,
            VerificationOutcome.AMBIGUOUS.value
        )
    ]
    if low_risk_unverified:
        reason = f"Approved under low-risk policy ({len(low_risk_unverified)} unverified everyday claim(s))"
        return FactualityPolicyStatus.PASSED_WITH_UNVERIFIED, reason, []

    # 5. All empirical claims supported, and subjective/metaphorical exempt
    return FactualityPolicyStatus.PASSED, f"All {len(claims)} claim(s) supported or exempt", []


def _rewrite_scene_for_factuality(
    scene: Dict[str, Any],
    claim_record: Any,
    llm: Optional[Any] = None,
    topic: Optional[str] = None,
    candidate_evidence: Optional[List[Any]] = None,
    **kwargs: Any
) -> Optional[Dict[str, Any]]:
    """
    Executes a targeted single-scene LLM rewrite to resolve an identified factuality defect.
    Preserves original meaning, intended narrative tone, and requested topic while grounding
    assertions in candidate evidence and enforcing natural spoken voice.
    """
    if llm is None:
        return None

    prop = getattr(claim_record, "extracted_proposition", "") or getattr(claim_record, "original_text", "")
    risk = getattr(claim_record, "risk_level", "low")
    rationale = getattr(claim_record, "rationale", "")
    outcome = getattr(claim_record, "outcome", "")
    claim_ev = getattr(claim_record, "evidence", []) or []

    # Gather available grounding evidence without fabricating citations
    evidence_pool: List[str] = []
    for ev in (list(claim_ev) + list(candidate_evidence or [])):
        if hasattr(ev, "text") and ev.text:
            txt = ev.text.strip()
        elif isinstance(ev, dict) and (ev.get("text") or ev.get("fact")):
            txt = str(ev.get("text") or ev.get("fact")).strip()
        elif isinstance(ev, str) and ev.strip():
            txt = ev.strip()
        else:
            continue
        if txt and txt not in evidence_pool:
            evidence_pool.append(txt)

    if evidence_pool:
        evidence_lines = [f"- [Evidence #{i+1}] {t}" for i, t in enumerate(evidence_pool[:5])]
        evidence_block = "\n".join(evidence_lines)
    else:
        evidence_block = "None available. (No verified candidate evidence provided; rephrase without unsupported empirical numbers or claims.)"

    topic_str = str(topic or "Intended Topic").strip()

    sys_prompt = (
        "You are an expert factual script editor for YouTube Shorts.\n"
        "Revise the given scene spoken text to resolve the identified factuality defect while preserving the hook, engagement, narrative flow, and topic relevance.\n\n"
        "FACTUALITY & GROUNDING EDITORIAL RULES:\n"
        f"1. TOPIC PRESERVATION: The revised scene MUST strictly preserve and stay relevant to the intended topic: '{topic_str}'. Do NOT pivot to an unrelated subject or substitute unrelated trivia.\n"
        "2. CONTRADICTIONS: If the assertion is contradicted by reality or evidence, replace it with verified, undeniable reality relevant to the topic.\n"
        "3. UNVERIFIED EMPIRICAL CLAIMS:\n"
        "   - If grounding evidence is provided below, you may base an empirical claim directly on that provided evidence.\n"
        "   - If NO supporting evidence is provided, rephrase the line as a relatable observation, perceptual question, introspective realization, or qualitative insight WITHOUT asserting unverified numbers, percentages, physical constants, medical/neurological claims, or speculative scientific mechanisms (such as ungrounded brain vetoes, psychiatric delusions, or resonance physics). Ground the line in undeniable everyday reality or relatable human experience while preserving the topic.\n"
        "4. NO FABRICATION: Do not invent supporting citations, statistics, or empirical claims not grounded in the provided evidence.\n"
        "5. VISUAL PHENOMENA ACCURACY: Distinguish visual perception phenomena accurately. Chronostasis (the stopped-clock illusion) strictly occurs upon rapid eye movement (saccade) when shifting gaze to a clock, NOT from continuous prolonged staring without eye movement (which causes Troxler fading or neural adaptation). Do not attribute chronostasis to prolonged fixed viewing.\n"
        "6. SCIENTIFIC HYPOTHESES: Do NOT state unproven biological theories (such as the brain-cooling hypothesis of yawning) as established absolute facts. State them as hypotheses or theories (e.g. 'one leading hypothesis suggests...', 'scientists theorize...') or rephrase as relatable everyday observations.\n"
        "7. SCRIPT COMPLETION: Every revised scene MUST be a grammatically complete, natural sentence. Never leave an unfinished subordinate clause or dangling ellipsis.\n\n"
        "NATURAL-VOICE EDITORIAL GUIDANCE:\n"
        "1. Conversational realism: Deliver the correction in natural spoken English as if an observant person were speaking directly to a friend.\n"
        "2. Direct observation: State facts and realities directly rather than adopting formal citations, clinical hedging, or textbook phrasing.\n"
        "3. Immediate immersion: Enter the core realization immediately without throat-clearing introductions, rhetorical signposts, or inflated hype.\n"
        "4. Spoken cadence: Keep the revised sentence grounded, curious, and rhythmically punchy for speech synthesis.\n"
        '5. Return ONLY valid JSON: {"spoken_text": "<revised text>", "stock_video_query": "<visual query>"}'
    )
    user_prompt = (
        f"Intended Topic: \"{topic_str}\"\n\n"
        f"Original Scene Spoken Text:\n\"{scene.get('spoken_text', '')}\"\n\n"
        f"Problematic Assertion:\n\"{prop}\" (Risk Level: {risk}, Outcome: {outcome})\n\n"
        f"Factuality Defect:\n{rationale}\n\n"
        f"Available Grounding Evidence:\n{evidence_block}\n\n"
        f"Revise the scene spoken text to resolve the defect, preserve topic '{topic_str}', and remain natural and factually accurate:"
    )

    try:
        res = llm.generate_json(sys_prompt, user_prompt, temperature=0.7, task_name="factuality_rewrite")
        if not isinstance(res, dict):
            return None
        candidate_text = (res.get("spoken_text") or res.get("text") or "").strip()
        candidate_text = re.sub(r'^["\']|["\']$', "", candidate_text).strip()
        if not candidate_text:
            return None

        # Ending structure preservation:
        orig_text = scene.get("spoken_text", "").strip()
        if orig_text.endswith("..."):
            if not candidate_text.endswith("..."):
                candidate_text = candidate_text.rstrip(".!? ") + "..."
        else:
            if candidate_text.endswith("..."):
                candidate_text = candidate_text.rstrip(".!? ") + "."
            elif not (candidate_text.endswith(".") or candidate_text.endswith("!") or candidate_text.endswith("?")):
                candidate_text = candidate_text.rstrip(" ,-—") + "."

        revised = dict(scene)
        revised["spoken_text"] = candidate_text
        from engine.managers.voice_normalizer import VoiceNormalizer
        revised["phonetic_text"] = VoiceNormalizer.normalize_text(candidate_text)
        if res.get("stock_video_query"):
            revised["stock_video_query"] = res["stock_video_query"]
        revised["_factuality_revised"] = True
        return revised
    except Exception as e:
        print(f"⚠️  [CLAIM INSPECTOR] Targeted scene rewrite failed: {e}", flush=True)
        return None


def _validate_and_refine_claims(
    raw_scenes: List[Dict[str, Any]],
    topic: str,
    claim_inspector: Any,
    llm: Optional[Any] = None,
    grounding_refs: Optional[List[Any]] = None,
    channel_premise: str = "",
    prompts_cfg: Optional[Dict[str, Any]] = None,
    script_data: Optional[Dict[str, Any]] = None,
    max_rewrites_per_scene: int = 2
) -> Tuple[List[Dict[str, Any]], Any, Tuple[FactualityPolicyStatus, str], bool]:
    """
    Validates scene-chain factuality via ClaimInspector and coordinates targeted rewrites.
    Grounds rewrites with available evidence, preserves the intended topic, enforces
    fail-closed policy on unresolved empirical claims, and reports explicit diagnosable
    outcomes on rewrite exhaustion.
    """
    global _LAST_CLAIM_INSPECTION_REPORT, _LAST_FACTUALITY_DECISION

    scene_factuality_rewrite_counts: Dict[int, int] = {}
    final_factuality_report = None
    final_factuality_decision = None
    rewrote_any = False

    while True:
        # 1. Inspect the candidate scene chain
        final_factuality_report = claim_inspector.inspect_script(
            raw_scenes,
            candidate_evidence=grounding_refs
        )
        decision, decision_reason, affected_claims = evaluate_shorts_factuality_policy(final_factuality_report)
        final_factuality_decision = (decision, decision_reason)
        _LAST_CLAIM_INSPECTION_REPORT = final_factuality_report
        _LAST_FACTUALITY_DECISION = final_factuality_decision

        if decision in (FactualityPolicyStatus.PASSED, FactualityPolicyStatus.PASSED_WITH_UNVERIFIED):
            if decision == FactualityPolicyStatus.PASSED_WITH_UNVERIFIED:
                print(f"⚠️  [CLAIM INSPECTOR] Script approved under low-risk policy ({decision_reason})", flush=True)
            else:
                print(f"✅ [CLAIM INSPECTOR] Script passed factuality verification ({decision_reason})", flush=True)
            return raw_scenes, final_factuality_report, final_factuality_decision, rewrote_any

        # 2. Policy rejection: evaluate if rewrite budget allows targeted correction
        scenes_to_rewrite: List[Tuple[int, Any]] = []
        for s_id, c_rec in affected_claims:
            if s_id and 1 <= s_id <= len(raw_scenes) and scene_factuality_rewrite_counts.get(s_id, 0) < max_rewrites_per_scene:
                if not any(s[0] == s_id for s in scenes_to_rewrite):
                    scenes_to_rewrite.append((s_id, c_rec))

        if not scenes_to_rewrite or llm is None:
            # Budget exhausted or no LLM available -> fail closed with rich diagnostics
            exhausted_details = []
            for s_id, c_rec in affected_claims:
                attempts = scene_factuality_rewrite_counts.get(s_id, 0)
                prop = getattr(c_rec, "extracted_proposition", "") or getattr(c_rec, "original_text", "")
                risk = getattr(c_rec, "risk_level", "unknown")
                exhausted_details.append(f"[Scene {s_id} | {attempts}/{max_rewrites_per_scene} attempts | Risk: {risk} | Claim: '{prop}']")
            diag_str = " ".join(exhausted_details) if exhausted_details else "No rewrite attempts remaining"

            is_exhausted = any(
                scene_factuality_rewrite_counts.get(s[0], 0) >= max_rewrites_per_scene
                for s in affected_claims
            )
            if is_exhausted:
                raise ValueError(
                    f"Claim Inspector rejected script ({decision.value}): {decision_reason} (Rewrite budget exhausted: {diag_str})"
                )
            else:
                raise ValueError(
                    f"Claim Inspector rejected script ({decision.value}): {decision_reason}"
                )

        # 3. Perform targeted rewrites for eligible affected scenes
        rewrote_this_pass = False
        import inspect
        sig = inspect.signature(_rewrite_scene_for_factuality)
        supports_kwargs = "topic" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )

        for s_id, c_rec in scenes_to_rewrite:
            scene_idx = s_id - 1
            scene_factuality_rewrite_counts[s_id] = scene_factuality_rewrite_counts.get(s_id, 0) + 1
            print(
                f"🔄 [CLAIM INSPECTOR] Rewriting Scene {s_id} for factuality "
                f"(attempt {scene_factuality_rewrite_counts[s_id]}/{max_rewrites_per_scene}): "
                f"{getattr(c_rec, 'rationale', '')[:60]}...",
                flush=True
            )
            if supports_kwargs:
                revised_sc = _rewrite_scene_for_factuality(
                    scene=raw_scenes[scene_idx],
                    claim_record=c_rec,
                    llm=llm,
                    topic=topic,
                    candidate_evidence=grounding_refs
                )
            else:
                revised_sc = _rewrite_scene_for_factuality(
                    scene=raw_scenes[scene_idx],
                    claim_record=c_rec,
                    llm=llm
                )
            if revised_sc:
                raw_scenes[scene_idx] = revised_sc
                rewrote_this_pass = True
                rewrote_any = True

        if not rewrote_this_pass:
            raise ValueError(
                f"Claim Inspector rejected script ({decision.value}): {decision_reason}"
            )

        # 4. Critical invariant: Re-run Editorial Critic after any text mutation
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from engine.managers.editorial_critic import audit_and_refine_spec
                _title_from_script = ""
                if script_data:
                    _title_from_script = script_data.get("seo", {}).get("title") or script_data.get("title", topic)
                else:
                    _title_from_script = topic
                _seo_for_critic = {"title": _title_from_script}
                raw_scenes, _seo_for_critic, audit_summary = audit_and_refine_spec(
                    raw_scenes=raw_scenes,
                    seo_data=_seo_for_critic,
                    topic=topic,
                    llm_manager=llm,
                    channel_premise=channel_premise,
                    prompts_cfg=prompts_cfg
                )
                if audit_summary.get("status") == "rejected" or audit_summary.get("unresolved_failures", 0) > 0:
                    raise ValueError(
                        f"Editorial Critic rejected script after factuality rewrite: {audit_summary.get('unresolved_failures', 0)} unresolvable defect(s)"
                    )
                if script_data and _seo_for_critic.get("title") and _seo_for_critic["title"] != _title_from_script:
                    new_aligned_title = _seo_for_critic["title"]
                    from engine.managers.iterative_script_generator import synchronize_seo_description_header
                    if "seo" in script_data and isinstance(script_data["seo"], dict):
                        script_data["seo"]["title"] = new_aligned_title
                        if "description" in script_data["seo"]:
                            script_data["seo"]["description"] = synchronize_seo_description_header(
                                description=script_data["seo"]["description"],
                                old_title=_title_from_script,
                                new_title=new_aligned_title
                            )
                    elif "title" in script_data:
                        script_data["title"] = new_aligned_title
                        if "description" in script_data:
                            script_data["description"] = synchronize_seo_description_header(
                                description=script_data["description"],
                                old_title=_title_from_script,
                                new_title=new_aligned_title
                            )
            except ValueError:
                raise
            except Exception as critic_err:
                print(f"⚠️  [EDITORIAL CRITIC] Post-factuality audit failed: {critic_err}", flush=True)


def run_spec_stage(video_type: str = "short", custom_topic: Optional[str] = None) -> None:
    """Executes Stage 1: 🚀 Init & Spec Generation."""
    full_channel_cfg = load_yaml("config/channel_config.yaml")
    channel_cfg = full_channel_cfg["channel"]
    settings_cfg = load_yaml("config/settings.yaml")
    prompts_cfg = load_yaml("config/prompts.yaml")
    weights = HealthManager.load_dynamic_weights()
    HealthManager.check_and_sync_models()

    llm = LLMManager()
    inspector = TopicInspector(llm_manager=llm)

    target_duration = settings_cfg.get("video_profiles", {}).get(video_type, {}).get("target_duration", 600 if video_type == "long" else 55)

    if video_type == "long":
        sub_format = "documentary_essay"
        topic_info = inspector.discover_verified_topic(channel_cfg.get("niche", "psychology_and_facts"), video_type="long")
        topic = topic_info["topic"]
        source = topic_info.get("source", "trend")
        script_cfg = prompts_cfg.get("long_form_doc", prompts_cfg["script_gen"])
    else:
        # For Shorts: STRICTLY lock sub-format to "shower_thoughts_listicle" (12-15 rapid-fire thoughts, 50-58s)
        # Avoid rolling core_brainblud for shorts which is only 5 scenes / 25s
        sub_format = "shower_thoughts_listicle"

        # 1. Discover topic (Competitor Spy -> Topic Inspector)
        surge = CompetitorSpy.get_surge_topic(settings_cfg.get("competitors", []))
        surge_approved = False
        if surge and not inspector.is_topic_recent(surge.get("title", "")):
            surge_title = surge.get("title", "").strip()
            surge_niche = channel_cfg.get("niche", "shower_thoughts")
            fact_check = inspector._fact_check(surge_title, niche=surge_niche)
            if fact_check.get("verified", False):
                topic = surge_title
                source = "competitor_surge"
                surge_approved = True
                if not is_test_run():
                    inspector.record_topic_usage(topic, fact_check.get("summary", topic), niche=surge_niche)
            else:
                reason = fact_check.get("reason", "Failed factuality verification")
                print(f"⚠️ [COMPETITOR SPY] Surge topic '{surge_title}' not approved by factuality gate ({reason}). Falling back to topic discovery...", flush=True)

        if not surge_approved:
            if surge and inspector.is_topic_recent(surge.get("title", "")):
                print(f"🔄 [COMPETITOR SPY] Surge topic '{surge.get('title', '')}' was already used recently. Discovering fresh topic...")
            topic_info = inspector.discover_verified_topic(channel_cfg.get("niche", "shower_thoughts"), video_type="short")
            topic = topic_info["topic"]
            source = topic_info.get("source", "trend")
        script_cfg = prompts_cfg["script_gen"]

    custom_override = (custom_topic or os.environ.get("CUSTOM_TOPIC", "")).strip()
    if custom_override:
        custom_niche = channel_cfg.get("niche", "shower_thoughts" if video_type == "short" else "psychology_and_facts")
        fact_check = inspector._fact_check(custom_override, niche=custom_niche)
        if not fact_check.get("verified", False):
            status = fact_check.get("status", "unknown")
            reason = fact_check.get("reason", "Failed factuality verification")
            if status == "unavailable":
                raise ValueError(
                    f"Custom topic verification unavailable: '{custom_override}' ({reason})"
                )
            raise ValueError(
                f"Custom topic rejected by topic verification gate: '{custom_override}' ({reason})"
            )
        topic = custom_override
        source = "custom_dispatch"
        print(f"🎯 [SPEC] Using verified custom topic override: '{topic}'", flush=True)

    with StageTimer(PikaStage.SPEC, topic=topic):
        print(f"🎯 [SPEC] Topic: '{topic}' (Source: {source}, Format: {sub_format}, Type: {video_type})")

        # 2. Setup Context & Channel Configuration
        prompt_settings = full_channel_cfg.get("prompt_settings", full_channel_cfg.get("prompt_rules", {}))
        channel_premise = (prompt_settings.get("channel_premise") or "").strip()
        extra_instructions = (prompt_settings.get("extra_instructions") or "").strip()

        # Sourcing verified grounding references (real human facts/thoughts) for scriptwriter context
        grounding_refs = TopicInspector.get_grounding_references(count=5)
        if grounding_refs:
            grounding_lines = "\n".join(f"- [{r.get('type', 'fact').upper()}] {r.get('text', '')}" for r in grounding_refs)
            grounding_facts_section = f"VERIFIED INSPIRATION REFERENCES (adapt and weave these into the script):\n{grounding_lines}\n"
        else:
            grounding_facts_section = ""

        # Inject channel-specific prompt rules (virality enforcement, banned phrases, extra instructions)
        prompts_cfg = apply_prompt_rules_to_config(prompts_cfg, full_channel_cfg)

        # Load thought-cache for deduplication (persisted in channel_config.yaml)
        thought_cfg = _load_thought_cache(full_channel_cfg)

        raw_scenes = []
        script_data = {}

        if video_type == "short":
            # ─── ITERATIVE SCENE CHAIN GENERATION (ISCG) FOR SHORTS ────────────────
            # Sole authorized script generation path for YouTube Shorts.
            # No monolithic fallback: if iterative generation fails or returns empty, fail closed.
            from engine.managers.iterative_script_generator import IterativeScriptGenerator
            from engine.managers.llm_quality_tracker import LLMQualityTracker
            qt = LLMQualityTracker()
            generator = IterativeScriptGenerator(
                llm_manager=llm,
                quality_tracker=qt,
                prompts_cfg=prompts_cfg,
                channel_premise=channel_premise,
                channel_cfg=full_channel_cfg
            )
            raw_scenes, seo_dict = generator.generate_scene_chain(
                topic=topic,
                channel_premise=channel_premise,
                grounding_facts=grounding_facts_section
            )
            if not isinstance(raw_scenes, list):
                raise ValueError(
                    f"Iterative script generation must produce a list of scenes, got: {type(raw_scenes).__name__}"
                )

            # Normalize malformed punctuation artifacts and resolve any trailing dangling outro fragments
            for sc in raw_scenes:
                if isinstance(sc, dict):
                    txt = sc.get("spoken_text", "")
                    if isinstance(txt, str):
                        txt = re.sub(r"[…\.]{4,}", "...", txt).replace("…", "...")
                        sc["spoken_text"] = txt

            if raw_scenes and llm and isinstance(raw_scenes[-1], dict):
                last_sc = raw_scenes[-1]
                is_dang, _ = is_dangling_or_incomplete_sentence(last_sc.get("spoken_text", ""))
                if is_dang:
                    comp_prompt = (
                        "You are an expert script editor for YouTube Shorts.\n"
                        "The following trailing outro scene is an incomplete sentence or dangling fragment.\n"
                        "Complete it into a full, natural, grammatically complete closing sentence that resolves the thought with impact and cadence.\n"
                        "Return ONLY valid JSON: {\"spoken_text\": \"<completed sentence>\"}"
                    )
                    user_p = f"Incomplete Fragment: \"{last_sc.get('spoken_text', '')}\"\nTopic: \"{topic}\""
                    try:
                        c_res = llm.generate_json(comp_prompt, user_p, temperature=0.5, task_name="script_completion")
                        if isinstance(c_res, dict) and c_res.get("spoken_text"):
                            comp_text = c_res["spoken_text"].strip()
                            if comp_text and not is_dangling_or_incomplete_sentence(comp_text)[0]:
                                last_sc["spoken_text"] = comp_text
                                print(f"✨ [SCRIPT COMPLETION] Completed trailing outro fragment into: '{comp_text}'", flush=True)
                    except Exception as comp_err:
                        print(f"⚠️ [SCRIPT COMPLETION] Outro completion failed: {comp_err}", flush=True)

            _validate_iscg_scenes_boundary(raw_scenes)
            script_data = {
                "scenes": raw_scenes,
                "seo": seo_dict,
                "topic": topic
            }
        elif video_type == "long":
            # ─── MONOLITHIC DOCUMENTARY ESSAY GENERATION FOR LONG-FORM ─────────────
            # Load performance insights from memory/channel_performance.json if available
            perf_insight = ""
            perf_path = os.path.join("memory", "channel_performance.json")
            if os.path.exists(perf_path):
                try:
                    with open(perf_path, "r", encoding="utf-8") as f:
                        perf_data = json.load(f)
                    top_topic = perf_data.get("top_topic", "")
                    if top_topic:
                        perf_insight = f"AUDIENCE RETENTION INSIGHT: Prioritize cognitive glitch angles similar to high-performing theme: '{top_topic}'."
                except Exception:
                    pass

            system_prompt = script_cfg["system_prompt"]
            if "constitution" in script_cfg:
                system_prompt += "\n\n" + script_cfg["constitution"]
            if "few_shot_exemplars" in script_cfg:
                system_prompt += "\n\n" + script_cfg["few_shot_exemplars"]

            user_prompt = script_cfg["user_template"].format(
                channel_name=channel_cfg.get("name", "TOPATO"),
                niche=channel_cfg.get("niche", "shower_thoughts"),
                topic=topic,
                sub_format=sub_format,
                target_duration=target_duration,
                channel_premise=channel_premise,
                extra_instructions=extra_instructions,
                performance_insight=perf_insight,
                grounding_facts_section=grounding_facts_section
            )
            system_prompt, user_prompt = apply_prompt_rules(system_prompt, user_prompt, full_channel_cfg)

            script_data = llm.generate_json(
                system_prompt,
                user_prompt,
                temperature=0.7,
                validator=None,
                task_name="generic"
            )

            raw_scenes = script_data.get("scenes", [])
            if not raw_scenes and "chapters" in script_data:
                # Flatten scenes from chapters
                raw_scenes = []
                for ch in script_data.get("chapters", []):
                    raw_scenes.extend(ch.get("scenes", []))

            if not raw_scenes:
                raise ValueError("LLM generated empty scene array.")
        else:
            raise ValueError(f"Unsupported video_type: {video_type}")

        # ─── EDITORIAL CRITIC AUDIT (Wall Test + Title Alignment + Hook Check) ────
        # Runs after calibration to enforce @BrainBlud quality standards.
        # Never run in pytest to keep unit tests fast and deterministic.
        if video_type == "short" and not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from engine.managers.editorial_critic import audit_and_refine_spec
                # Build seo_data from what we have so far (title may come from script or will be SEO-generated later)
                _title_from_script = script_data.get("seo", {}).get("title") or script_data.get("title", topic)
                _seo_for_critic = {"title": _title_from_script}
                raw_scenes, _seo_for_critic, audit_summary = audit_and_refine_spec(
                    raw_scenes=raw_scenes,
                    seo_data=_seo_for_critic,
                    topic=topic,
                    llm_manager=llm,
                    channel_premise=channel_premise,
                    prompts_cfg=prompts_cfg
                )
                # If critic rejected the script due to unresolvable defects, halt generation safely
                if audit_summary.get("status") == "rejected" or audit_summary.get("unresolved_failures", 0) > 0:
                    raise ValueError(
                        f"Editorial Critic rejected script: {audit_summary.get('unresolved_failures', 0)} unresolvable defect(s)"
                    )
                # If critic corrected the title, update script_data so it flows downstream and synchronize description header
                if _seo_for_critic.get("title") and _seo_for_critic["title"] != _title_from_script:
                    new_aligned_title = _seo_for_critic["title"]
                    from engine.managers.iterative_script_generator import synchronize_seo_description_header
                    if "seo" in script_data and isinstance(script_data["seo"], dict):
                        script_data["seo"]["title"] = new_aligned_title
                        if "description" in script_data["seo"]:
                            script_data["seo"]["description"] = synchronize_seo_description_header(
                                description=script_data["seo"]["description"],
                                old_title=_title_from_script,
                                new_title=new_aligned_title
                            )
                    elif "title" in script_data:
                        script_data["title"] = new_aligned_title
                        if "description" in script_data:
                            script_data["description"] = synchronize_seo_description_header(
                                description=script_data["description"],
                                old_title=_title_from_script,
                                new_title=new_aligned_title
                            )

                # Feed results back to LLM Quality Tracker
                _active_provider_id = getattr(llm, "_last_used_provider_id", "unknown")
                try:
                    from engine.managers.llm_quality_tracker import LLMQualityTracker
                    qt = LLMQualityTracker()
                    qt.record_result(
                        model_id=_active_provider_id,
                        wall_test_failures=audit_summary.get("wall_test_failures", 0),
                        wall_test_replacements=audit_summary.get("wall_test_replacements", 0),
                        passed_first_attempt=True  # Already passed validator to get here
                    )
                except Exception as qt_err:
                    print(f"⚠️  [QUALITY TRACKER] Could not record result: {qt_err}")

            except ValueError:
                raise
            except Exception as critic_err:
                print(f"❌ [EDITORIAL CRITIC] Audit failed unexpectedly: {critic_err}", flush=True)
                raise

        # ─── CLAIM-LEVEL FACTUALITY & PROVENANCE INSPECTION (SHORTS ONLY) ────────
        # Runs after Editorial Critic has finalized scene text, enforcing factual
        # integrity and risk-aware policy before thought-cache checks, TTS, or spec persistence.
        if video_type == "short":
            from engine.managers.claim_inspector import ClaimInspector
            claim_inspector = ClaimInspector(llm_manager=llm)

            raw_scenes, final_factuality_report, final_factuality_decision, rewrote_any = _validate_and_refine_claims(
                raw_scenes=raw_scenes,
                topic=topic,
                claim_inspector=claim_inspector,
                llm=llm,
                grounding_refs=grounding_refs if 'grounding_refs' in locals() else None,
                channel_premise=channel_premise,
                prompts_cfg=prompts_cfg,
                script_data=script_data,
                max_rewrites_per_scene=2
            )

            # Keep script_data scenes synchronized with verified raw_scenes
            script_data["scenes"] = raw_scenes

            # If factuality rewrites modified scenes, refresh SEO metadata to maintain strict truth-in-packaging
            if rewrote_any and video_type == "short":
                try:
                    refreshed_seo = generator._generate_seo(scenes=raw_scenes, topic=topic)
                    script_data["seo"] = refreshed_seo
                    print("✅ [SEO] Refreshed SEO metadata against factuality-verified scenes.", flush=True)
                except Exception as seo_ref_err:
                    print(f"⚠️ [SEO] Post-factuality SEO refresh failed ({seo_ref_err}). Applying safe script-grounded fallback metadata.", flush=True)
                    # Explicit safe policy: Never silently retain pre-rewrite metadata that may advertise
                    # discredited empirical claims. Generate deterministic, script-grounded fallback metadata
                    # derived strictly from the verified final scenes.
                    from engine.managers.iterative_script_generator import derive_grounded_fallback_seo
                    safe_seo = derive_grounded_fallback_seo(scenes=raw_scenes, topic=topic)
                    safe_seo["_refresh_failed"] = True
                    safe_seo["_refresh_error"] = str(seo_ref_err)
                    script_data["seo"] = safe_seo

        # ─── THOUGHT-CACHE DEDUPLICATION & PERSISTENCE ────────────────────────
        # Check each scene against the rolling thought cache (persisted in memory and channel_config.yaml).
        # Invariant: No scene text may change after the final successful call to editorial_critic.
        # If any scene duplicates a previously published line, reject the script safely rather than
        # performing unvalidated raw-LLM rewrites that bypass the Editorial Critic.
        if not is_test_run() and not os.environ.get("PYTEST_CURRENT_TEST"):
            for idx, scene in enumerate(raw_scenes):
                spoken = scene.get("spoken_text", "")
                if spoken and _is_duplicate(spoken, thought_cfg):
                    raise ValueError(
                        f"Thought Cache rejected script: Scene {idx + 1} duplicates previously published thought: '{spoken[:60]}...'"
                    )

            # Register all final verified lines in cache and persist ONLY in production
            for scene in raw_scenes:
                _add_to_cache(scene.get("spoken_text", ""), thought_cfg)
            try:
                os.makedirs("memory", exist_ok=True)
                with open(_MEMORY_THOUGHT_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(thought_cfg, f, indent=2)
            except Exception as e:
                print(f"⚠️  [THOUGHT CACHE] Could not persist cache to memory: {e}", flush=True)
            try:
                from engine.managers.iterative_script_generator import save_past_spoken_thoughts
                spoken_lines = [s.get("spoken_text", "") for s in raw_scenes if s.get("spoken_text")]
                save_past_spoken_thoughts(spoken_lines)
            except Exception as e:
                print(f"⚠️  [MEMORY] Could not persist to past_spoken_thoughts.json: {e}", flush=True)
            try:
                _save_yaml(_CHANNEL_CONFIG_PATH, full_channel_cfg)
            except Exception as e:
                print(f"⚠️  [THOUGHT CACHE] Could not persist cache to channel_config.yaml: {e}", flush=True)
        else:
            print("🧪 [TEST MODE] Skipping thought cache persistence so test thoughts/facts are not added to duplicate list or wasted.", flush=True)

        # 3. Normalize for Phonetic TTS & Extract Word Boundaries
        for s in raw_scenes:
            s["phonetic_text"] = VoiceNormalizer.normalize_text(s["spoken_text"])

        full_phonetic_script = " ".join(s["phonetic_text"] for s in raw_scenes)
        full_display_script = " ".join(s["spoken_text"] for s in raw_scenes)

        
        audio_output = os.path.join("output", "narration.mp3")
        voice_cfg = channel_cfg.get("voice", {})
        voice_id = voice_cfg.get("voice_id", "am_adam")
        voice_provider = voice_cfg.get("provider", "kokoro")
        voice_speed = float(voice_cfg.get("speed", 1.02))
        
        print(f"🎙️ [TTS] Synthesizing narration with {voice_provider} (voice: {voice_id}, speed: {voice_speed:.2f})...")
        total_duration, word_timestamps, scene_cut_durations, scene_word_slices = VoiceNormalizer.synthesize_scenes_sync(
            raw_scenes=raw_scenes,
            output_audio_path=audio_output,
            voice=voice_id,
            speed=voice_speed,
            prefer_provider=voice_provider
        )

        if total_duration <= 0.0:
            words_count = len(full_phonetic_script.split())
            total_duration = max(15.0, round(words_count / 2.5, 2))
            print(f"⚠️ [TTS] Measured duration was 0.0s — calculated fallback duration: {total_duration:.1f}s")
            each_d = round(total_duration / max(1, len(raw_scenes)), 2)
            scene_cut_durations = [each_d] * len(raw_scenes)

        # Natural Shorts duration audit (100% natural 1.0x audio speed, zero atempo distortion)
        if video_type == "short":
            print(f"⏱️ [DURATION AUDIT] Narration audio finalized at {total_duration:.2f}s across {len(raw_scenes)} scenes (100% natural speed, zero atempo distortion).", flush=True)
            from engine.managers.caption_aligner import CaptionAligner
            scene_word_slices = CaptionAligner.slice_words_by_scenes(word_timestamps, raw_scenes)

        num_scenes = len(raw_scenes)
        # Sample unique visual queries for this video from the channel taxonomy
        from engine.managers.stock_video_manager import SHORTS_VISUAL_TAXONOMY
        visual_tax = full_channel_cfg.get("visual_settings", {}).get("visual_taxonomy", SHORTS_VISUAL_TAXONOMY)
        if video_type == "short":
            if len(visual_tax) >= num_scenes:
                sampled_queries = random.sample(visual_tax, num_scenes)
            else:
                sampled_queries = (visual_tax * ((num_scenes // len(visual_tax)) + 1))[:num_scenes]
                random.shuffle(sampled_queries)
        else:
            sampled_queries = [s.get("stock_video_query", "cinematic abstract background") for s in raw_scenes]

        scenes_spec = []
        for idx, s in enumerate(raw_scenes):
            s_text = s["spoken_text"]
            p_text = s["phonetic_text"]
            scene_words = scene_word_slices[idx] if idx < len(scene_word_slices) else []
            s_dur = scene_cut_durations[idx] if idx < len(scene_cut_durations) else round(total_duration / max(1, num_scenes), 2)
            if s_dur <= 0.0:
                s_dur = 4.0

            scenes_spec.append(
                SceneSpec(
                    scene_id=idx + 1,
                    spoken_text=s_text,
                    phonetic_text=p_text,
                    stock_video_query=sampled_queries[idx],
                    duration_seconds=round(s_dur, 2),
                    word_timestamps=scene_words
                )
            )

        # 4. Extract or Generate SEO Metadata
        script_seo = script_data.get("seo")
        if isinstance(script_seo, dict) and script_seo.get("title"):
            print("🚀 [SEO] Extracted unified SEO metadata directly from script generation.", flush=True)
            seo_data = script_seo
        elif "title" in script_data and ("description" in script_data or "tags" in script_data):
            print("🚀 [SEO] Extracted root SEO metadata directly from script generation.", flush=True)
            seo_data = {
                "title": script_data.get("title"),
                "description": script_data.get("description", ""),
                "tags": script_data.get("tags", [])
            }
        else:
            print("🤖 [SEO] Script did not include unified SEO. Generating via secondary SEO prompt...", flush=True)
            seo_cfg = prompts_cfg.get("seo_gen", {})
            sys_p = seo_cfg.get(
                "system_prompt",
                "You generate accurate, compelling, and natural YouTube Shorts metadata (title, description, tags) grounded strictly in the provided script and topic. Output valid JSON with 'title', 'description', 'tags'."
            )
            usr_tmpl = seo_cfg.get("user_template", "")
            if usr_tmpl:
                try:
                    seo_user_prompt = usr_tmpl.format(script_text=full_display_script, topic=topic or "General")
                except KeyError:
                    seo_user_prompt = f"TOPIC: {topic or 'General'}\nSCRIPT:\n{full_display_script}\n\nGenerate accurate, compelling YouTube Shorts metadata reflecting this specific script."
            else:
                seo_user_prompt = f"TOPIC: {topic or 'General'}\nSCRIPT:\n{full_display_script}\n\nGenerate accurate, compelling YouTube Shorts metadata reflecting this specific script."
            seo_data = llm.generate_json(sys_p, seo_user_prompt, temperature=0.2, task_name="seo_gen")

        if video_type == "long":
            seo_title = seo_data.get("title", f"{topic[:60]}").replace("#shorts", "").strip()
            seo_desc = seo_data.get("description", f"An in-depth psychological documentary exploring {topic}.").replace("#shorts", "").strip()
            seo_tags = [t for t in seo_data.get("tags", ["psychology", "documentary", "facts", "essay"]) if t != "shorts"]
        else:
            base_title = seo_data.get("title")
            if not base_title:
                from engine.managers.iterative_script_generator import derive_grounded_fallback_title
                base_title = derive_grounded_fallback_title(
                    scenes=[{"spoken_text": sc.spoken_text} for sc in scenes_spec],
                    topic=topic
                )
            from engine.managers.editorial_critic import _ensure_shorts_suffix
            base_title = _ensure_shorts_suffix(base_title)

            from engine.managers.iterative_script_generator import derive_grounded_fallback_description
            default_desc = derive_grounded_fallback_description(
                scenes=[{"spoken_text": sc.spoken_text} for sc in scenes_spec],
                topic=topic
            )
            seo_desc = seo_data.get("description", default_desc)
            if not seo_desc or len(seo_desc.strip()) < 20:
                seo_desc = default_desc

            script_kws = extract_keywords(full_display_script, max_keywords=8)
            default_tags = [topic.lower()] if topic else []
            default_tags.extend([kw.lower() for kw in script_kws if kw.lower() not in default_tags])
            if "shorts" not in default_tags:
                default_tags.append("shorts")
            seo_tags = seo_data.get("tags") or default_tags

            # Enhance title using script keywords, trend data, and channel title_settings
            try:
                from engine.managers.youtube_manager import generate_seo_title
                from engine.managers.editorial_critic import (
                    TitleScriptAlignmentSkill,
                    _ensure_shorts_suffix,
                    _token_overlap,
                    _load_upload_history_titles,
                )
                from engine.managers.iterative_script_generator import synchronize_seo_description_header

                title_cfg = full_channel_cfg.get("title_settings", {})
                cand_title = generate_seo_title(
                    niche=channel_cfg.get("niche", ""),
                    base_title=base_title,
                    script_text=full_display_script,
                    cfg=title_cfg
                )
                if not isinstance(cand_title, str) or not cand_title.strip():
                    print("ℹ️ [SEO] Enhanced title candidate is empty or invalid. Retaining base title.", flush=True)
                    seo_title = base_title
                else:
                    norm_cand = _ensure_shorts_suffix(cand_title)
                    passed, reason = TitleScriptAlignmentSkill.audit_title(
                        norm_cand,
                        scenes=[{"spoken_text": sc.spoken_text} for sc in scenes_spec]
                    )
                    upload_history = _load_upload_history_titles(strict=True)
                    if upload_history is None:
                        print("⚠️ [SEO] Upload history validation unavailable (history file exists but cannot be read or parsed). Retaining base title.", flush=True)
                        seo_title = base_title
                    else:
                        history_lower = [t.lower().strip() for t in upload_history if isinstance(t, str)]
                        cand_lower = norm_cand.lower()
                        is_dup = any(_token_overlap(cand_lower, h) > 0.70 for h in history_lower)

                        if passed and not is_dup:
                            seo_title = norm_cand
                        else:
                            if not passed:
                                print(f"ℹ️ [SEO] Enhanced title rejected by audit ({reason}). Retaining base title.", flush=True)
                            elif is_dup:
                                print("🔄 [SEO] Enhanced title duplicate of recent upload history. Retaining base title.", flush=True)
                            seo_title = base_title
            except Exception as e:
                print(f"⚠️ [SEO] Title enhancement failed ({e}). Using base title.", flush=True)
                seo_title = base_title

            # Synchronize description header if title was modified by enhancement
            if seo_title != base_title:
                seo_desc = synchronize_seo_description_header(
                    description=seo_desc,
                    old_title=base_title,
                    new_title=seo_title
                )

        # Merge evergreen brand tags from channel_config.yaml
        brand_tags = full_channel_cfg.get("brand_tags", [])
        if brand_tags:
            merged_tags = []
            seen_tags = set()
            for t in list(seo_tags) + list(brand_tags):
                t_clean = t.strip()
                t_lower = t_clean.lower()
                if t_clean and t_lower not in seen_tags:
                    seen_tags.add(t_lower)
                    merged_tags.append(t_clean)
            seo_tags = merged_tags

        # Exact title on top of the description always, followed by an empty line, then the SEO description
        clean_desc = seo_desc.strip()
        if clean_desc.startswith(seo_title):
            clean_desc = clean_desc[len(seo_title):].strip()
        seo_desc = f"{seo_title}\n\n{clean_desc}"

        seo = SEOMetadata(
            title=seo_title,
            description=seo_desc,
            tags=seo_tags
        )

        calculated_total = round(max(total_duration, sum(sc.duration_seconds for sc in scenes_spec)), 2)

        # 5. Output spec.json artifact
        spec = SpecOutput(
            topic=topic,
            video_type=video_type,
            sub_format=sub_format,
            seo=seo,
            scenes=scenes_spec,
            total_duration_seconds=calculated_total if calculated_total > 0.0 else 30.0,
            audio_path=audio_output,
            thought_process=script_data.get("thought_process"),
            word_timestamps=word_timestamps
        )

        spec_dict = spec.model_dump() if hasattr(spec, "model_dump") else spec.dict()
        if isinstance(script_data.get("seo"), dict) and script_data["seo"].get("_refresh_failed"):
            spec_dict["seo"]["_refresh_failed"] = True
            spec_dict["seo"]["_refresh_error"] = script_data["seo"].get("_refresh_error", "")
        if full_channel_cfg.get("upload_settings", {}).get("generate_community_post", True):
            try:
                from engine.managers.youtube_manager import YouTubeManager
                hook_txt = scenes_spec[0].spoken_text if scenes_spec else ""
                spec_dict["community_engagement"] = YouTubeManager.generate_community_post(topic, hook_txt)
                comm_data = YouTubeManager.generate_community_post(topic, hook_txt)
                spec_dict["community_engagement"] = comm_data

                # Persist community engagement copy for 1-click posting
                os.makedirs("output", exist_ok=True)
                with open(os.path.join("output", "community_post.json"), "w", encoding="utf-8") as pf:
                    json.dump(comm_data, pf, indent=2)
                print("📦 [COMMUNITY] Generated Community Post & Poll in 'output/community_post.json'", flush=True)
            except Exception as e:
                print(f"⚠️ [COMMUNITY] Failed to generate community post: {e}", flush=True)

        os.makedirs("output", exist_ok=True)
        spec_path = os.path.join("output", "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(spec_dict, indent=2))

        print(f"📦 [SPEC] Saved spec artifact to '{spec_path}' ({len(scenes_spec)} scenes, {total_duration:.1f}s)")


def main():
    # ── POINT 1: KILL SWITCH & RUNTIME MODE ───────────────────────────────────
    _system_enabled = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
    _event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")

    if _system_enabled == "false":
        print("🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. System halted by operator.")
        sys.exit(0)
    elif _system_enabled == "test" and _event_name == "schedule":
        print("🔴 [TEST MODE] Scheduled cron run detected while in Test Mode. Halting automatically.")
        sys.exit(0)
    elif _system_enabled == "test":
        os.environ["TEST_MODE"] = "true"
        print("🧪 [TEST MODE] Running in Test Mode (GHOST_ENGINE_ENABLED=test). API mutations & releases strictly blocked.")

    parser = argparse.ArgumentParser(description="Pika Flow Pipeline Runner (v2.0)")
    parser.add_argument("--stage", required=True, choices=["spec", "clips", "editor", "release"], help="Stage to execute")
    parser.add_argument("--type", default="short", choices=["short", "long"], help="Video profile type")
    parser.add_argument("--test-mode", action="store_true", help="Run in test mode (bypasses YouTube upload and database updates)")
    parser.add_argument("--topic", default=None, help="Custom topic to override automatic topic discovery")
    args = parser.parse_args()

    if args.test_mode and os.environ.get("TEST_MODE") != "true":
        os.environ["TEST_MODE"] = "true"
        print("🧪 [TEST MODE] Activated via CLI flag. Zero YouTube API / Database mutation.")

    try:
        if args.stage == "spec":
            run_spec_stage(video_type=args.type, custom_topic=args.topic)
        elif args.stage == "clips":
            from engine.managers.stock_video_manager import run_clips_stage
            run_clips_stage()
        elif args.stage == "editor":
            from scripts.render_video import run_editor_stage
            run_editor_stage()
        elif args.stage == "release":
            from engine.managers.youtube_manager import run_release_stage
            run_release_stage()
    except Exception as e:
        ErrorManager.handle_fatal_error(e, context=f"Pipeline Stage '{args.stage}'")


if __name__ == "__main__":
    main()

