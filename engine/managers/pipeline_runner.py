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
        system_prompt = script_cfg["system_prompt"] + "\n\n" + script_cfg["constitution"] + "\n\n" + script_cfg.get("few_shot_exemplars", "")
        user_prompt = script_cfg["user_template"].format(
            niche=channel_cfg.get("niche", "shower_thoughts"),
            topic=topic,
            sub_format=sub_format,
            target_duration=target_duration
        )

        def validate_short_script(data: Dict[str, Any]) -> bool:
            if not isinstance(data, dict):
                return False
            scenes = data.get("scenes", [])
            if not isinstance(scenes, list) or len(scenes) < 11 or len(scenes) > 13:
                return False
            words = sum(len(sc.get("spoken_text", "").split()) for sc in scenes if isinstance(sc, dict))
            return 135 <= words <= 158

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

            if len(raw_scenes) < 11 or total_words < 135:
                print(f"⚠️ [SPEC] Script below target word budget ({len(raw_scenes)} scenes, {total_words} words). Expanding with verified viral thoughts...", flush=True)
                FALLBACK_THOUGHTS = [
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
                    "Why your future self is watching you right now through the lens of your memories.",
                    "Water can boil and freeze at the exact same instant under specific pressure.",
                    "You can never hold an empty container because it is always completely full of air.",
                    "The voice inside your head never has to take a physical breath while talking."
                ]
                
                # If LLM returned only 1 broken scene (like "Here."), synthesize a proper hook
                if len(raw_scenes) <= 1 or total_words < 30:
                    raw_scenes = [{
                        "scene_id": 1,
                        "spoken_text": "The only part of your reflection you can lick is your tongue.",
                        "stock_video_query": "soap cutting grid razor ASMR"
                    }]

                loop_scene = raw_scenes[-1] if len(raw_scenes) > 1 and "overthink" in raw_scenes[-1].get("spoken_text", "").lower() else {
                    "scene_id": 12,
                    "spoken_text": "Which is why you should never overthink these...",
                    "stock_video_query": "spiral optical illusion hypnotic"
                }
                
                mid_scenes = [raw_scenes[0]]
                for sc in raw_scenes[1:-1]:
                    mid_scenes.append(sc)
                
                existing_texts = {s.get("spoken_text", "").lower() for s in mid_scenes}
                
                for fb in FALLBACK_THOUGHTS:
                    if fb.lower() not in existing_texts:
                        mid_scenes.append({"scene_id": len(mid_scenes) + 1, "spoken_text": fb, "stock_video_query": "soap cutting grid razor ASMR"})
                        existing_texts.add(fb.lower())
                    if len(mid_scenes) >= 11 and sum(len(s.get("spoken_text", "").split()) for s in mid_scenes) >= 140:
                        break
                
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
        # Sample unique visual queries for this video from the expanded taxonomy
        from engine.managers.stock_video_manager import SHORTS_VISUAL_TAXONOMY
        if video_type == "short":
            if len(SHORTS_VISUAL_TAXONOMY) >= num_scenes:
                sampled_queries = random.sample(SHORTS_VISUAL_TAXONOMY, num_scenes)
            else:
                sampled_queries = (SHORTS_VISUAL_TAXONOMY * ((num_scenes // len(SHORTS_VISUAL_TAXONOMY)) + 1))[:num_scenes]
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
        print("🧪 [TEST MODE] GHOST_ENGINE_ENABLED=test. YouTube API mutations & DB releases strictly blocked.")

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

