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
            return {
                "spoken_text": f"Astonishing perspective shift number {self.call_count} that breaks your thinking.",
                "stock_video_query": "pottery wheel clay shaping satisfying"
            }

    mock_llm = MockChainLLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(
        topic="Mind Bending Thoughts",
        max_duration=32.0
    )

    # High-retention circular short: 4 to 7 scenes total
    assert 4 <= len(scenes) <= 7
    # Scene 1 is Hook
    assert scenes[0]["scene_id"] == 1
    assert "face" in scenes[0]["spoken_text"].lower()
    # Scene 2 is a genuine thought, NOT a category title readout
    assert scenes[1]["scene_id"] == 2
    assert "shower thoughts that" not in scenes[1]["spoken_text"].lower()
    # Final Scene is Loop Outro Anchor
    assert scenes[-1]["spoken_text"].endswith("...") or scenes[-1]["spoken_text"].endswith((".", "!"))
    # Total duration strictly <= 32.0s
    total_dur = sum(generator._calc_duration(s["spoken_text"]) for s in scenes)
    assert total_dur <= 32.0
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
            elif "SCENES TO NORMALIZE & EMOTIFY:" in user_prompt:
                import json
                try:
                    lines = user_prompt.split("SCENES TO NORMALIZE & EMOTIFY:\n")[1].split("\n\n")[0]
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
                return {
                    "spoken_text": f"Mind-bending perspective number {self.call_count} that resets your daily perception.",
                    "stock_video_query": "pottery wheel clay shaping satisfying"
                }

    mock_llm = MockV4LLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(max_duration=32.0)

    # 1. Total duration must be strictly <= 32.0s
    total_dur = sum(generator._calc_duration(s["spoken_text"]) for s in scenes)
    assert total_dur <= 32.0, f"Total duration {total_dur}s exceeded max 32.0s ceiling!"

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




