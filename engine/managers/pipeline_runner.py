"""
engine/managers/pipeline_runner.py — CLI Dispatch Entrypoint for Pika Flow Stages (v2.0)
Orchestrates Stage 1 (spec), Stage 2 (clips), Stage 3 (editor), and Stage 4 (release).
"""

import os
import sys
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

    # Roll for sub-format (80% core_brainblud, 20% listicle)
    sub_formats = weights.get("sub_formats", {"core_brainblud": 0.8, "listicle": 0.2})
    r = random.random()
    sub_format = "core_brainblud" if r < sub_formats.get("core_brainblud", 0.8) else "listicle"

    llm = LLMManager()
    inspector = TopicInspector(llm_manager=llm)

    # 1. Discover topic (Competitor Spy -> Topic Inspector)
    surge = CompetitorSpy.get_surge_topic(settings_cfg.get("competitors", []))
    if surge:
        topic = surge.get("title")
        source = "competitor_surge"
    else:
        topic_info = inspector.discover_verified_topic(channel_cfg.get("niche", "psychology_and_facts"))
        topic = topic_info["topic"]
        source = topic_info.get("source", "trend")

    with StageTimer(PikaStage.SPEC, topic=topic):
        print(f"🎯 [SPEC] Topic: '{topic}' (Source: {source}, Format: {sub_format})")

        # 2. Generate BrainBlud Script
        script_cfg = prompts_cfg["script_gen"]
        system_prompt = script_cfg["system_prompt"] + "\n\n" + script_cfg["constitution"] + "\n\n" + script_cfg["few_shot_exemplars"]
        user_prompt = script_cfg["user_template"].format(
            niche=channel_cfg.get("niche", "psychology_and_facts"),
            topic=topic,
            sub_format=sub_format,
            target_duration=settings_cfg["video_profiles"][video_type]["target_duration"]
        )

        script_data = llm.generate_json(system_prompt, user_prompt, temperature=0.7)
        raw_scenes = script_data.get("scenes", [])
        if not raw_scenes:
            raise ValueError("LLM generated empty scene array.")

        # 3. Normalize for Phonetic TTS & Extract Word Boundaries
        full_display_script = " ".join(s["spoken_text"] for s in raw_scenes)
        full_phonetic_script = VoiceNormalizer.normalize_text(full_display_script)
        
        audio_output = os.path.join("output", "narration.mp3")
        voice_id = channel_cfg.get("voice", {}).get("voice_id", "en-US-ChristopherNeural")
        
        print(f"🎙️ [TTS] Synthesizing narration with {voice_id} & capturing word boundaries...")
        total_duration, word_timestamps = VoiceNormalizer.synthesize_sync(
            full_phonetic_script, audio_output, voice=voice_id
        )

        # Map scene timing approximately across word timestamps
        scenes_spec = []
        word_cursor = 0
        total_words_count = len(word_timestamps)

        for idx, s in enumerate(raw_scenes):
            s_text = s["spoken_text"]
            p_text = VoiceNormalizer.normalize_text(s_text)
            s_word_count = len(s_text.split())
            
            # Slice word timestamps
            scene_words = word_timestamps[word_cursor: word_cursor + s_word_count]
            word_cursor += s_word_count
            
            s_dur = (scene_words[-1].end - scene_words[0].start) if scene_words else (total_duration / len(raw_scenes))

            scenes_spec.append(
                SceneSpec(
                    scene_id=idx + 1,
                    spoken_text=s_text,
                    phonetic_text=p_text,
                    stock_video_query=s.get("stock_video_query", "cinematic abstract background"),
                    duration_seconds=round(s_dur, 2),
                    word_timestamps=scene_words
                )
            )

        # 4. Generate SEO Metadata
        seo_cfg = prompts_cfg["seo_gen"]
        seo_user_prompt = seo_cfg["user_template"].format(script_text=full_display_script)
        seo_data = llm.generate_json(seo_cfg["system_prompt"], seo_user_prompt, temperature=0.2)
        
        seo = SEOMetadata(
            title=seo_data.get("title", f"{topic[:40]} #shorts"),
            description=seo_data.get("description", f"Verified fact on {topic}. #shorts #psychology"),
            tags=seo_data.get("tags", ["shorts", "psychology", "facts"])
        )

        # 5. Output spec.json artifact
        spec = SpecOutput(
            topic=topic,
            video_type=video_type,
            sub_format=sub_format,
            seo=seo,
            scenes=scenes_spec,
            total_duration_seconds=round(total_duration, 2),
            audio_path=audio_output,
            thought_process=script_data.get("thought_process")
        )

        os.makedirs("output", exist_ok=True)
        spec_path = os.path.join("output", "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(spec.model_dump_json(indent=2))

        print(f"📦 [SPEC] Saved spec artifact to '{spec_path}' ({len(scenes_spec)} scenes, {total_duration:.1f}s)")


def main():
    parser = argparse.ArgumentParser(description="Pika Flow Pipeline Runner (v2.0)")
    parser.add_argument("--stage", required=True, choices=["spec", "clips", "editor", "release"], help="Stage to execute")
    parser.add_argument("--type", default="short", choices=["short", "long"], help="Video profile type")
    args = parser.parse_args()

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

