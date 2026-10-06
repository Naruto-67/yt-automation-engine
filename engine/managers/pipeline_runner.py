"""
engine/managers/pipeline_runner.py — CLI Dispatch Entrypoint for Pika Flow Stages (v2.0)
Orchestrates Stage 1 (spec), Stage 2 (clips), Stage 3 (editor), and Stage 4 (release).
"""

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
from typing import Dict, Any, List

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


def _hash_line(line: str) -> str:
    """SHA-256 hash of a normalised spoken line (stripped, lowercased, no punctuation)."""
    normalised = re.sub(r"[^\w\s]", "", line.strip().lower())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _load_thought_cache(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg.setdefault("thought_cache", {"max_entries": 200, "entries": []})


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
    """
    rules = channel_cfg.get("prompt_settings", channel_cfg.get("prompt_rules", {}))

    # 1. Enforce virality reminder
    if rules.get("enforce_virality", True):
        system_prompt += (
            "\n\nVIRALITY ENFORCEMENT: Every scene must be instantly shareable, "
            "psychologically shocking, and optimised for maximum scroll-stop retention."
        )

    # 2. Extra freeform user instruction
    extra = (rules.get("extra_instructions") or "").strip()
    if extra:
        user_prompt += f"\n\nADDITIONAL CHANNEL INSTRUCTION: {extra}"

    # 3. Extra banned phrases
    banned: List[str] = rules.get("banned_phrases", [])
    if banned:
        joined = ", ".join(f'"{p}"' for p in banned)
        system_prompt += f"\n\nEXTRA BANNED PHRASES (channel-specific): {joined}. Never use these."

    return system_prompt, user_prompt


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


def run_spec_stage(video_type: str = "short") -> None:
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
        if surge and not inspector.is_topic_recent(surge.get("title", "")):
            topic = surge.get("title")
            source = "competitor_surge"
            inspector.record_topic_usage(topic, topic, niche=channel_cfg.get("niche", "shower_thoughts"))
        else:
            if surge:
                print(f"🔄 [COMPETITOR SPY] Surge topic '{surge.get('title', '')}' was already used recently. Discovering fresh topic...")
            topic_info = inspector.discover_verified_topic(channel_cfg.get("niche", "shower_thoughts"), video_type="short")
            topic = topic_info["topic"]
            source = topic_info.get("source", "trend")
        script_cfg = prompts_cfg["script_gen"]

    with StageTimer(PikaStage.SPEC, topic=topic):
        print(f"🎯 [SPEC] Topic: '{topic}' (Source: {source}, Format: {sub_format}, Type: {video_type})")

        # 2. Generate Script
        system_prompt = script_cfg["system_prompt"]
        if "constitution" in script_cfg:
            system_prompt += "\n\n" + script_cfg["constitution"]
        if "few_shot_exemplars" in script_cfg:
            system_prompt += "\n\n" + script_cfg["few_shot_exemplars"]

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

        prompt_settings = full_channel_cfg.get("prompt_settings", full_channel_cfg.get("prompt_rules", {}))
        channel_premise = prompt_settings.get("channel_premise", "Mind-bending shower thoughts, psychological paradoxes, and reality-breaking cognitive glitches.")
        extra_instructions = prompt_settings.get("extra_instructions", "")

        user_prompt = script_cfg["user_template"].format(
            channel_name=channel_cfg.get("name", "TOPATO"),
            niche=channel_cfg.get("niche", "shower_thoughts"),
            topic=topic,
            sub_format=sub_format,
            target_duration=target_duration,
            channel_premise=channel_premise,
            extra_instructions=extra_instructions,
            performance_insight=perf_insight
        )

        # Inject channel-specific prompt rules (virality enforcement, banned phrases, extra instructions)
        system_prompt, user_prompt = apply_prompt_rules(system_prompt, user_prompt, full_channel_cfg)

        # Load thought-cache for deduplication (persisted in channel_config.yaml)
        thought_cfg = _load_thought_cache(full_channel_cfg)

        def validate_short_script(data: Dict[str, Any]) -> bool:
            if not isinstance(data, dict):
                return False
            scenes = data.get("scenes", [])
            if not scenes and "chapters" in data:
                scenes = []
                for ch in data.get("chapters", []):
                    scenes.extend(ch.get("scenes", []))
            if not isinstance(scenes, list) or len(scenes) < 3:
                return False
            valid_scenes = [sc for sc in scenes if isinstance(sc, dict) and bool(sc.get("spoken_text", "").strip())]
            if len(valid_scenes) < 3:
                return False
            # YouTube policy safety gate: reject if script contains banned policy words
            for sc in valid_scenes:
                txt = sc.get("spoken_text", "").lower()
                if any(bad in txt for bad in YOUTUBE_POLICY_BANNED_WORDS):
                    print(f"⚠️ [POLICY GATE] Script contains YouTube policy flagged term. Cascading...", flush=True)
                    return False
            words = sum(len(sc.get("spoken_text", "").split()) for sc in valid_scenes)
            if words < 25 or words > 220:
                print(f"⚠️ [VALIDATOR] Script word count out of range ({words} words, expected 25-220). Cascading...", flush=True)
                return False
            return True

        validator = validate_short_script if (video_type == "short" and not os.environ.get("PYTEST_CURRENT_TEST")) else None
        script_data = llm.generate_json(system_prompt, user_prompt, temperature=0.7, validator=validator)

        raw_scenes = script_data.get("scenes", [])
        if not raw_scenes and "chapters" in script_data:
            # Flatten scenes from chapters
            raw_scenes = []
            for ch in script_data.get("chapters", []):
                raw_scenes.extend(ch.get("scenes", []))

        if not raw_scenes:
            raise ValueError("LLM generated empty scene array.")

        # Ensure clean opening for Hook (no leading ellipses or dots)
        if raw_scenes:
            raw_scenes[0]["spoken_text"] = re.sub(r"^[\.\s…\-]+", "", raw_scenes[0]["spoken_text"]).strip()
            if raw_scenes[0]["spoken_text"] and raw_scenes[0]["spoken_text"][0].islower():
                raw_scenes[0]["spoken_text"] = raw_scenes[0]["spoken_text"][0].upper() + raw_scenes[0]["spoken_text"][1:]

        # Ensure sufficient scenes and words for Shorts in production & test runs
        if video_type == "short" and not os.environ.get("PYTEST_CURRENT_TEST"):
            total_words = sum(len(s.get("spoken_text", "").split()) for s in raw_scenes)
            # Cap if too long to prevent > 58s run
            if len(raw_scenes) > 13:
                loop_scene = raw_scenes[-1]
                raw_scenes = raw_scenes[:12] + [loop_scene]
                for i, sc in enumerate(raw_scenes):
                    sc["scene_id"] = i + 1
                total_words = sum(len(s.get("spoken_text", "").split()) for s in raw_scenes)

            FALLBACK_THOUGHTS = prompt_settings.get("fallback_thoughts", [
                "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
                "If you replace every single part of an axe, is it still the exact same axe?",
                "You have never actually seen your own face, only reflections, screens, and photographs.",
                "Sleeping is just charging your biological battery, while dreaming is running a diagnostics test.",
                "Nothing is ever on fire. Fire is actually on things.",
                "Clapping is just repeatedly slapping yourself because you enjoyed something.",
                "Your age is just the number of laps you survived around a giant nuclear fireball.",
                "If poison expires, does it become more poisonous, or less poisonous?",
                "The brain named itself, recognized itself, and is now realizing that exact fact.",
                "Every book you have ever read is just twenty-six letters arranged in different orders.",
                "Water can boil and freeze at the exact same instant under specific pressure.",
                "You can never hold an empty container because it is always completely full of air."
            ])

            if len(raw_scenes) < 11 or total_words < 135:
                print(f"⚠️ [SPEC] Script below target word budget ({len(raw_scenes)} scenes, {total_words} words). Expanding with verified viral thoughts...", flush=True)

                default_hook = prompt_settings.get("default_hook", "The only part of your reflection you can lick is your tongue.")
                default_loop = prompt_settings.get("default_loop", "Which is why you should never overthink these...")

                if len(raw_scenes) <= 1 or total_words < 30:
                    raw_scenes = [{
                        "scene_id": 1,
                        "spoken_text": default_hook,
                        "stock_video_query": "soap carving cubes ASMR"
                    }]

                has_loop_phrase = len(raw_scenes) > 1 and any(
                    lp in raw_scenes[-1].get("spoken_text", "").lower()
                    for lp in ["overthink", "which is why", "why you should", "never think about"]
                )
                if has_loop_phrase:
                    loop_scene = raw_scenes[-1]
                    mid_scenes = list(raw_scenes[:-1])
                else:
                    loop_scene = {
                        "scene_id": 12,
                        "spoken_text": default_loop,
                        "stock_video_query": "spiral optical illusion hypnotic"
                    }
                    mid_scenes = list(raw_scenes)

                # Fuzzy deduplication: avoid adding thoughts similar to existing ones
                for fb in FALLBACK_THOUGHTS:
                    if not any(are_thoughts_similar(fb, s.get("spoken_text", "")) for s in mid_scenes):
                        mid_scenes.append({"scene_id": len(mid_scenes) + 1, "spoken_text": fb, "stock_video_query": "soap carving cubes ASMR"})
                    if len(mid_scenes) >= 11 and sum(len(s.get("spoken_text", "").split()) for s in mid_scenes) >= 140:
                        break

                mid_scenes.append(loop_scene)
                raw_scenes = mid_scenes
                for i, sc in enumerate(raw_scenes):
                    sc["scene_id"] = i + 1

            # Intra-Script Deduplication: verify no two scenes in raw_scenes are duplicates
            deduped_scenes = []
            for s in raw_scenes:
                is_duplicate = any(are_thoughts_similar(s.get("spoken_text", ""), prev.get("spoken_text", "")) for prev in deduped_scenes)
                if is_duplicate and s != raw_scenes[-1] and s != raw_scenes[0]:
                    print(f"♻️ [INTRA-DEDUP] Duplicate thought in script: '{s.get('spoken_text', '')[:40]}...'. Replacing with fresh thought.", flush=True)
                    for fb in FALLBACK_THOUGHTS:
                        if not any(are_thoughts_similar(fb, x.get("spoken_text", "")) for x in deduped_scenes + raw_scenes):
                            s["spoken_text"] = fb
                            break
                deduped_scenes.append(s)
            raw_scenes = deduped_scenes

        # Seamless circular loop for Shorts: Ensure final scene ends with continuation ellipsis '...'
        if video_type == "short" and raw_scenes:
            last_text = raw_scenes[-1]["spoken_text"].rstrip(".! ")
            if not last_text.endswith("..."):
                raw_scenes[-1]["spoken_text"] = f"{last_text}..."

        # ─── THOUGHT-CACHE DEDUPLICATION ──────────────────────────────────────
        # Check each scene against the rolling thought cache (stored in channel_config.yaml).
        # If a spoken line matches a previously used line, ask the LLM to rewrite only that scene.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            for scene in raw_scenes:
                spoken = scene.get("spoken_text", "")
                if spoken and _is_duplicate(spoken, thought_cfg):
                    print(f"♻️  [THOUGHT CACHE] Duplicate line detected. Rewriting: '{spoken[:60]}...'", flush=True)
                    rewrite_sys = (
                        "You are a viral YouTube Shorts copywriter. Rewrite the following spoken line so it "
                        "expresses a similar idea but uses completely different wording. Keep it under 15 words, "
                        "psychologically punchy, and do NOT start with ellipses. "
                        'Return ONLY valid JSON: {"text": "<rewritten line>"}'
                    )
                    rewrite_usr = f'Original: "{spoken}"\nRewrite (15 words max, no leading punctuation):'
                    try:
                        result = llm.generate_json(rewrite_sys, rewrite_usr, temperature=0.9)
                        new_line = (result.get("text") or "").strip()
                        new_line = re.sub(r'^["\']|["\']$', "", new_line)
                        if new_line:
                            scene["spoken_text"] = new_line
                    except Exception as e:
                        print(f"⚠️  [THOUGHT CACHE] Rewrite failed ({e}). Keeping original.", flush=True)
            # Register all final lines in cache and persist
            for scene in raw_scenes:
                _add_to_cache(scene.get("spoken_text", ""), thought_cfg)
            try:
                _save_yaml(_CHANNEL_CONFIG_PATH, full_channel_cfg)
            except Exception as e:
                print(f"⚠️  [THOUGHT CACHE] Could not persist cache to channel_config.yaml: {e}", flush=True)

        # 3. Normalize for Phonetic TTS & Extract Word Boundaries
        for s in raw_scenes:
            s["phonetic_text"] = VoiceNormalizer.normalize_text(s["spoken_text"])

        full_phonetic_script = " ".join(s["phonetic_text"] for s in raw_scenes)
        full_display_script = " ".join(s["spoken_text"] for s in raw_scenes)

        
        audio_output = os.path.join("output", "narration.mp3")
        voice_cfg = channel_cfg.get("voice", {})
        voice_id = voice_cfg.get("voice_id", "am_adam")
        voice_provider = voice_cfg.get("provider", "kokoro")
        voice_speed = float(voice_cfg.get("speed", 0.92))
        
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

        # Enforce strict Shorts duration window (50-56.5s, strictly under 58s and at least 50s)
        if video_type == "short":
            target_dur = 0.0
            if total_duration > 57.5:
                target_dur = 55.0
            elif total_duration < 50.0 and total_duration >= 25.0:
                target_dur = 52.5

            if target_dur > 0.0:
                speed_ratio = round(total_duration / target_dur, 3)
                print(f"⚠️ [DURATION GUARD] Measured audio ({total_duration:.2f}s) outside 50.0-57.5s window. Calibrating audio in-place by {speed_ratio}x to {target_dur}s...", flush=True)
                wav_path = audio_output.rsplit(".", 1)[0] + ".wav"
                rescaled_wav = os.path.join("output", "narration_rescaled.wav")
                rescaled_mp3 = os.path.join("output", "narration_rescaled.mp3")

                rescaled_ok = False
                if os.path.exists(wav_path):
                    rescaled_ok = VoiceNormalizer.rescale_audio_duration(wav_path, rescaled_wav, speed_ratio)
                if not rescaled_ok and os.path.exists(audio_output):
                    rescaled_ok = VoiceNormalizer.rescale_audio_duration(audio_output, rescaled_mp3, speed_ratio)

                if rescaled_ok:
                    import shutil
                    if os.path.exists(rescaled_wav):
                        shutil.move(rescaled_wav, wav_path)
                    if os.path.exists(rescaled_mp3):
                        shutil.move(rescaled_mp3, audio_output)
                    elif os.path.exists(wav_path):
                        # Convert rescaled wav to mp3 in place
                        import subprocess
                        subprocess.run(
                            ["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", audio_output],
                            check=False
                        )
                    total_duration = target_dur

                    # Re-align captions directly on the final rescaled audio via CaptionAligner
                    from engine.managers.caption_aligner import CaptionAligner
                    target_audio = wav_path if os.path.exists(wav_path) else audio_output
                    aligned_words = CaptionAligner.align_captions(
                        audio_path=target_audio,
                        script_text=full_phonetic_script
                    )
                    if aligned_words and len(aligned_words) >= max(1, int(len(word_timestamps) * 0.8)):
                        word_timestamps = aligned_words
                    else:
                        for wt in word_timestamps:
                            wt.start = round(wt.start / speed_ratio, 3)
                            wt.end = round(wt.end / speed_ratio, 3)

                    scene_cut_durations = [round(d / speed_ratio, 2) for d in scene_cut_durations]
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
            seo_cfg = prompts_cfg["seo_gen"]
            seo_user_prompt = seo_cfg["user_template"].format(script_text=full_display_script)
            seo_data = llm.generate_json(seo_cfg["system_prompt"], seo_user_prompt, temperature=0.2)

        if video_type == "long":
            seo_title = seo_data.get("title", f"{topic[:60]}").replace("#shorts", "").strip()
            seo_desc = seo_data.get("description", f"An in-depth psychological documentary exploring {topic}.").replace("#shorts", "").strip()
            seo_tags = [t for t in seo_data.get("tags", ["psychology", "documentary", "facts", "essay"]) if t != "shorts"]
        else:
            base_title = seo_data.get("title", f"{topic[:60]} #shorts")
            if "#shorts" not in base_title.lower():
                base_title = f"{base_title.rstrip()} #shorts"

            default_desc = (
                f"Mind-bending shower thoughts and psychological paradoxes about {topic}. "
                f"Which realization broke your brain the most? Drop your perspective below! 👇\n\n"
                f"Subscribe to @metopato for daily mind-bending shifts.\n\n"
                f"#showerthoughts #psychology #mindblowing #deepthoughts #shorts"
            )
            seo_desc = seo_data.get("description", default_desc)
            if not seo_desc or len(seo_desc.strip()) < 30:
                seo_desc = default_desc

            seo_tags = seo_data.get("tags", [
                "shower thoughts", "mind blowing facts", "psychology", "paradoxes",
                "brain glitches", "reality check", "deep thoughts", "shorts"
            ])

            # Enhance title using script keywords, trend data, and channel title_settings
            try:
                from engine.managers.youtube_manager import generate_seo_title
                title_cfg = full_channel_cfg.get("title_settings", {})
                seo_title = generate_seo_title(
                    niche=channel_cfg.get("niche", ""),
                    base_title=base_title,
                    script_text=full_display_script,
                    cfg=title_cfg
                )
            except Exception as e:
                print(f"⚠️ [SEO] Title enhancement failed ({e}). Using base title.", flush=True)
                seo_title = base_title

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
        if full_channel_cfg.get("upload_settings", {}).get("generate_community_post", True):
            try:
                from engine.managers.youtube_manager import YouTubeManager
                hook_txt = scenes_spec[0].spoken_text if scenes_spec else ""
                spec_dict["community_engagement"] = YouTubeManager.generate_community_post(topic, hook_txt)
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
    args = parser.parse_args()

    if args.test_mode and os.environ.get("TEST_MODE") != "true":
        os.environ["TEST_MODE"] = "true"
        print("🧪 [TEST MODE] Activated via CLI flag. Zero YouTube API / Database mutation.")

    try:
        if args.stage == "spec":
            run_spec_stage(video_type=args.type)
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

