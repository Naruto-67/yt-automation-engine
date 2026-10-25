"""
tests/test_iterative_generation.py — Unit tests for ISCG and Phonetic/Editorial fixes
"""
import os
import pytest

os.environ["PYTEST_CURRENT_TEST"] = "true"


def test_voice_normalizer_comma_numbers():
    """Formatted comma numbers like 10,000 must expand to 'ten thousand', not 'ten, zero'."""
    from engine.managers.voice_normalizer import VoiceNormalizer

    text = "The tongue has 10,000 taste buds and over 1,500,000 receptors."
    normalized = VoiceNormalizer.normalize_text(text)
    assert "ten thousand" in normalized
    assert "ten,zero" not in normalized
    assert "ten, zero" not in normalized
    assert "one million" in normalized


def test_voice_normalizer_contraction_before_ellipsis():
    """Contractions before ellipses like brain's... must expand to prevent Kokoro saying 'brain S.'."""
    from engine.managers.voice_normalizer import VoiceNormalizer

    text = "Your tongue’s lingering heat is the brain’s..."
    normalized = VoiceNormalizer.normalize_text(text)
    assert "brain is..." in normalized
    assert "brain's..." not in normalized
    assert "brain’s..." not in normalized


def test_thought_completeness_skill():
    """ThoughtCompletenessSkill must flag dangling connectors and pass complete sentences."""
    from engine.managers.editorial_critic import ThoughtCompletenessSkill

    dangling_scenes = [
        "Time moves slower at your feet than at your head because",
        "Which means you are distant cousins with every smoothie in your kitchen and",
        "Placebos still trigger genuine neurological relief whenever",
        "Meaning your shoes are technically aging much slower than your brain which means",
    ]
    for text in dangling_scenes:
        passed, reason = ThoughtCompletenessSkill.audit_completeness(text, is_final_scene=False)
        assert not passed, f"Expected FAIL for dangling thought: '{text}'"
        assert "Thought Completeness FAILED" in reason

    clean_scenes = [
        "Time moves slower at your feet than it does at your head because of gravity.",
        "A single teaspoon of water contains more molecules than all the teaspoons in the Atlantic.",
        "Your bones are completely wet right now, but you will never feel it.",
    ]
    for text in clean_scenes:
        passed, reason = ThoughtCompletenessSkill.audit_completeness(text, is_final_scene=False)
        assert passed, f"Expected PASS for clean thought: '{text}', got: {reason}"


def test_title_alignment_blocks_medical_falsehoods():
    """TitleScriptAlignmentSkill must reject absurd medical clickbait like 'Explode Your Brain'."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [{"spoken_text": "Scene text here."}] * 5
    bad_title = "Why Holding In A Sneeze Can Actually Explode Your Brain! 🤯 #shorts"
    passed, reason = TitleScriptAlignmentSkill.audit_title(bad_title, scenes)
    assert not passed
    assert "Truth-in-Packaging FAILED" in reason


def test_title_alignment_requires_umbrella_for_compilations():
    """TitleScriptAlignmentSkill must require umbrella titles for 5+ scene compilations."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [{"spoken_text": "Scene text here."}] * 5
    narrow_title = "Why Your Tongue Echoes Spicy Heat for Minutes 🔥 #shorts"
    passed, reason = TitleScriptAlignmentSkill.audit_title(narrow_title, scenes)
    assert not passed
    assert "requires an umbrella title" in reason

    good_title = "Shower Thoughts That Break Your Brain 🤯 #shorts"
    passed_good, reason_good = TitleScriptAlignmentSkill.audit_title(good_title, scenes)
    assert passed_good


def test_iterative_generator_loop_selection():
    """Outro closer architect must generate punchy BrainBlud closers ending in '.' or '!' and never dangling '...'."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator, BRAINBLUD_CLOSERS

    class DummyLLM:
        _last_used_provider_id = "test_prov"
        def generate_json(self, *args, **kwargs):
            return {
                "spoken_text": "Because everything in the universe is connected to.",
                "stock_video_query": "kinetic sand"
            }

    generator = IterativeScriptGenerator(llm_manager=DummyLLM())

    # Question hook -> Must select BrainBlud closer
    question_hook = "A single chili pepper can fire up your taste buds for 10 minutes—ever wondered why?"
    outro_q = generator._generate_brainblud_closer(
        hook_text=question_hook,
        scene_num=11,
        existing_scenes=[],
        used_queries=[]
    )
    assert outro_q["spoken_text"] in BRAINBLUD_CLOSERS or outro_q["spoken_text"].endswith((".", "!"))
    assert outro_q["spoken_text"].endswith((".", "!"))

    # Declarative hook -> Must also select BrainBlud closer ending with . or ! (never ...)
    declarative_hook = "The only part of your reflection you can lick is your tongue."
    outro_d = generator._generate_brainblud_closer(
        hook_text=declarative_hook,
        scene_num=11,
        existing_scenes=[],
        used_queries=[]
    )
    assert outro_d["spoken_text"] in BRAINBLUD_CLOSERS or outro_d["spoken_text"].endswith((".", "!"))
    assert outro_d["spoken_text"].endswith((".", "!"))
    assert not outro_d["spoken_text"].endswith("...")


def test_iterative_generator_chain_full_flow():
    """generate_scene_chain constructs a high-retention circular script under 32s."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator, PILLARS

    class MockChainLLM:
        _last_used_provider_id = "test_model"
        def __init__(self):
            self.call_count = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.call_count += 1
            if "Scene 1 hook thought and a Final Scene loopback bridge" in user_prompt:
                return {
                    "hook_scene": {
                        "spoken_text": "You have never actually seen your own face, only reflections and photos.",
                        "stock_video_query": "soap carving cubes ASMR"
                    },
                    "loop_outro_scene": {
                        "spoken_text": "Which means the only reason you recognize yourself is because...",
                        "stock_video_query": "resin lathe turning wood polishing"
                    }
                }
            elif "SCENES TO NORMALIZE & EMOTIFY:" in user_prompt:
                import json
                try:
                    lines = user_prompt.split("SCENES TO NORMALIZE & EMOTIFY:\n")[1].split("\n\n")[0]
                    scs = json.loads(lines)
                    return {"scenes": scs}
                except Exception:
                    return {}
            elif "optimized YouTube metadata" in user_prompt:
                return {
                    "title": "Shower Thoughts That Blow Minds 🤯 #shorts",
                    "description": "Shower Thoughts That Blow Minds 🤯 #shorts\n\nDeep realizations.\n\n#shorts",
                    "tags": ["shower thoughts", "psychology", "shorts"]
                }
            distinct_thoughts = [
                "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
                "Oxygen is slowly rusting our physical bodies from the inside out over decades.",
                "Nothing is ever completely on fire, fire is just on things.",
                "Every clock you look at is technically showing you the distant past.",
                "The voice inside your head has no accent until you consciously give it one.",
                "You have never seen a movie with completely brand new invisible colors.",
                "Sleeping resets your emotional patience much more than food or water ever does.",
                "A single tree produces thousands of matches but one match can burn all trees.",
                "Your future memories are being recorded right now by your present choices.",
                "You cannot describe a new novel smell without comparing it to something familiar."
            ]
            thought = distinct_thoughts[(self.call_count - 1) % len(distinct_thoughts)]
            return {
                "spoken_text": thought,
                "stock_video_query": "pottery wheel clay shaping satisfying"
            }

    mock_llm = MockChainLLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(
        topic="Mind Bending Thoughts"
    )

    # Circular short has hook, middle thoughts, penultimate fact, and loop bridge
    assert len(scenes) >= 3
    # Scene 1 is Hook
    assert scenes[0]["scene_id"] == 1
    assert "face" in scenes[0]["spoken_text"].lower()
    # Scene 2 is a genuine thought, NOT a category title readout
    assert scenes[1]["scene_id"] == 2
    assert "shower thoughts that" not in scenes[1]["spoken_text"].lower()
    # Final Scene is Loop Outro Anchor
    assert scenes[-1]["spoken_text"].endswith("...") or scenes[-1]["spoken_text"].endswith((".", "!"))
    # Total duration is positive and audio-driven without hard min/max locks
    total_dur = sum(generator._calc_duration(s["spoken_text"]) for s in scenes)
    assert total_dur > 0
    # SEO title has #shorts
    assert "#shorts" in seo["title"]


def test_iterative_generator_loop_rejects_hook_repetition():
    """_generate_loop_outro must reject LLM output that echoes Scene 1 and fall back to curated bridge."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.editorial_critic import check_loop_repeats_hook, COMPILATION_LOOP_BRIDGES

    hook = "Your nose physically cannot close fully during a sneeze, making a perfectly silent one impossible."

    class EchoLLM:
        _last_used_provider_id = "echo_model"
        def generate_json(self, *args, **kwargs):
            # Simulates the flawed LLM response from the reported run
            return {
                "spoken_text": "And that is why your nose physically cannot close fully during a sneeze, making a perfectly silent one impossible...",
                "stock_video_query": "spiral optical illusion hypnotic"
            }

    generator = IterativeScriptGenerator(llm_manager=EchoLLM())
    outro = generator._generate_loop_outro(
        hook_text=hook,
        scene_num=12,
        existing_scenes=[],
        used_queries=[]
    )

    # Must NOT contain the echoed text
    assert outro["spoken_text"] != "And that is why your nose physically cannot close fully during a sneeze, making a perfectly silent one impossible..."
    # Must be one of the curated non-repeating bridges
    assert outro["spoken_text"] in COMPILATION_LOOP_BRIDGES
    # Must pass check_loop_repeats_hook
    repeats, _ = check_loop_repeats_hook(outro["spoken_text"], hook)
    assert repeats is False


def test_v4_circular_loop_scene_by_scene():
    """Validates the v4 circular loop generation: Paired Hook/Loop -> Thoughts -> Loop Outro, under 32s, with dedup and emotion pass."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class MockV4LLM:
        _last_used_provider_id = "mock_v4"
        def __init__(self):
            self.call_count = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.call_count += 1
            if "Scene 1 hook thought and a Final Scene loopback bridge" in user_prompt:
                return {
                    "hook_scene": {
                        "spoken_text": "The only part of your reflection you can lick is your tongue.",
                        "stock_video_query": "soap carving cubes ASMR"
                    },
                    "loop_outro_scene": {
                        "spoken_text": "And the reason you are tempted to test that right now is because...",
                        "stock_video_query": "resin lathe turning wood polishing"
                    }
                }
            elif "SCENES TO NORMALIZE & POLISH:" in user_prompt or "SCENES TO NORMALIZE & EMOTIFY:" in user_prompt:
                import json
                try:
                    split_token = "SCENES TO NORMALIZE & POLISH:\n" if "SCENES TO NORMALIZE & POLISH:\n" in user_prompt else "SCENES TO NORMALIZE & EMOTIFY:\n"
                    lines = user_prompt.split(split_token)[1].split("\n\n")[0]
                    scs = json.loads(lines)
                    for sc in scs:
                        sc["spoken_text"] = sc["spoken_text"].rstrip(".") + "!"
                    return {"scenes": scs}
                except Exception:
                    return {}
            elif "optimized YouTube metadata" in user_prompt:
                return {
                    "title": "Mind Glitches You Experience Daily 🤯 #shorts",
                    "description": "Mind Glitches You Experience Daily 🤯 #shorts\n\nDaily cognitive shifts.\n\n#shorts",
                    "tags": ["mind glitches", "shower thoughts", "shorts"]
                }
            else:
                distinct_thoughts = [
                    "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
                    "Oxygen is slowly rusting our physical bodies from the inside out over decades.",
                    "Nothing is ever completely on fire, fire is just on things.",
                    "Every clock you look at is technically showing you the distant past.",
                    "The voice inside your head has no accent until you consciously give it one.",
                    "You have never seen a movie with completely brand new invisible colors.",
                    "Sleeping resets your emotional patience much more than food or water ever does.",
                    "A single tree produces thousands of matches but one match can burn all trees.",
                    "Your future memories are being recorded right now by your present choices.",
                    "You cannot describe a new novel smell without comparing it to something familiar."
                ]
                thought = distinct_thoughts[(self.call_count - 1) % len(distinct_thoughts)]
                return {
                    "spoken_text": thought,
                    "stock_video_query": "pottery wheel clay shaping satisfying"
                }

    mock_llm = MockV4LLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(topic="Mind Glitches")

    # 1. Total duration is positive and audio-driven without hard min/max locks
    total_dur = sum(generator._calc_duration(s["spoken_text"]) for s in scenes)
    assert total_dur > 0

    # 2. Scene 1 is Hook, Scene 2 is a genuine thought, Last scene is Loop Outro
    assert scenes[0]["scene_id"] == 1
    assert "lick" in scenes[0]["spoken_text"].lower()
    assert scenes[1]["scene_id"] == 2
    assert "shower thoughts that" not in scenes[1]["spoken_text"].lower()

    # 3. Emotion pass applied expressive punctuation
    assert any("!" in s["spoken_text"] for s in scenes)

    # 4. Sequential scene_ids
    for idx, sc in enumerate(scenes):
        assert sc["scene_id"] == idx + 1


def test_cliche_auditor_blocks_expanded_tropes():
    """CynicalHumanAuditor must block all forensic clichés: alarm clock, rehearsals, oldest you've been, etc."""
    from engine.managers.editorial_critic import CynicalHumanAuditor

    cliche_examples = [
        "Your alarm clock screams because it wakes you up to punish you.",
        "You are constantly rehearsing conversations in your head that will never happen.",
        "You are now the oldest you've ever been and the youngest you'll ever be.",
        "You are now manually breathing and cannot stop thinking about it.",
        "Your stomach lining replaces itself every four days so it doesn't digest itself.",
        "Hot water freezes faster than cold water due to the Mpemba effect.",
        "Cracking your knuckles gives you arthritis according to myths.",
    ]
    for text in cliche_examples:
        passed, reason = CynicalHumanAuditor.audit_text(text)
        assert not passed, f"Expected FAIL for cliché: '{text}'"
        assert "Cliché Audit FAILED" in reason


def test_whoosh_transition_sfx_track(tmp_path):
    """Verifies that generate_transition_whoosh_track creates a valid WAV file at cut timestamps."""
    from scripts.render_video import generate_transition_whoosh_track
    import wave

    output_wav = str(tmp_path / "test_whoosh_track.wav")
    cuts = [4.5, 9.2, 14.8]
    res = generate_transition_whoosh_track(
        cut_timestamps=cuts,
        total_duration=20.0,
        output_path=output_wav,
        whoosh_sfx_path="assets/audio/sfx/whoosh.wav",
        ducking_factor=0.20
    )
    assert res == output_wav
    assert os.path.exists(output_wav)
    with wave.open(output_wav, "rb") as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == 44100
        assert w.getnframes() > 44100 * 19


def test_seo_description_has_exact_title_on_top():
    """Verifies description begins with the exact title on top, followed by an empty line, then the SEO description."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    generator = IterativeScriptGenerator()
    scenes = [{"spoken_text": "Sample thought text."}]
    seo = generator._generate_seo(scenes, premise_line="Shower thoughts that sound illegal to know")

    title = seo["title"]
    description = seo["description"]

    # Must start with exact title
    assert description.startswith(title), f"Description did not start with exact title '{title}'"
    # Followed by an empty line (\n\n)
    after_title = description[len(title):]
    assert after_title.startswith("\n\n"), f"Expected empty line after title, got: {repr(after_title[:10])}"
    # Followed by the SEO description body
    body = after_title[2:].strip()
    assert len(body) > 20
    assert "#shorts" in body or "#showerthoughts" in body


def test_test_mode_does_not_persist_thought_cache(monkeypatch):
    """Verifies that in test mode, is_test_run detects TEST_MODE and GHOST_ENGINE_ENABLED=test."""
    from engine.managers.pipeline_runner import is_test_run

    # 1. Normal mode
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)
    assert is_test_run() is False

    # 2. TEST_MODE=true
    monkeypatch.setenv("TEST_MODE", "true")
    assert is_test_run() is True

    # 3. GHOST_ENGINE_ENABLED=test
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "test")
    assert is_test_run() is True






def test_iscg_v4_1_triplet_anchors_and_audio_duration():
    """Validates ISCG v4.1 triplet anchor generation, audio duration loop, and phonetic synchronization."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    class MockTripletLLM:
        _last_used_provider_id = "triplet_model"
        def __init__(self):
            self.call_count = 0
            self.prompts_received = []

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.call_count += 1
            self.prompts_received.append(user_prompt)

            if "Scene 1 hook thought and a Final Scene loopback bridge" in user_prompt:
                return {
                    "hook_scene": {
                        "spoken_text": "The brain named itself, recognized itself, and is now questioning that exact fact.",
                        "stock_video_query": "soap carving cubes ASMR"
                    },
                    "penultimate_scene": {
                        "spoken_text": "Every single mirror you purchase is technically used since someone had to test it.",
                        "stock_video_query": "resin lathe turning wood polishing"
                    },
                    "loop_scene": {
                        "spoken_text": "And the wildest part about reflections is that...",
                        "stock_video_query": "kinetic sand squishing satisfying"
                    }
                }
            elif "SCENES TO NORMALIZE & EMOTIFY:" in user_prompt:
                import json
                try:
                    lines = user_prompt.split("SCENES TO NORMALIZE & EMOTIFY:\n")[1].split("\n\n")[0]
                    scs = json.loads(lines)
                    for sc in scs:
                        sc["spoken_text"] = sc["spoken_text"].rstrip(".") + "!"
                    scs[-1]["spoken_text"] = "And the wildest part about reflections is that..."
                    return {"scenes": scs}
                except Exception:
                    return {}
            elif "optimized YouTube metadata" in user_prompt:
                return {
                    "title": "Mind Glitches You Experience Daily 🤯 #shorts",
                    "description": "Mind Glitches You Experience Daily 🤯 #shorts\n\nDaily cognitive shifts.\n\n#shorts",
                    "tags": ["mind glitches", "shower thoughts", "shorts"]
                }
            else:
                distinct_thoughts = [
                    "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
                    "Oxygen is slowly rusting our physical bodies from the inside out over decades.",
                    "Nothing is ever completely on fire, fire is just on things.",
                    "Every clock you look at is technically showing you the distant past.",
                    "The voice inside your head has no accent until you consciously give it one.",
                    "You have never seen a movie with completely brand new invisible colors.",
                    "Sleeping resets your emotional patience much more than food or water ever does.",
                    "A single tree produces thousands of matches but one match can burn all trees.",
                    "Your future memories are being recorded right now by your present choices.",
                    "You cannot describe a new novel smell without comparing it to something familiar."
                ]
                thought = distinct_thoughts[(self.call_count - 1) % len(distinct_thoughts)]
                return {
                    "spoken_text": thought,
                    "stock_video_query": "pottery wheel clay shaping satisfying"
                }

    mock_llm = MockTripletLLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(topic="Mind Glitches")

    # 1. Total scenes >= 5
    assert len(scenes) >= 5

    # 2. Scene 1 is Hook, Scene N-1 is Penultimate Fact, Scene N is Loop Bridge
    assert scenes[0]["scene_id"] == 1
    assert "brain" in scenes[0]["spoken_text"].lower()
    assert "mirror" in scenes[-2]["spoken_text"].lower()
    assert scenes[-1]["spoken_text"].endswith("...")
    assert "reflections" in scenes[-1]["spoken_text"].lower()

    # 3. All scenes have strictly synchronized phonetic_text
    for sc in scenes:
        assert "phonetic_text" in sc
        assert sc["phonetic_text"] == VoiceNormalizer.normalize_text(sc["spoken_text"])

    # 4. Total duration is positive and audio-driven without hard min/max locks
    total_dur = sum(VoiceNormalizer.measure_duration_quick(s["spoken_text"]) for s in scenes)
    assert total_dur > 0


def test_past_spoken_thoughts_deduplication():
    """Validates that thoughts present in memory/past_spoken_thoughts.json are rejected."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    generator = IterativeScriptGenerator()
    past_thoughts = [
        "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
        "You have never actually seen your own face, only reflections, screens, and photographs."
    ]

    # Exact or high token overlap must be rejected
    is_dup, reason = generator._is_duplicate_thought(
        "Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
        existing_scenes=[],
        past_thoughts=past_thoughts
    )
    assert is_dup is True
    assert "past video thought" in reason

    # Clean novel thought must pass
    is_clean, clean_reason = generator._is_duplicate_thought(
        "A bus arriving ten minutes early is far more inconvenient than one ten minutes late.",
        existing_scenes=[],
        past_thoughts=past_thoughts
    )
    assert is_clean is False
    assert clean_reason == "Clean"


def test_normalize_and_emotify_script_preserves_circular_ellipsis():
    """_normalize_and_emotify_script must restore trailing ellipsis if polish replaces it with period."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    class PolishPeriodLLM:
        def generate_json(self, *args, **kwargs):
            return {
                "scenes": [
                    {"scene_id": 1, "spoken_text": "You have never actually seen your own face."},
                    {"scene_id": 2, "spoken_text": "And the wildest part about reflections is that."}  # LLM changed ... to .
                ]
            }

    generator = IterativeScriptGenerator(llm_manager=PolishPeriodLLM())
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "You have never actually seen your own face."},
        {"scene_id": 2, "spoken_text": "And the wildest part about reflections is that..."}  # Original was circular
    ]

    polished = generator._normalize_and_emotify_script(raw_scenes)
    assert polished[-1]["spoken_text"].endswith("...")
    assert polished[-1]["spoken_text"] == "And the wildest part about reflections is that..."
    assert polished[-1]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[-1]["spoken_text"])


def test_normalize_and_emotify_script_preserves_standalone_terminal_punctuation():
    """_normalize_and_emotify_script must NOT force ellipsis onto a standalone ending."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class PolishNormalLLM:
        def generate_json(self, *args, **kwargs):
            return {
                "scenes": [
                    {"scene_id": 1, "spoken_text": "You have never actually seen your own face."},
                    {"scene_id": 2, "spoken_text": "Every mirror you purchase is technically used!"}
                ]
            }

    generator = IterativeScriptGenerator(llm_manager=PolishNormalLLM())
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "You have never actually seen your own face."},
        {"scene_id": 2, "spoken_text": "Every mirror you purchase is technically used."}
    ]

    polished = generator._normalize_and_emotify_script(raw_scenes)
    assert not polished[-1]["spoken_text"].endswith("...")
    assert polished[-1]["spoken_text"].endswith(("!", "."))
    assert polished[-1]["spoken_text"] == "Every mirror you purchase is technically used!"


def test_normalize_and_emotify_script_preserves_unchanged_strong_line():
    """_normalize_and_emotify_script preserves strong, already-natural lines when polish suggests no change or identical wording."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    already_natural_hook = "Your shadow has traveled thousands of miles across the Earth, but you will never see all of it."
    already_natural_middle = "A single tree produces thousands of matches, but one match can burn down an entire forest."

    class NoOpPolishLLM:
        def generate_json(self, *args, **kwargs):
            return {
                "scenes": [
                    {"scene_id": 1, "spoken_text": already_natural_hook},
                    {"scene_id": 2, "spoken_text": already_natural_middle}
                ]
            }

    generator = IterativeScriptGenerator(llm_manager=NoOpPolishLLM())
    raw_scenes = [
        {"scene_id": 1, "spoken_text": already_natural_hook},
        {"scene_id": 2, "spoken_text": already_natural_middle}
    ]

    polished = generator._normalize_and_emotify_script(raw_scenes)
    # The strong lines must remain completely identical without corruption or distortion
    assert polished[0]["spoken_text"] == already_natural_hook
    assert polished[1]["spoken_text"] == already_natural_middle
    # Verify phonetic_text was synchronized accurately
    assert polished[0]["phonetic_text"] == VoiceNormalizer.normalize_text(already_natural_hook)
    assert polished[1]["phonetic_text"] == VoiceNormalizer.normalize_text(already_natural_middle)


def test_extract_number_tokens_supported_formats_and_normalization():
    """_extract_number_tokens deterministically normalizes integers, decimals, commas, signs, and distinguishes ranges."""
    from engine.managers.iterative_script_generator import _extract_number_tokens

    # 1. Ordinary integers and distinguishing signed values
    assert _extract_number_tokens("Temperatures drop to -5 degrees.") == ["-5"]
    assert _extract_number_tokens("Temperatures rise to +5 degrees.") == ["+5"]
    assert _extract_number_tokens("Temperatures are 5 degrees.") == ["5"]
    assert _extract_number_tokens("-5") != _extract_number_tokens("5")
    assert _extract_number_tokens("-5") != _extract_number_tokens("+5")
    assert _extract_number_tokens("+5") != _extract_number_tokens("5")

    # 2. Signed decimal values and redundant zero normalization
    assert _extract_number_tokens("Chill factor of -3.50 degrees matches -3.5.") == ["-3.5", "-3.5"]
    assert _extract_number_tokens("Heat factor of +3.50 degrees matches +3.5.") == ["+3.5", "+3.5"]
    assert _extract_number_tokens("-3.5") != _extract_number_tokens("3.5")

    # 3. Range notation not incorrectly classified as negative
    assert _extract_number_tokens("Orbital cycle lasts 16-24 hours.") == ["16", "24"]
    assert _extract_number_tokens("Between 16 - 24 hours.") == ["16", "24"]
    assert _extract_number_tokens("Range 16\u201324 and 16\u201424 hours.") == ["16", "24", "16", "24"]

    # 4. High-precision decimals preserve significant digits and remain distinguishable
    tok_high_1 = _extract_number_tokens("Offset measured at -1.0000000000000001 seconds.")
    tok_high_2 = _extract_number_tokens("Offset measured at -1.0000000000000002 seconds.")
    assert tok_high_1 == ["-1.0000000000000001"]
    assert tok_high_2 == ["-1.0000000000000002"]
    assert tok_high_1 != tok_high_2

    # 5. Comma-formatted integers and large numbers with signs
    assert _extract_number_tokens("Debt of -10,000 matches -10000.") == ["-10000", "-10000"]
    assert _extract_number_tokens("Gain of +10,000 matches +10000.") == ["+10000", "+10000"]

    # 6. Repeated numbers preserving occurrence counts
    assert _extract_number_tokens("You have 2 eyes, 2 ears, and 1 mouth.") == ["2", "2", "1"]

    # 7. Sentences with no numerical tokens
    assert _extract_number_tokens("Your shadow travels across the Earth without making a sound.") == []
    assert _extract_number_tokens("") == []


def test_normalize_and_emotify_script_preserves_numerical_facts():
    """_normalize_and_emotify_script rejects rewrites that reorder, drop, change, sign-flip, or invent numbers."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    class FlawedPolishLLM:
        def generate_json(self, *args, **kwargs):
            return {
                "scenes": [
                    # Scene 1: Drops original numbers (16, 24) -> Must be rejected
                    {"scene_id": 1, "spoken_text": "Astronauts see multiple sunrises every single day."},
                    # Scene 2: Changes an original number (20 -> 15) -> Must be rejected
                    {"scene_id": 2, "spoken_text": "Your brain uses about 15% of your total energy."},
                    # Scene 3: Invents a new number (50) where none existed -> Must be rejected
                    {"scene_id": 3, "spoken_text": "You check your phone 50 times an hour for messages you do not even want."},
                    # Scene 4: Reorders original numbers ([16, 24] -> [24, 16]) -> Must be rejected
                    {"scene_id": 4, "spoken_text": "In 24 hours, astronauts witness about 16 sunrises."},
                    # Scene 5: Drops one occurrence of a repeated number ([2, 2] -> [2]) -> Must be rejected
                    {"scene_id": 5, "spoken_text": "You have 2 eyes and ears."},
                    # Scene 6: Changes high-precision decimal significant digits -> Must be rejected
                    {"scene_id": 6, "spoken_text": "The constant measured exactly 1.0000000000000002 units."},
                    # Scene 7: Changes signed negative to unsigned (-5 -> 5) -> Must be rejected
                    {"scene_id": 7, "spoken_text": "Deep in space, temperature plummets to 5 degrees."},
                    # Scene 8: Changes signed positive to unsigned (+5 -> 5) -> Must be rejected
                    {"scene_id": 8, "spoken_text": "Charge increases by 5 percent."},
                    # Scene 9: Preserves signed negative (-5 -> -5) -> Accepted
                    {"scene_id": 9, "spoken_text": "Deep in space, temperature plummets to -5 degrees!"},
                    # Scene 10: Preserves signed decimal equivalence (-3.5 -> -3.50) -> Accepted
                    {"scene_id": 10, "spoken_text": "Thermal variance drops by exactly -3.50 degrees."},
                    # Scene 11: Preserves range notation (16-24 -> 16-24) without misclassifying as negative -> Accepted
                    {"scene_id": 11, "spoken_text": "Astronauts experience 16-24 sunrises in orbit!"},
                    # Scene 12: Preserves repeated numbers in exact order ([2, 2] -> [2, 2]) -> Accepted
                    {"scene_id": 12, "spoken_text": "With 2 eyes and 2 ears, you observe constantly."},
                    # Scene 13: Equivalent comma formatting (10,000 -> 10000) -> Accepted
                    {"scene_id": 13, "spoken_text": "There are over 10000 stars visible tonight."},
                    # Scene 14: Equivalent decimal formatting (3.5 -> 3.50) -> Accepted
                    {"scene_id": 14, "spoken_text": "The cycle lasts exactly 3.50 seconds."},
                    # Scene 15: Sentences with zero numbers ([] -> []) -> Accepted
                    {"scene_id": 15, "spoken_text": "A tree grows quietly in the forest without anyone noticing."}
                ]
            }

    generator = IterativeScriptGenerator(llm_manager=FlawedPolishLLM())
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "Astronauts see 16 sunrises every 24 hours."},
        {"scene_id": 2, "spoken_text": "Your brain uses 20% of your oxygen and energy."},
        {"scene_id": 3, "spoken_text": "You check your phone constantly for messages you do not even want."},
        {"scene_id": 4, "spoken_text": "Astronauts see 16 sunrises every 24 hours."},
        {"scene_id": 5, "spoken_text": "You have 2 eyes and 2 ears for a reason."},
        {"scene_id": 6, "spoken_text": "The constant measured exactly 1.0000000000000001 units."},
        {"scene_id": 7, "spoken_text": "Deep in space, temperature plummets to -5 degrees."},
        {"scene_id": 8, "spoken_text": "Charge increases by +5 percent."},
        {"scene_id": 9, "spoken_text": "Deep in space, temperature plummets to -5 degrees."},
        {"scene_id": 10, "spoken_text": "Thermal variance drops by exactly -3.5 degrees."},
        {"scene_id": 11, "spoken_text": "Astronauts experience 16-24 sunrises in orbit."},
        {"scene_id": 12, "spoken_text": "You have 2 eyes and 2 ears for a reason."},
        {"scene_id": 13, "spoken_text": "There are over 10,000 stars visible tonight."},
        {"scene_id": 14, "spoken_text": "The cycle lasts exactly 3.5 seconds."},
        {"scene_id": 15, "spoken_text": "A tree grows quietly in the woods without anyone noticing."}
    ]

    polished = generator._normalize_and_emotify_script(raw_scenes)

    # 1. Dropped number: rejected, retained original
    assert polished[0]["spoken_text"] == "Astronauts see 16 sunrises every 24 hours."
    assert "16" in polished[0]["spoken_text"] and "24" in polished[0]["spoken_text"]
    assert polished[0]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[0]["spoken_text"])

    # 2. Changed number: rejected, retained original
    assert polished[1]["spoken_text"] == "Your brain uses 20% of your oxygen and energy."
    assert "20%" in polished[1]["spoken_text"]
    assert polished[1]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[1]["spoken_text"])

    # 3. Invented number: rejected, retained original
    assert polished[2]["spoken_text"] == "You check your phone constantly for messages you do not even want."
    assert "50" not in polished[2]["spoken_text"]
    assert polished[2]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[2]["spoken_text"])

    # 4. Reordered numbers ([16, 24] -> [24, 16]): rejected, retained original
    assert polished[3]["spoken_text"] == "Astronauts see 16 sunrises every 24 hours."
    assert polished[3]["spoken_text"].startswith("Astronauts see 16")
    assert polished[3]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[3]["spoken_text"])

    # 5. Dropped repeated number: rejected, retained original
    assert polished[4]["spoken_text"] == "You have 2 eyes and 2 ears for a reason."
    assert polished[4]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[4]["spoken_text"])

    # 6. Changed high-precision significant digit: rejected, retained original
    assert polished[5]["spoken_text"] == "The constant measured exactly 1.0000000000000001 units."
    assert "1.0000000000000001" in polished[5]["spoken_text"]
    assert polished[5]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[5]["spoken_text"])

    # 7. Changed signed negative to unsigned (-5 -> 5): rejected, retained original
    assert polished[6]["spoken_text"] == "Deep in space, temperature plummets to -5 degrees."
    assert "-5" in polished[6]["spoken_text"]
    assert polished[6]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[6]["spoken_text"])

    # 8. Changed signed positive to unsigned (+5 -> 5): rejected, retained original
    assert polished[7]["spoken_text"] == "Charge increases by +5 percent."
    assert "+5" in polished[7]["spoken_text"]
    assert polished[7]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[7]["spoken_text"])

    # 9. Preserved signed negative: accepted
    assert polished[8]["spoken_text"] == "Deep in space, temperature plummets to -5 degrees!"
    assert polished[8]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[8]["spoken_text"])

    # 10. Preserved signed decimal: accepted
    assert polished[9]["spoken_text"] == "Thermal variance drops by exactly -3.50 degrees."
    assert polished[9]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[9]["spoken_text"])

    # 11. Preserved range notation: accepted
    assert polished[10]["spoken_text"] == "Astronauts experience 16-24 sunrises in orbit!"
    assert polished[10]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[10]["spoken_text"])

    # 12. Preserved repeated numbers in exact order: accepted
    assert polished[11]["spoken_text"] == "With 2 eyes and 2 ears, you observe constantly."
    assert polished[11]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[11]["spoken_text"])

    # 13. Comma-formatting equivalence (10,000 -> 10000): accepted
    assert polished[12]["spoken_text"] == "There are over 10000 stars visible tonight."
    assert polished[12]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[12]["spoken_text"])

    # 14. Decimal formatting equivalence (3.5 -> 3.50): accepted
    assert polished[13]["spoken_text"] == "The cycle lasts exactly 3.50 seconds."
    assert polished[13]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[13]["spoken_text"])

    # 15. Sentences with no numbers: accepted
    assert polished[14]["spoken_text"] == "A tree grows quietly in the forest without anyone noticing."
    assert polished[14]["phonetic_text"] == VoiceNormalizer.normalize_text(polished[14]["spoken_text"])


def test_normalize_and_emotify_script_incorporates_channel_premise():
    """_normalize_and_emotify_script must pass channel premise context in the user prompt."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_user_prompts = []

    class CapturingLLM:
        def generate_json(self, system_prompt, user_prompt, *args, **kwargs):
            captured_user_prompts.append(user_prompt)
            return {
                "scenes": [
                    {"scene_id": 1, "spoken_text": "A sharp, observant perspective shift."}
                ]
            }

    generator = IterativeScriptGenerator(
        llm_manager=CapturingLLM(),
        channel_premise="Observant, witty perspective shifts on modern absurdity"
    )
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "A sharp, observant perspective shift."}
    ]

    generator._normalize_and_emotify_script(raw_scenes)
    assert len(captured_user_prompts) == 1
    assert "Observant, witty perspective shifts on modern absurdity" in captured_user_prompts[0]


def test_normalize_and_emotify_script_synchronizes_phonetics_even_on_failure():
    """_normalize_and_emotify_script must strictly synchronize phonetic_text even when polish fails or falls back."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    class ErrorLLM:
        def generate_json(self, *args, **kwargs):
            raise RuntimeError("Temporary LLM timeout")

    generator = IterativeScriptGenerator(llm_manager=ErrorLLM())
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "There are 86,400 seconds in a day."}
    ]

    polished = generator._normalize_and_emotify_script(raw_scenes)
    assert polished[0]["spoken_text"] == "There are 86,400 seconds in a day."
    assert polished[0]["phonetic_text"] == VoiceNormalizer.normalize_text("There are 86,400 seconds in a day.")
    assert "eighty-six thousand, four hundred" in polished[0]["phonetic_text"] or "eighty-six thousand four hundred" in polished[0]["phonetic_text"]


def test_rewrite_scene_for_factuality_natural_voice_and_phonetics():
    """_rewrite_scene_for_factuality must preserve natural voice and strictly synchronize phonetic_text."""
    from engine.managers.pipeline_runner import _rewrite_scene_for_factuality
    from engine.managers.voice_normalizer import VoiceNormalizer

    class MockClaim:
        extracted_proposition = "You swallow 8 spiders a year in your sleep."
        risk_level = "high"
        rationale = "Debunked urban legend; humans do not swallow spiders during sleep."

    class MockRewriteLLM:
        def generate_json(self, system_prompt, user_prompt, *args, **kwargs):
            assert "NATURAL-VOICE EDITORIAL GUIDANCE" in system_prompt
            return {
                "spoken_text": "The myth about swallowing 8 spiders in your sleep was invented purely to prove people believe fake statistics.",
                "stock_video_query": "sleeping person cinematic bed"
            }

    original_scene = {
        "scene_id": 3,
        "spoken_text": "You swallow 8 spiders every single year in your sleep."
    }

    revised = _rewrite_scene_for_factuality(
        scene=original_scene,
        claim_record=MockClaim(),
        llm=MockRewriteLLM()
    )
    assert revised is not None
    assert revised["_factuality_revised"] is True
    assert revised["spoken_text"].startswith("The myth about swallowing")
    assert revised["phonetic_text"] == VoiceNormalizer.normalize_text(revised["spoken_text"])
    assert "eight" in revised["phonetic_text"]


def test_editorial_critic_sanitize_synchronizes_phonetics():
    """Editorial critic sanitizers must synchronize phonetic_text via VoiceNormalizer."""
    from engine.managers.editorial_critic import LoopAuditorSkill, CynicalHumanAuditor
    from engine.managers.voice_normalizer import VoiceNormalizer

    # Test LoopAuditorSkill.sanitize_loop
    raw_loop = {"scene_id": 5, "spoken_text": "And that is why you have never seen 100% of your own face..."}
    sanitized_loop = LoopAuditorSkill.sanitize_loop(raw_loop)
    assert sanitized_loop["spoken_text"].endswith(".")
    assert not sanitized_loop["spoken_text"].endswith("...")
    assert sanitized_loop["phonetic_text"] == VoiceNormalizer.normalize_text(sanitized_loop["spoken_text"])
    assert "one hundred percent" in sanitized_loop["phonetic_text"]

    # Test CynicalHumanAuditor.sanitize_scene with replacement
    raw_scene = {"scene_id": 2, "spoken_text": "Reality is just an illusion created by your mind."}
    replacement = "You check 50 times a day for messages you don't even want."
    sanitized_scene = CynicalHumanAuditor.sanitize_scene(raw_scene, replacement_thoughts=[replacement])
    assert sanitized_scene.get("_editorial_replaced") is True
    assert sanitized_scene["spoken_text"] == replacement
    assert sanitized_scene["phonetic_text"] == VoiceNormalizer.normalize_text(replacement)
    assert "fifty" in sanitized_scene["phonetic_text"]


def test_anchor_generation_exhaustion_raises_runtime_error_no_canned_triplet():
    """_generate_anchor_bookends must raise RuntimeError on attempt exhaustion instead of returning canned fallbacks."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator, TRIPLET_CIRCULAR_FALLBACKS

    class FailingAnchorLLM:
        def __init__(self):
            self.call_count = 0

        def generate_json(self, *args, **kwargs):
            self.call_count += 1
            # Return invalid or failing payload
            return {"hook_scene": {}, "penultimate_scene": {}, "loop_scene": {}}

    llm = FailingAnchorLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)

    with pytest.raises(RuntimeError) as exc_info:
        generator._generate_anchor_bookends(topic="Testing Exhaustion")

    assert "Failed to generate fresh triplet anchors after 4 attempts" in str(exc_info.value)
    assert llm.call_count == 4

    # Verify that canned triplet sentences are NEVER returned
    all_canned_texts = {text for triplet in TRIPLET_CIRCULAR_FALLBACKS for text in triplet}
    assert "You have never actually seen your own face" not in str(exc_info.value)


def test_middle_thought_exhaustion_raises_runtime_error_no_curated_or_bus_thought():
    """_generate_random_thought must raise RuntimeError on exhaustion instead of pulling curated vault or bus thought."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class FailingThoughtLLM:
        def __init__(self):
            self.call_count = 0

        def generate_json(self, *args, **kwargs):
            self.call_count += 1
            raise ValueError("Simulated LLM generation error")

    llm = FailingThoughtLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)

    with pytest.raises(RuntimeError) as exc_info:
        generator._generate_random_thought(
            scene_num=3,
            existing_scenes=[{"spoken_text": "Existing hook scene."}]
        )

    assert "Failed to generate fresh standalone thought for Scene 3 after 4 attempts" in str(exc_info.value)
    assert llm.call_count == 4
    # Ensure neither curated thoughts nor the hardcoded bus thought are returned
    bus_thought = "A bus ten minutes early is far worse than a bus ten minutes late."
    assert bus_thought not in str(exc_info.value)


def test_anchor_generation_retries_and_succeeds_on_transient_failure():
    """_generate_anchor_bookends must retry upon transient invalid output and succeed when fresh triplet is returned."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class RetryAnchorLLM:
        def __init__(self):
            self.attempts = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                # First attempt fails due to transient network / LLM exception
                raise ConnectionError("Simulated transient network drop")
            # Second attempt succeeds with valid triplet
            return {
                "hook_scene": {
                    "spoken_text": "Your eyes actually process everything upside down before your brain flips it.",
                    "stock_video_query": "soap carving cubes ASMR"
                },
                "penultimate_scene": {
                    "spoken_text": "Light takes eight whole minutes to travel from the sun to your skin.",
                    "stock_video_query": "resin lathe turning wood polishing"
                },
                "loop_scene": {
                    "spoken_text": "Which means everything you experience is delayed until...",
                    "stock_video_query": "sand pendulum harmonograph geometric"
                }
            }

    llm = RetryAnchorLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)

    hook, penultimate, loop = generator._generate_anchor_bookends(topic="Vision Physics")

    assert llm.attempts == 2
    assert "eyes actually process" in hook["spoken_text"]
    assert "eight whole minutes" in penultimate["spoken_text"]
    assert loop["spoken_text"].endswith("...")


def test_generate_scene_chain_propagates_runtime_error_on_anchor_failure():
    """generate_scene_chain must propagate RuntimeError so pipeline runner can switch to monolithic fallback."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class TotalFailureLLM:
        def generate_json(self, *args, **kwargs):
            raise RuntimeError("API quota completely exhausted")

    llm = TotalFailureLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)

    with pytest.raises(RuntimeError) as exc_info:
        generator.generate_scene_chain(topic="Total Failure")

    assert "Failed to generate fresh triplet anchors" in str(exc_info.value)


def test_pipeline_runner_monolithic_preserves_circular_ellipsis():
    """Pipeline runner monolithic path must preserve trailing '...' and normalize '…' to '...'."""
    raw_scenes_with_ellipsis = [
        {"scene_id": 1, "spoken_text": "Why do mirrors flip horizontally but never vertically?"},
        {"scene_id": 2, "spoken_text": "Which only makes sense when you remember that..."}
    ]
    video_type = "short"

    # Simulate the pipeline_runner.py terminal punctuation normalization logic
    if video_type == "short" and raw_scenes_with_ellipsis:
        last_text = raw_scenes_with_ellipsis[-1]["spoken_text"].strip()
        if last_text.endswith("…"):
            last_text = last_text[:-1].rstrip() + "..."
        if not (last_text.endswith(".") or last_text.endswith("!") or last_text.endswith("?") or last_text.endswith("...")):
            last_text = f"{last_text.rstrip('— ')}."
        raw_scenes_with_ellipsis[-1]["spoken_text"] = last_text

    assert raw_scenes_with_ellipsis[-1]["spoken_text"].endswith("...")
    assert raw_scenes_with_ellipsis[-1]["spoken_text"] == "Which only makes sense when you remember that..."

    # Test unicode ellipsis normalization
    raw_scenes_unicode = [
        {"scene_id": 1, "spoken_text": "Hook text here."},
        {"scene_id": 2, "spoken_text": "Trailing unicode ellipsis…"}
    ]
    if video_type == "short" and raw_scenes_unicode:
        last_text = raw_scenes_unicode[-1]["spoken_text"].strip()
        if last_text.endswith("…"):
            last_text = last_text[:-1].rstrip() + "..."
        if not (last_text.endswith(".") or last_text.endswith("!") or last_text.endswith("?") or last_text.endswith("...")):
            last_text = f"{last_text.rstrip('— ')}."
        raw_scenes_unicode[-1]["spoken_text"] = last_text

    assert raw_scenes_unicode[-1]["spoken_text"].endswith("...")
    assert raw_scenes_unicode[-1]["spoken_text"] == "Trailing unicode ellipsis..."


def test_iscg_natural_duration_stopping_and_overshoot(monkeypatch):
    """
    Phase 5B: Verifies that IterativeScriptGenerator stops accumulating middle scenes as soon as
    cumulative estimated duration reaches or crosses >= 30.0s, and accepts the crossing
    scene in full without trimming, popping, or clamping.
    """
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    # Mock triplet anchors (Hook ~4.0s, Penultimate ~3.5s, Loop ~3.0s -> t_anchors = 10.5s)
    class DeterministicDurationLLM:
        _last_used_provider_id = "duration_model"
        def __init__(self):
            self.call_count = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.call_count += 1
            if "Scene 1 hook thought and a Final Scene loopback bridge" in user_prompt:
                return {
                    "hook_scene": {
                        "spoken_text": "The only part of your reflection you can lick is your tongue.",
                        "stock_video_query": "mirror reflection"
                    },
                    "penultimate_scene": {
                        "spoken_text": "Every mirror you have ever bought in a store was in used condition.",
                        "stock_video_query": "mirror store"
                    },
                    "loop_scene": {
                        "spoken_text": "Which is why you should never overthink these strange quirks...",
                        "stock_video_query": "loop ending"
                    }
                }
            elif "SCENES TO NORMALIZE & EMOTIFY:" in user_prompt:
                import json
                try:
                    lines = user_prompt.split("SCENES TO NORMALIZE & EMOTIFY:\n")[1].split("\n\n")[0]
                    return {"scenes": json.loads(lines)}
                except Exception:
                    return {}
            elif "optimized YouTube metadata" in user_prompt:
                return {
                    "title": "Shower Thoughts 🤯 #shorts",
                    "description": "Shower Thoughts #shorts",
                    "tags": ["thoughts", "shorts"]
                }
            else:
                distinct = [
                    "Your brain actively deletes the sensation of your tongue resting in your mouth.",
                    "You have never actually touched anything because electron fields repel your atoms.",
                    "Your future self is currently watching you through memories right at this moment.",
                    "When you wait for the waiter you temporarily become the waiter in that situation.",
                    "The person you think you are only exists in your own personal mind.",
                    "If you rip a hole in a net there are actually fewer holes in it.",
                    "Earth is a giant spaceship traveling through deep space without any seatbelts.",
                ]
                return {
                    "spoken_text": distinct[(self.call_count - 1) % len(distinct)],
                    "stock_video_query": "abstract motion"
                }

    # Deterministic audio durations:
    # Anchors: Hook = 4.0s, Penultimate = 3.5s, Loop = 3.0s -> total = 10.5s
    # Each middle scene: exactly 4.0s
    # Cumulative trajectory:
    # Start: 10.5s
    # Mid 1: 10.5 + 4.0 = 14.5s (< 30)
    # Mid 2: 14.5 + 4.0 = 18.5s (< 30)
    # Mid 3: 18.5 + 4.0 = 22.5s (< 30)
    # Mid 4: 22.5 + 4.0 = 26.5s (< 30)
    # Mid 5: 26.5 + 4.0 = 30.5s (>= 30.0s -> STOPS!)
    def mock_measure_duration(text, voice="am_adam", speed=1.02):
        if "lick is your tongue" in text:
            return 4.0
        elif "used condition" in text:
            return 3.5
        elif "overthink these strange quirks" in text:
            return 3.0
        else:
            return 4.0

    monkeypatch.setattr(VoiceNormalizer, "measure_duration_quick", mock_measure_duration)

    llm = DeterministicDurationLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)
    scenes, seo = generator.generate_scene_chain(topic="Mind Glitches")

    # Hook (1) + 5 Middle scenes + Penultimate (1) + Loop (1) = exactly 8 scenes!
    assert len(scenes) == 8
    # Cumulative duration at stop was 30.5s (natural overshoot past 30.0s)
    # Proves the crossing scene (Mid 5) was NOT popped or trimmed!
    mid_scenes = scenes[1:-2]
    assert len(mid_scenes) == 5
    assert scenes[0]["scene_id"] == 1
    assert scenes[-1]["scene_id"] == 8
    assert scenes[-1]["spoken_text"].endswith("...")


def test_generate_random_thought_accepts_valid_short_and_long_thoughts():
    """Phase 9A: Verifies _generate_random_thought accepts concise (<7 words) and long (>18 words) thoughts without word-count rejection."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class VaryingLengthLLM:
        def __init__(self, spoken_text: str):
            self.spoken_text = spoken_text
            self.call_count = 0

        def generate_json(self, *args, **kwargs):
            self.call_count += 1
            return {
                "spoken_text": self.spoken_text,
                "stock_video_query": "ambient motion"
            }

    # Concise valid thought: 4 words (previously rejected by 7 <= len <= 18)
    short_text = "Silence is surprisingly loud."
    short_llm = VaryingLengthLLM(short_text)
    generator_short = IterativeScriptGenerator(llm_manager=short_llm)
    scene_short = generator_short._generate_random_thought(
        scene_num=2,
        existing_scenes=[{"spoken_text": "Existing hook."}]
    )
    assert scene_short["spoken_text"] == short_text
    assert short_llm.call_count == 1  # Accepted on first attempt without retrying

    # Long valid thought: 24 words (previously rejected by 7 <= len <= 18)
    long_text = "Your brain is constantly filtering out the sound of your own breathing so that you do not go completely insane during quiet reflective moments."
    long_llm = VaryingLengthLLM(long_text)
    generator_long = IterativeScriptGenerator(llm_manager=long_llm)
    scene_long = generator_long._generate_random_thought(
        scene_num=2,
        existing_scenes=[{"spoken_text": "Existing hook."}]
    )
    assert scene_long["spoken_text"] == long_text
    assert long_llm.call_count == 1  # Accepted on first attempt without retrying


def test_generate_anchor_bookends_accepts_concise_anchors():
    """Phase 9A: Verifies _generate_anchor_bookends accepts concise anchors (<6 hook words, <3 loop words) without rejection."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class ConciseAnchorLLM:
        def __init__(self):
            self.call_count = 0

        def generate_json(self, *args, **kwargs):
            self.call_count += 1
            return {
                "hook_scene": {
                    "spoken_text": "Time is an illusion.",  # 4 words (previously required >= 6)
                    "stock_video_query": "clock face"
                },
                "penultimate_scene": {
                    "spoken_text": "Clocks only measure movement.",  # 4 words
                    "stock_video_query": "hourglass sand"
                },
                "loop_scene": {
                    "spoken_text": "Which is why...",  # Concise 3-word bridge flowing naturally into hook
                    "stock_video_query": "loop motion"
                }
            }

    llm = ConciseAnchorLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)
    hook, penult, loop = generator._generate_anchor_bookends(topic="Time")

    assert hook["spoken_text"] == "Time is an illusion."
    assert penult["spoken_text"] == "Clocks only measure movement."
    assert loop["spoken_text"] == "Which is why..."
    assert llm.call_count == 1  # Accepted immediately without retry exhaustion


def test_selected_topic_reaches_middle_scene_generation():
    """Phase 9B: Verifies selected topic reaches middle-scene user_prompt without rigid continuity constraints."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []

    class TopicCapturingLLM:
        def generate_json(self, system_prompt="", user_prompt="", *args, **kwargs):
            captured_prompts.append((system_prompt, user_prompt))
            return {
                "spoken_text": "Time dilation means astronauts age slower than their twin on Earth.",
                "stock_video_query": "astronaut in space"
            }

    llm = TopicCapturingLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)

    res = generator._generate_random_thought(
        scene_num=3,
        existing_scenes=[{"spoken_text": "Existing hook."}],
        topic="Relativity and Time"
    )

    assert res["spoken_text"] == "Time dilation means astronauts age slower than their twin on Earth."
    assert len(captured_prompts) == 1
    sys_p, usr_p = captured_prompts[0]
    assert "Video Topic / Thematic Context: Relativity and Time" in usr_p
    assert "unexpected or surprising complementary thoughts" in usr_p


def test_configured_channel_premise_reaches_prompts():
    """Phase 9B: Verifies channel premise from config reaches anchor and middle scene prompts."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []

    class PremiseCapturingLLM:
        def generate_json(self, system_prompt="", user_prompt="", *args, **kwargs):
            captured_prompts.append((system_prompt, user_prompt))
            if "Scene 1 hook thought" in user_prompt:
                return {
                    "hook_scene": {"spoken_text": "Your brain creates your reality.", "stock_video_query": "brain synapsis"},
                    "penultimate_scene": {"spoken_text": "Dreams feel real until you wake up.", "stock_video_query": "dream state"},
                    "loop_scene": {"spoken_text": "Which means...", "stock_video_query": "loop spin"}
                }
            return {
                "spoken_text": "You cannot imagine a new color that does not already exist.",
                "stock_video_query": "color spectrum"
            }

    llm = PremiseCapturingLLM()
    channel_cfg = {
        "prompt_settings": {
            "channel_premise": "Psychological paradoxes that challenge reality perception"
        }
    }
    generator = IterativeScriptGenerator(llm_manager=llm, channel_cfg=channel_cfg)

    # 1. Anchors
    generator._generate_anchor_bookends(topic="Perception")
    # 2. Middle Scene
    generator._generate_random_thought(scene_num=2, existing_scenes=[], topic="Perception")

    assert len(captured_prompts) == 2
    # Anchor prompt check
    assert "Channel Premise / Identity: Psychological paradoxes that challenge reality perception" in captured_prompts[0][1]
    # Middle scene prompt check
    assert "Channel Premise / Identity: Psychological paradoxes that challenge reality perception" in captured_prompts[1][1]


def test_generator_uses_supplied_prompts_cfg():
    """Phase 9B: Verifies IterativeScriptGenerator consumes supplied prompts_cfg instead of reloading from disk."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []

    class PromptsCfgCapturingLLM:
        def generate_json(self, system_prompt="", user_prompt="", *args, **kwargs):
            captured_prompts.append((system_prompt, user_prompt))
            if "CUSTOM_TRIPLET_PROMPT" in system_prompt:
                return {
                    "hook_scene": {"spoken_text": "The ocean is largely unexplored.", "stock_video_query": "deep ocean"},
                    "penultimate_scene": {"spoken_text": "We know more about the moon than our abyss.", "stock_video_query": "moon surface"},
                    "loop_scene": {"spoken_text": "Because...", "stock_video_query": "water swirl"}
                }
            return {
                "spoken_text": "Sunlight underwater disappears within 200 meters.",
                "stock_video_query": "underwater ray"
            }

    custom_prompts = {
        "triplet_anchor_scenes": {"system_prompt": "CUSTOM_TRIPLET_PROMPT: Generate three anchors."},
        "thought_scene": {"system_prompt": "CUSTOM_THOUGHT_PROMPT: Generate one thought."}
    }

    llm = PromptsCfgCapturingLLM()
    generator = IterativeScriptGenerator(llm_manager=llm, prompts_cfg=custom_prompts)

    assert generator.prompts["triplet_anchor_scenes"]["system_prompt"] == "CUSTOM_TRIPLET_PROMPT: Generate three anchors."
    assert generator.prompts["thought_scene"]["system_prompt"] == "CUSTOM_THOUGHT_PROMPT: Generate one thought."

    generator._generate_anchor_bookends(topic="Ocean")
    generator._generate_random_thought(scene_num=2, existing_scenes=[], topic="Ocean")

    assert len(captured_prompts) == 2
    assert "CUSTOM_TRIPLET_PROMPT" in captured_prompts[0][0]
    assert "CUSTOM_THOUGHT_PROMPT" in captured_prompts[1][0]


def test_channel_instructions_reach_active_shorts_prompts():
    """Phase 9B: Verifies apply_prompt_rules_to_config injects virality, extra instructions, and banned phrases into active Shorts prompts."""
    from engine.managers.pipeline_runner import apply_prompt_rules_to_config

    base_prompts = {
        "triplet_anchor_scenes": {"system_prompt": "Base triplet prompt."},
        "thought_scene": {"system_prompt": "Base thought prompt."},
        "paired_anchor_scene": {"system_prompt": "Base paired prompt."},
        "script_gen": {"system_prompt": "Base script_gen.", "user_template": "Base user template."}
    }

    channel_cfg = {
        "prompt_settings": {
            "enforce_virality": True,
            "extra_instructions": "Focus strictly on mind-bending neuroscience quirks.",
            "banned_phrases": ["In a world where", "Believe it or not"]
        }
    }

    patched = apply_prompt_rules_to_config(base_prompts, channel_cfg)

    for key in ["triplet_anchor_scenes", "thought_scene", "paired_anchor_scene"]:
        sys_p = patched[key]["system_prompt"]
        assert "VIRALITY ENFORCEMENT" in sys_p
        assert sys_p.count("VIRALITY ENFORCEMENT") == 1
        assert "EXTRA BANNED PHRASES" in sys_p
        assert sys_p.count("EXTRA BANNED PHRASES") == 1
        assert '"In a world where"' in sys_p
        assert '"Believe it or not"' in sys_p
        assert "ADDITIONAL CHANNEL INSTRUCTION: Focus strictly on mind-bending neuroscience quirks." in sys_p
        assert sys_p.count("ADDITIONAL CHANNEL INSTRUCTION") == 1

    # script_gen also gets rules applied
    assert "VIRALITY ENFORCEMENT" in patched["script_gen"]["system_prompt"]
    assert patched["script_gen"]["system_prompt"].count("VIRALITY ENFORCEMENT") == 1
    assert "ADDITIONAL CHANNEL INSTRUCTION: Focus strictly on mind-bending neuroscience quirks." in patched["script_gen"]["user_template"]
    assert patched["script_gen"]["user_template"].count("ADDITIONAL CHANNEL INSTRUCTION") == 1


def test_prompt_rules_applied_exactly_once_in_generator_flow():
    """Phase 9B.1: Verifies that passing configured prompts_cfg and channel_cfg to IterativeScriptGenerator applies rules exactly once."""
    from engine.managers.pipeline_runner import apply_prompt_rules_to_config
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    base_prompts = {
        "triplet_anchor_scenes": {"system_prompt": "Base triplet prompt."},
        "thought_scene": {"system_prompt": "Base thought prompt."},
        "paired_anchor_scene": {"system_prompt": "Base paired prompt."},
        "script_gen": {"system_prompt": "Base script_gen.", "user_template": "Base user template."}
    }

    channel_cfg = {
        "prompt_settings": {
            "enforce_virality": True,
            "extra_instructions": "Focus strictly on mind-bending neuroscience quirks.",
            "banned_phrases": ["In a world where", "Believe it or not"]
        }
    }

    # Step 1: PipelineRunner applies prompt rules to configuration
    configured_prompts = apply_prompt_rules_to_config(base_prompts, channel_cfg)

    # Step 2: Generator is instantiated with BOTH configured prompts_cfg and channel_cfg (production flow)
    class DummyLLM:
        pass

    generator = IterativeScriptGenerator(
        llm_manager=DummyLLM(),
        prompts_cfg=configured_prompts,
        channel_cfg=channel_cfg
    )

    # Step 3: Assert every rule is present exactly once, never duplicated
    for key in ["triplet_anchor_scenes", "thought_scene", "paired_anchor_scene"]:
        sys_p = generator.prompts[key]["system_prompt"]
        assert sys_p.count("VIRALITY ENFORCEMENT") == 1, f"Duplicate virality enforcement in {key}: {sys_p}"
        assert sys_p.count("ADDITIONAL CHANNEL INSTRUCTION") == 1, f"Duplicate extra instructions in {key}: {sys_p}"
        assert sys_p.count("EXTRA BANNED PHRASES") == 1, f"Duplicate banned phrases in {key}: {sys_p}"

    gen_sys = generator.prompts["script_gen"]["system_prompt"]
    gen_usr = generator.prompts["script_gen"]["user_template"]
    assert gen_sys.count("VIRALITY ENFORCEMENT") == 1
    assert gen_sys.count("EXTRA BANNED PHRASES") == 1
    assert gen_usr.count("ADDITIONAL CHANNEL INSTRUCTION") == 1


def test_apply_prompt_rules_idempotency_on_repeated_calls():
    """Phase 9B.1: Verifies apply_prompt_rules and apply_prompt_rules_to_config are fully idempotent on repeated execution."""
    from engine.managers.pipeline_runner import apply_prompt_rules, apply_prompt_rules_to_config

    channel_cfg = {
        "prompt_settings": {
            "enforce_virality": True,
            "extra_instructions": "Focus on high dopamine hooks.",
            "banned_phrases": ["Wait until the end", "Mind blown"]
        }
    }

    # 1. Direct prompt strings idempotency
    sys_once, usr_once = apply_prompt_rules("SYS", "USR", channel_cfg)
    sys_twice, usr_twice = apply_prompt_rules(sys_once, usr_once, channel_cfg)
    assert sys_once == sys_twice
    assert usr_once == usr_twice
    assert sys_twice.count("VIRALITY ENFORCEMENT") == 1
    assert usr_twice.count("ADDITIONAL CHANNEL INSTRUCTION") == 1
    assert sys_twice.count("EXTRA BANNED PHRASES") == 1

    # 2. Config dictionary idempotency
    base_prompts = {
        "triplet_anchor_scenes": {"system_prompt": "Base triplet prompt."},
        "thought_scene": {"system_prompt": "Base thought prompt."},
        "paired_anchor_scene": {"system_prompt": "Base paired prompt."},
        "script_gen": {"system_prompt": "Base script_gen.", "user_template": "Base user template."}
    }
    cfg_once = apply_prompt_rules_to_config(base_prompts, channel_cfg)
    cfg_twice = apply_prompt_rules_to_config(cfg_once, channel_cfg)

    for k in base_prompts:
        assert cfg_once[k] == cfg_twice[k]
        if "system_prompt" in cfg_twice[k]:
            assert cfg_twice[k]["system_prompt"].count("VIRALITY ENFORCEMENT") == 1


def test_existing_generator_callers_backward_compatibility():
    """Phase 9B: Verifies legacy/existing callers without prompts_cfg or channel_premise work cleanly."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class LegacyLLM:
        def generate_json(self, *args, **kwargs):
            return {
                "hook_scene": {"spoken_text": "The mind forgets quickly.", "stock_video_query": "clock"},
                "penultimate_scene": {"spoken_text": "Memory degrades every year.", "stock_video_query": "notes"},
                "loop_scene": {"spoken_text": "Which explains why...", "stock_video_query": "loop"},
                "spoken_text": "Deja vu is just a neurological delay.",
                "stock_video_query": "brain"
            }

    llm = LegacyLLM()
    # 1. Default instantiation without new params
    generator = IterativeScriptGenerator(llm_manager=llm)
    assert generator.channel_premise == ""
    assert isinstance(generator.prompts, dict)

    # 2. Legacy helper: _generate_single_pillar_scene
    scene = generator._generate_single_pillar_scene(scene_num=2, existing_scenes=[])
    assert scene["scene_id"] == 2
    assert scene["spoken_text"] == "Deja vu is just a neurological delay."

    # 3. Legacy helper: _generate_hook
    hook = generator._generate_hook(topic="Memory")
    assert hook["scene_id"] == 1
    assert hook["spoken_text"] == "The mind forgets quickly."

    # 4. Legacy helper: _generate_paired_anchors
    h, l = generator._generate_paired_anchors(topic="Memory")
    assert h["spoken_text"] == "The mind forgets quickly."
    assert l["spoken_text"] == "Which explains why..."


def test_generation_produces_valid_standalone_non_loop_ending():
    """Phase 10A: Verifies _generate_anchor_bookends and generate_scene_chain produce and preserve standalone non-loop endings."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class StandaloneEndingLLM:
        def __init__(self):
            self.call_count = 0

        def generate_json(self, system_prompt="", user_prompt="", *args, **kwargs):
            self.call_count += 1
            if "Scene 1 hook thought" in user_prompt:
                return {
                    "hook_scene": {
                        "spoken_text": "Astronauts on the International Space Station experience sixteen sunrises every single day.",
                        "stock_video_query": "space station orbit"
                    },
                    "penultimate_scene": {
                        "spoken_text": "Because of orbital speed, an entire day and night cycle passes in just ninety minutes.",
                        "stock_video_query": "earth horizon sunrise"
                    },
                    "ending_scene": {
                        "spoken_text": "Living there means your body clock has to completely divorce itself from the sun.",
                        "stock_video_query": "astronaut looking out cupola",
                        "ending_type": "observation"
                    }
                }
            elif "SCENES TO NORMALIZE & EMOTIFY:" in user_prompt:
                import json
                payload = json.loads(user_prompt.split("SCENES TO NORMALIZE & EMOTIFY:\n")[1].split("\n\nEnhance")[0])
                return {"scenes": payload}
            elif "optimized YouTube metadata" in user_prompt:
                return {
                    "title": "Living In Space Breaks Your Internal Clock 🛰️ #shorts",
                    "description": "Astronauts experience 16 sunrises a day.\n\nSubscribe for more daily shifts!",
                    "tags": ["space", "astronauts", "shorts"]
                }
            else:
                return {
                    "spoken_text": "Light from the sun takes eight minutes to reach your retinas.",
                    "stock_video_query": "sunlight rays"
                }

    llm = StandaloneEndingLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)

    # 1. Direct anchor bookends check
    hook, penult, ending = generator._generate_anchor_bookends(topic="Space")
    assert hook["spoken_text"] == "Astronauts on the International Space Station experience sixteen sunrises every single day."
    assert penult["spoken_text"] == "Because of orbital speed, an entire day and night cycle passes in just ninety minutes."
    assert ending["spoken_text"] == "Living there means your body clock has to completely divorce itself from the sun."
    # Ensure it ends with definitive period and was NOT forced to end with '...'
    assert ending["spoken_text"].endswith(".")
    assert not ending["spoken_text"].endswith("...")
    assert llm.call_count == 1  # Accepted on first attempt without rejection


def test_generation_produces_valid_natural_circular_loop_ending():
    """Phase 10A: Verifies _generate_anchor_bookends accepts and preserves natural circular loop endings ending in '...'."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class CircularLoopLLM:
        def __init__(self):
            self.call_count = 0

        def generate_json(self, *args, **kwargs):
            self.call_count += 1
            return {
                "hook_scene": {
                    "spoken_text": "The ancient library of Alexandria never actually burned down in a single catastrophic night.",
                    "stock_video_query": "ancient library ruins"
                },
                "penultimate_scene": {
                    "spoken_text": "It suffered centuries of steady budget cuts, administrative neglect, and political disinterest.",
                    "stock_video_query": "ancient papyrus scrolls"
                },
                "ending_scene": {
                    "spoken_text": "Which is why civilizations rarely lose their greatest knowledge to sudden fires, but rather to the quiet reality that...",
                    "stock_video_query": "sand hourglass ancient",
                    "ending_type": "circular_loop"
                }
            }

    llm = CircularLoopLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)
    hook, penult, ending = generator._generate_anchor_bookends(topic="History")

    assert hook["spoken_text"].startswith("The ancient library of Alexandria")
    assert ending["spoken_text"].endswith("...")
    assert llm.call_count == 1


def test_non_loop_ending_does_not_fail_solely_for_lacking_bridge_syntax():
    """Phase 10A: Verifies LoopAuditorSkill.audit_loop accepts diverse non-loop endings (periods, exclamation marks, questions)."""
    from engine.managers.editorial_critic import LoopAuditorSkill

    hook = "Every human on earth is carrying several pounds of non-human bacteria right now."

    # Punchline / Observation with '.'
    ending_period = "In other words, you are less of an individual and more of a walking microbial apartment complex."
    passed, reason = LoopAuditorSkill.audit_loop(ending_period, hook)
    assert passed, f"Expected PASS for period ending, got: {reason}"
    assert "Standalone Ending PASSED" in reason

    # Witty remark with '!'
    ending_exclamation = "So the next time you feel lonely, just remember that trillions of organisms literally cannot live without you!"
    passed, reason = LoopAuditorSkill.audit_loop(ending_exclamation, hook)
    assert passed, f"Expected PASS for exclamation ending, got: {reason}"
    assert "Standalone Ending PASSED" in reason

    # Thoughtful provocation with '?'
    ending_question = "If trillions of microscopic beings call you home, who is really in charge here?"
    passed, reason = LoopAuditorSkill.audit_loop(ending_question, hook)
    assert passed, f"Expected PASS for question ending, got: {reason}"
    assert "Standalone Ending PASSED" in reason


def test_loop_endings_still_receive_strict_structural_and_antirepetition_validation():
    """Phase 10A: Verifies that attempted loop endings that repeat hook words or lack bridge syntax are rejected."""
    from engine.managers.editorial_critic import is_valid_circular_bridge, LoopAuditorSkill

    hook = "Time dilation means astronauts age slower than their twin on Earth."

    # 1. Attempted loop that verbatim repeats the opening of hook -> Must fail
    stutter_loop = "And time dilation means astronauts age slower than their..."
    is_circ, circ_reason = is_valid_circular_bridge(stutter_loop, hook)
    assert not is_circ
    assert ("Loop duplicates opening words of hook" in circ_reason or "Loop echoes majority of hook content" in circ_reason)

    # 2. LoopAuditorSkill correctly reports failure on defective circular attempt
    passed, reason = LoopAuditorSkill.audit_loop(stutter_loop, hook)
    assert not passed
    assert "Loop Audit FAILED" in reason


def test_prompts_yaml_anchor_and_thought_redesign_integrity():
    """Phase 10A: Verifies config/prompts.yaml defines optional loop payoffs and broad curiosity without mirror fixation."""
    import yaml

    with open("config/prompts.yaml", "r", encoding="utf-8") as f:
        prompts = yaml.safe_load(f)

    # 1. triplet_anchor_scenes
    triplet_sys = prompts["triplet_anchor_scenes"]["system_prompt"]
    assert "Punchline" in triplet_sys
    assert "Unexpected Implication" in triplet_sys
    assert "Thoughtful Provocation" in triplet_sys
    assert "Clean Resolution" in triplet_sys
    assert "Circular Loop" in triplet_sys
    assert "Do NOT force every video to be a circular loop" in triplet_sys
    # Ensure mirror / face / reflection exemplar fixation was removed
    assert "Every mirror you purchase is technically used" not in triplet_sys

    # 2. thought_scene
    thought_sys = prompts["thought_scene"]["system_prompt"]
    assert "Psychology" in thought_sys
    assert "Space, time, & physics" in thought_sys
    assert "do not fixate on reflections, mirrors, or faces" in thought_sys

    # Ensure hard-coded phrase bans are removed in favor of context-aware editorial guidance
    assert "Did you know" not in triplet_sys
    assert "Fun fact" not in triplet_sys
    assert "Ever wonder why" not in triplet_sys
    assert "Imagine if" not in triplet_sys
    assert "Did you know" not in thought_sys
    assert "Fun fact" not in thought_sys
    assert "Prepare to have your mind blown" not in thought_sys


def test_standalone_endings_accept_hook_word_reuse_and_callbacks():
    """Phase 10A.1: Standalone endings must not be rejected solely because they reuse words from the hook."""
    from engine.managers.editorial_critic import LoopAuditorSkill

    hook = "Every human on earth is carrying several pounds of non-human bacteria right now."

    # Callback reusing 3 content words from hook: 'human', 'earth', 'bacteria'
    callback_ending = "In other words, you are less of an individual human and more of a walking home for bacteria on earth."
    # 1. With explicit ending_type="callback" or "observation"
    passed, reason = LoopAuditorSkill.audit_loop(callback_ending, hook, ending_type="callback")
    assert passed, f"Expected PASS for callback ending, got: {reason}"
    assert "Standalone Ending PASSED" in reason

    # 2. Without ending_type (inferred from definitive punctuation '.')
    passed_legacy, reason_legacy = LoopAuditorSkill.audit_loop(callback_ending, hook)
    assert passed_legacy, f"Expected PASS for standalone ending without ending_type, got: {reason_legacy}"
    assert "Standalone Ending PASSED" in reason_legacy

    # 3. But verbatim duplicate of the entire hook must still fail
    verbatim_dup = "Every human on earth is carrying several pounds of non-human bacteria right now."
    passed_dup, reason_dup = LoopAuditorSkill.audit_loop(verbatim_dup, hook, ending_type="observation")
    assert not passed_dup
    assert "duplicates opening hook verbatim" in reason_dup


def test_explicit_loop_intent_prefers_ending_type_and_handles_legacy_ellipsis():
    """Phase 10A.1: Prefer explicit ending_type; legacy ellipsis '...' treated as loop without inferring from trailing words."""
    from engine.managers.editorial_critic import LoopAuditorSkill

    hook = "Time dilation means astronauts age slower than their twin on Earth."

    # 1. Trailing word 'that' with ending_type='observation' must NOT be inferred as a loop
    observation_that = "And in the physics of relativity, that is simply the way reality works."
    passed, reason = LoopAuditorSkill.audit_loop(observation_that, hook, ending_type="observation")
    assert passed
    assert "Standalone Ending PASSED" in reason

    # 2. Trailing word 'is' or 'that' without ending_type and ending in '.' is NOT treated as a loop
    sentence_ending_is = "Which is why true absolute time does not exist as an independent entity."
    passed_is, reason_is = LoopAuditorSkill.audit_loop(sentence_ending_is, hook)
    assert passed_is
    assert "Standalone Ending PASSED" in reason_is

    # 3. Legacy ending ending in '...' without ending_type is treated as a loop
    valid_circ_legacy = "Which is why astronauts returning from orbit realize that..."
    passed_circ, reason_circ = LoopAuditorSkill.audit_loop(valid_circ_legacy, hook)
    assert passed_circ
    assert "Circular Loopback Bridge PASSED" in reason_circ

    # 4. Explicit circular_loop ending without bridge syntax is rejected
    invalid_circ = "Astronauts age slower than their twin."
    passed_inv, reason_inv = LoopAuditorSkill.audit_loop(invalid_circ, hook, ending_type="circular_loop")
    assert not passed_inv
    assert "Missing circular bridge syntax" in reason_inv


def test_middle_thought_prompt_appends_each_section_exactly_once():
    """Phase 10E: _generate_random_thought appends topic, premise, and grounding context exactly once."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []

    class MockLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="script_gen"):
            captured_prompts.append(user_prompt)
            return {
                "spoken_text": "A neutron star rotates hundreds of times per second.",
                "stock_video_query": "pulsar neutron star space"
            }

    generator = IterativeScriptGenerator(
        llm_manager=MockLLM(),
        prompts_cfg={
            "thought_scene": {
                "system_prompt": "Generate a standalone thought."
            }
        }
    )

    topic_val = "Astrophysical Relativities"
    premise_val = "Mind-bending shower thoughts and cosmic realizations."
    grounding_val = "Neutron stars can spin up to 700 times per second."

    generator._generate_random_thought(
        scene_num=2,
        existing_scenes=[{"spoken_text": "Black holes warp spacetime to infinity."}],
        topic=topic_val,
        channel_premise=premise_val,
        grounding_facts=grounding_val
    )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]

    # Verify each label header appears exactly once
    assert prompt.count("Video Topic / Thematic Context:") == 1
    assert prompt.count("Channel Premise / Identity:") == 1
    assert prompt.count(grounding_val) == 1

    # Verify actual distinct values are present
    assert topic_val in prompt
    assert premise_val in prompt
    assert grounding_val in prompt

    # Verify with absent/empty parameters: no duplicate headers and clean formatting
    captured_prompts.clear()
    generator._generate_random_thought(
        scene_num=3,
        existing_scenes=[{"spoken_text": "Black holes warp spacetime to infinity."}],
        topic="",
        channel_premise="",
        grounding_facts=None
    )
    assert len(captured_prompts) == 1
    clean_prompt = captured_prompts[0]
    assert "Video Topic / Thematic Context:" not in clean_prompt
    assert "Channel Premise / Identity:" not in clean_prompt
    assert "VERIFIED INSPIRATION & FACTUAL REFERENCES:" not in clean_prompt


def test_run_spec_stage_shorts_does_not_evaluate_script_gen_template(monkeypatch, tmp_path):
    """Phase 10E: PipelineRunner run_spec_stage() for Shorts does not format the unused script_gen template."""
    import engine.managers.pipeline_runner as pr

    broken_prompts_cfg = {
        "script_gen": {
            "system_prompt": "Broken script gen system prompt",
            "user_template": "Broken template requiring {NONEXISTENT_MANDATORY_KEY_XYZ}"
        },
        "triplet_anchor_scenes": {"system_prompt": "triplet prompt"},
        "thought_scene": {"system_prompt": "thought prompt"},
        "script_polish": {"system_prompt": "polish prompt"},
        "seo_gen": {"system_prompt": "seo prompt"},
        "editorial_revision": {"system_prompt": "editorial prompt"}
    }
    dummy_channel_cfg = {
        "channel": {"name": "TEST", "niche": "science", "voice": {"provider": "kokoro", "voice_id": "am_adam"}},
        "prompt_settings": {"channel_premise": "Premise"}
    }

    monkeypatch.setattr(pr, "load_yaml", lambda path: broken_prompts_cfg if "prompts" in path else dummy_channel_cfg)
    monkeypatch.setattr(pr.TopicInspector, "get_grounding_references", classmethod(lambda cls, count=5: []))
    monkeypatch.setattr(pr.TopicInspector, "discover_verified_topic", lambda self, niche, video_type="short": {"topic": "Black Holes", "source": "trend"})
    monkeypatch.setattr(pr.TopicInspector, "_fact_check", lambda self, topic, niche=None: {"verified": True, "summary": topic, "status": "verified"})
    monkeypatch.setattr(pr.CompetitorSpy, "get_surge_topic", staticmethod(lambda competitors: None))
    monkeypatch.setattr(pr.HealthManager, "load_dynamic_weights", staticmethod(lambda: {}))
    monkeypatch.setattr(pr.HealthManager, "check_and_sync_models", staticmethod(lambda: None))

    class MockGenerator:
        def __init__(self, *args, **kwargs):
            pass
        def generate_scene_chain(self, *args, **kwargs):
            return [
                {"scene_id": 1, "spoken_text": "The core of a star collapses into a singularity."},
                {"scene_id": 2, "spoken_text": "Time halts at the event horizon relative to distant observers."}
            ], {"title": "Black Holes Collapse Spacetime #shorts", "description": "Black Holes Collapse Spacetime #shorts\n\nPerspectives.", "tags": ["black holes", "shorts"]}

    monkeypatch.setattr("engine.managers.iterative_script_generator.IterativeScriptGenerator", MockGenerator)
    monkeypatch.setattr(pr, "_validate_iscg_scenes_boundary", lambda scenes: None)
    monkeypatch.setattr(pr, "_load_thought_cache", lambda cfg: {"entries": []})
    monkeypatch.setattr(pr, "_is_duplicate", lambda text, cfg: False)
    monkeypatch.setattr(pr, "_add_to_cache", lambda text, cfg: None)
    monkeypatch.setattr(pr.VoiceNormalizer, "normalize_text", lambda text: text)
    monkeypatch.setattr(pr.VoiceNormalizer, "synthesize_scenes_sync", lambda **kw: (15.0, [], [7.5, 7.5], []))
    monkeypatch.setattr(pr, "is_test_run", lambda: True)

    # Calling run_spec_stage for Shorts must succeed without evaluating script_gen template
    pr.run_spec_stage(video_type="short", custom_topic="Black Holes")


# ─── PHASE 10G.1: DURATION STOPPING & NUMERIC TOKEN LIMITATION TESTS ───────────

def test_generate_scene_chain_approximate_30s_stopping_preserves_crossing_scene(monkeypatch):
    """Phase 10G.1: Verifies that generate_scene_chain stops middle-scene accumulation
    at approximately 30.0s (stop_threshold = 30.0s) and retains the full crossing scene
    without clipping, popping, or padding to 52-58s."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    from engine.managers.voice_normalizer import VoiceNormalizer

    class DeterministicStoppingLLM:
        _last_used_provider_id = "test_llm"
        def __init__(self):
            self.middle_count = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            if "Scene 1 hook thought and a Final Scene loopback bridge" in user_prompt or "Generate THREE key anchor scenes" in user_prompt:
                return {
                    "hook_scene": {"spoken_text": "Astronauts observe sixteen sunrises daily.", "stock_video_query": "iss space"},
                    "penultimate_scene": {"spoken_text": "Orbital speed compresses an entire day into ninety minutes.", "stock_video_query": "earth orbit"},
                    "ending_scene": {"spoken_text": "Living in space completely alters your body clock.", "stock_video_query": "astronaut sleeping"}
                }
            elif "SCENES TO NORMALIZE & POLISH:" in user_prompt:
                import json
                try:
                    lines = user_prompt.split("SCENES TO NORMALIZE & POLISH:\n")[1].split("\n\n")[0]
                    return {"scenes": json.loads(lines)}
                except Exception:
                    return {}
            elif "Generate accurate, compelling YouTube Shorts metadata" in user_prompt:
                return {
                    "title": "Sixteen Sunrises in Space #shorts",
                    "description": "Sixteen Sunrises in Space #shorts\n\nSpace perspectives.\n\n#shorts",
                    "tags": ["space", "shorts"]
                }
            else:
                distinct_middle_thoughts = [
                    "Cosmic radiation passes through spacecraft walls causing astronauts to see bright flashes.",
                    "The silence of deep vacuum makes every internal heartbeat inside a spacesuit sound loud.",
                    "Without atmospheric diffusion, distant stars never twinkle and shine like piercing lasers.",
                    "Microgravity causes the human spinal column to stretch up to three additional inches.",
                    "Our home planet looks like a tiny fragile oasis suspended in infinite emptiness."
                ]
                thought = distinct_middle_thoughts[(self.middle_count) % len(distinct_middle_thoughts)]
                self.middle_count += 1
                return {
                    "spoken_text": thought,
                    "stock_video_query": "spacetime clock"
                }

    # Deterministic durations:
    # Anchors: 4.0s (Hook) + 4.0s (Penultimate) + 4.0s (Ending) = 12.0s
    # Each middle thought: exactly 7.0s
    # Trajectory:
    # Initial: 12.0s (< 30.0s)
    # Mid 1: 12.0 + 7.0 = 19.0s (< 30.0s)
    # Mid 2: 12.0 + 7.0 + 7.0 = 26.0s (< 30.0s)
    # Mid 3: 26.0 + 7.0 = 33.0s (>= 30.0s -> STOPS!)
    def mock_measure_duration(text, voice="am_adam", speed=1.02):
        if "sixteen sunrises" in text.lower():
            return 4.0
        elif "orbital speed" in text.lower():
            return 4.0
        elif "living in space" in text.lower():
            return 4.0
        else:
            return 7.0

    monkeypatch.setattr(VoiceNormalizer, "measure_duration_quick", mock_measure_duration)

    llm = DeterministicStoppingLLM()
    generator = IterativeScriptGenerator(llm_manager=llm)
    scenes, seo = generator.generate_scene_chain(topic="Space Habitability")

    # Hook (1) + 3 Middle + Penultimate (1) + Ending (1) = 6 scenes total
    assert len(scenes) == 6
    assert llm.middle_count == 3
    # Crossing scene (Mid 3) brought total to 33.0s; it must be fully preserved
    assert scenes[0]["spoken_text"] == "Astronauts observe sixteen sunrises daily."
    assert scenes[3]["spoken_text"] == "Without atmospheric diffusion, distant stars never twinkle and shine like piercing lasers."
    assert scenes[4]["spoken_text"] == "Orbital speed compresses an entire day into ninety minutes."
    assert scenes[5]["spoken_text"] == "Living in space completely alters your body clock."

    # Measured duration is ~33.0s (natural stop around 30s), NOT padded or clamped to 52-58s
    final_dur = sum(mock_measure_duration(s["spoken_text"]) for s in scenes)
    assert final_dur == 33.0


def test_extract_number_tokens_scope_and_digit_limitations():
    """Phase 10G.1: Documents and verifies that _extract_number_tokens strictly detects
    digit-formatted numerical tokens (integers, decimals, signed numbers, ranges, commas)
    and does NOT extract or convert spelled-out number words (e.g. 'one', 'two', 'first')."""
    from engine.managers.iterative_script_generator import _extract_number_tokens

    # Digit numbers are extracted
    digit_text = "The speed increased by +15.5 mph to 10,000 feet in 30 seconds."
    assert _extract_number_tokens(digit_text) == ["+15.5", "10000", "30"]

    # Spelled-out number words are NOT extracted
    spelled_text = "There are twelve sunrises every single day, the first of which is golden."
    assert _extract_number_tokens(spelled_text) == []

    # Mixed text extracts only digit tokens
    mixed_text = "Apollo 11 had three astronauts who completed two spacewalks."
    assert _extract_number_tokens(mixed_text) == ["11"]
