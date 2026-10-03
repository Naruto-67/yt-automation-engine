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
import argparse
from typing import Dict, Any

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


def run_spec_stage(video_type: str = "short") -> None:
    """Executes Stage 1: 🚀 Init & Spec Generation."""
    channel_cfg = load_yaml("config/channel_config.yaml")["channel"]
    settings_cfg = load_yaml("config/settings.yaml")
    prompts_cfg = load_yaml("config/prompts.yaml")
    weights = HealthManager.load_dynamic_weights()
    HealthManager.check_and_sync_models()

    llm = LLMManager()
    inspector = TopicInspector(llm_manager=llm)

    target_duration = settings_cfg.get("video_profiles", {}).get(video_type, {}).get("target_duration", 600 if video_type == "long" else 55)

    if video_type == "long":
        sub_format = "documentary_essay"
        topic_info = inspector.discover_verified_topic(channel_cfg.get("niche", "psychology_and_facts"))
        topic = topic_info["topic"]
        source = topic_info.get("source", "trend")
        script_cfg = prompts_cfg.get("long_form_doc", prompts_cfg["script_gen"])
    else:
        # For Shorts: STRICTLY lock sub-format to "shower_thoughts_listicle" (12-15 rapid-fire thoughts, 50-58s)
        # Avoid rolling core_brainblud for shorts which is only 5 scenes / 25s
        sub_format = "shower_thoughts_listicle"

        # 1. Discover topic (Competitor Spy -> Topic Inspector)
        surge = CompetitorSpy.get_surge_topic(settings_cfg.get("competitors", []))
        if surge:
            topic = surge.get("title")
            source = "competitor_surge"
        else:
            topic_info = inspector.discover_verified_topic(channel_cfg.get("niche", "shower_thoughts"))
            topic = topic_info["topic"]
            source = topic_info.get("source", "trend")
        script_cfg = prompts_cfg["script_gen"]

    with StageTimer(PikaStage.SPEC, topic=topic):
        print(f"🎯 [SPEC] Topic: '{topic}' (Source: {source}, Format: {sub_format}, Type: {video_type})")

        # 2. Generate Script
        system_prompt = script_cfg["system_prompt"] + "\n\n" + script_cfg["constitution"] + "\n\n" + script_cfg.get("few_shot_exemplars", "")
        user_prompt = script_cfg["user_template"].format(
            niche=channel_cfg.get("niche", "shower_thoughts"),
            topic=topic,
            sub_format=sub_format,
            target_duration=target_duration
        )

        script_data = llm.generate_json(system_prompt, user_prompt, temperature=0.7)
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

        # Ensure sufficient scenes and words for Shorts in production runs
        if video_type == "short" and not os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("TEST_MODE"):
            total_words = sum(len(s.get("spoken_text", "").split()) for s in raw_scenes)
            # Cap if too long to prevent > 58s run
            if len(raw_scenes) > 13:
                loop_scene = raw_scenes[-1]
                raw_scenes = raw_scenes[:12] + [loop_scene]
                for i, sc in enumerate(raw_scenes):
                    sc["scene_id"] = i + 1
                total_words = sum(len(s.get("spoken_text", "").split()) for s in raw_scenes)

            if len(raw_scenes) < 11 or total_words < 125:
                print(f"⚠️ [SPEC] LLM output short ({len(raw_scenes)} scenes, {total_words} words). Expanding with verified shower thoughts...", flush=True)
                FALLBACK_THOUGHTS = [
                    "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
                    "If you replace every single part of an axe, is it still the exact same axe?",
                    "You have never actually seen your own face, only reflections, video screens, and photographs.",
                    "Sleeping is just charging your biological battery, while dreaming is running a diagnostics test.",
                    "Nothing is ever on fire. Fire is actually on things.",
                    "Clapping is just repeatedly slapping yourself because you enjoyed something.",
                    "Your age is just the number of laps you survived around a giant nuclear fireball.",
                    "If poison expires, does it become more poisonous, or less poisonous?",
                    "The brain named itself, recognized itself, and is now realizing that exact fact.",
                    "Why your future self is watching you right now through the lens of your memories."
                ]
                loop_scene = raw_scenes[-1] if len(raw_scenes) > 1 else None
                mid_scenes = raw_scenes[:-1] if len(raw_scenes) > 1 else raw_scenes
                existing_texts = {s.get("spoken_text", "").lower() for s in raw_scenes}
                
                for fb in FALLBACK_THOUGHTS:
                    if fb.lower() not in existing_texts:
                        mid_scenes.append({"scene_id": len(mid_scenes) + 1, "spoken_text": fb, "stock_video_query": "satisfying asmr"})
                        existing_texts.add(fb.lower())
                    if len(mid_scenes) >= 12 or sum(len(s.get("spoken_text", "").split()) for s in mid_scenes) >= 132:
                        break
                
                if loop_scene:
                    mid_scenes.append(loop_scene)
                raw_scenes = mid_scenes
                for i, sc in enumerate(raw_scenes):
                    sc["scene_id"] = i + 1

        # 3. Normalize for Phonetic TTS & Extract Word Boundaries
        for s in raw_scenes:
            s["phonetic_text"] = VoiceNormalizer.normalize_text(s["spoken_text"])

        full_phonetic_script = " ".join(s["phonetic_text"] for s in raw_scenes)
        full_display_script = " ".join(s["spoken_text"] for s in raw_scenes)
        
        audio_output = os.path.join("output", "narration.mp3")
        voice_cfg = channel_cfg.get("voice", {})
        voice_id = voice_cfg.get("voice_id", "am_adam")
        voice_provider = voice_cfg.get("provider", "kokoro")
        
        print(f"🎙️ [TTS] Synthesizing narration with {voice_provider} (voice: {voice_id})...")
        total_duration, word_timestamps = VoiceNormalizer.synthesize_sync(
            phonetic_text=full_phonetic_script,
            output_audio_path=audio_output,
            voice=voice_id,
            prefer_provider=voice_provider
        )

        if total_duration <= 0.0:
            words_count = len(full_phonetic_script.split())
            total_duration = max(15.0, round(words_count / 2.5, 2))
            print(f"⚠️ [TTS] Measured duration was 0.0s — calculated fallback duration: {total_duration:.1f}s")

        # Enforce strict Shorts duration ceiling (strictly under 59s: target 54-56s)
        if video_type == "short" and total_duration > 57.5:
            target_dur = 55.0
            speed_ratio = round(total_duration / target_dur, 3)
            print(f"⚠️ [DURATION GUARD] Measured audio ({total_duration:.2f}s) exceeds 57.5s. Rescaling audio by {speed_ratio}x to {target_dur}s...", flush=True)
            rescaled_path = os.path.join("output", "narration_rescaled.mp3")
            if VoiceNormalizer.rescale_audio_duration(audio_output, rescaled_path, speed_ratio):
                audio_output = rescaled_path
                total_duration = target_dur
                for wt in word_timestamps:
                    wt.start = round(wt.start / speed_ratio, 3)
                    wt.end = round(wt.end / speed_ratio, 3)

        # Map scene timing precisely across word timestamps with zero accumulative drift
        from engine.managers.stock_video_manager import SHORTS_VISUAL_TAXONOMY
        total_words_count = len(word_timestamps)
        total_p_words = max(1, sum(len(s["phonetic_text"].split()) for s in raw_scenes))
        accum_p_words = 0
        scenes_spec = []

        for idx, s in enumerate(raw_scenes):
            s_text = s["spoken_text"]
            p_text = s["phonetic_text"]
            p_count = len(p_text.split())
            
            # Slice word timestamps proportionally to prevent any accumulative desynchronization
            if total_words_count > 0 and total_p_words > 0:
                start_w_idx = int(round(accum_p_words / total_p_words * total_words_count))
                end_w_idx = int(round((accum_p_words + p_count) / total_p_words * total_words_count)) if idx < len(raw_scenes) - 1 else total_words_count
                scene_words = word_timestamps[start_w_idx:end_w_idx]
            else:
                scene_words = []

            accum_p_words += p_count

            # Determine scene duration
            if scene_words:
                s_dur = round(scene_words[-1].end - scene_words[0].start, 2)
            else:
                s_dur = round(total_duration / len(raw_scenes), 2)
            if s_dur <= 0.0:
                s_dur = round(total_duration / len(raw_scenes), 2)
            if s_dur <= 0.0:
                s_dur = 4.0

            # Stock video query: For Shorts, guarantee rotating satisfying ASMR query
            if video_type == "short":
                stock_query = SHORTS_VISUAL_TAXONOMY[idx % len(SHORTS_VISUAL_TAXONOMY)]
            else:
                stock_query = s.get("stock_video_query", "cinematic abstract background")

            scenes_spec.append(
                SceneSpec(
                    scene_id=idx + 1,
                    spoken_text=s_text,
                    phonetic_text=p_text,
                    stock_video_query=stock_query,
                    duration_seconds=round(s_dur, 2),
                    word_timestamps=scene_words
                )
            )

        # 4. Generate SEO Metadata
        seo_cfg = prompts_cfg["seo_gen"]
        seo_user_prompt = seo_cfg["user_template"].format(script_text=full_display_script)
        seo_data = llm.generate_json(seo_cfg["system_prompt"], seo_user_prompt, temperature=0.2)
        
        if video_type == "long":
            seo_title = seo_data.get("title", f"{topic[:60]}").replace("#shorts", "").strip()
            seo_desc = seo_data.get("description", f"An in-depth psychological documentary exploring {topic}.").replace("#shorts", "").strip()
            seo_tags = [t for t in seo_data.get("tags", ["psychology", "documentary", "facts", "essay"]) if t != "shorts"]
        else:
            seo_title = seo_data.get("title", f"{topic[:40]} #shorts")
            seo_desc = seo_data.get("description", f"Verified fact on {topic}. #shorts #psychology")
            seo_tags = seo_data.get("tags", ["shorts", "psychology", "facts"])

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

        os.makedirs("output", exist_ok=True)
        spec_path = os.path.join("output", "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            if hasattr(spec, "model_dump_json"):
                f.write(spec.model_dump_json(indent=2))
            else:
                f.write(json.dumps(spec.model_dump() if hasattr(spec, "model_dump") else spec.dict(), indent=2))

        print(f"📦 [SPEC] Saved spec artifact to '{spec_path}' ({len(scenes_spec)} scenes, {total_duration:.1f}s)")


def main():
    parser = argparse.ArgumentParser(description="Pika Flow Pipeline Runner (v2.0)")
    parser.add_argument("--stage", required=True, choices=["spec", "clips", "editor", "release"], help="Stage to execute")
    parser.add_argument("--type", default="short", choices=["short", "long"], help="Video profile type")
    parser.add_argument("--test-mode", action="store_true", help="Run in test mode (bypasses YouTube upload and database updates)")
    args = parser.parse_args()

    if args.test_mode:
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

