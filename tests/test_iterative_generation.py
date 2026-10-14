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
    """Loop outro architect must choose Mode B for questions and Mode A for declarative hooks."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator, MODE_B_WITTY_CLOSERS

    class DummyLLM:
        _last_used_provider_id = "test_prov"
        def generate_json(self, *args, **kwargs):
            return {
                "spoken_text": "Because everything in the universe is connected to...",
                "stock_video_query": "kinetic sand"
            }

    generator = IterativeScriptGenerator(llm_manager=DummyLLM())

    # Question hook -> Must select Mode B (witty closer)
    question_hook = "A single chili pepper can fire up your taste buds for 10 minutes—ever wondered why?"
    outro_q = generator._generate_loop_outro(
        hook_text=question_hook,
        scene_num=11,
        existing_scenes=[],
        used_queries=[]
    )
    assert outro_q["spoken_text"] in MODE_B_WITTY_CLOSERS

    # Declarative hook -> Attempts Mode A (loop ending with ...)
    declarative_hook = "The only part of your reflection you can lick is your tongue."
    outro_d = generator._generate_loop_outro(
        hook_text=declarative_hook,
        scene_num=11,
        existing_scenes=[],
        used_queries=[]
    )
    assert outro_d["spoken_text"].endswith("...")


def test_iterative_generator_chain_full_flow():
    """generate_scene_chain constructs an 11+ scene script rotating through pillars."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator, PILLARS

    class MockChainLLM:
        _last_used_provider_id = "test_model"
        def __init__(self):
            self.call_count = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.call_count += 1
            if "Scene 1:" in user_prompt:
                return {
                    "spoken_text": "The only part of your reflection you can lick is your tongue.",
                    "stock_video_query": "soap carving cubes ASMR"
                }
            elif "ASSIGNED KNOWLEDGE DOMAIN:" in user_prompt:
                # Return distinct thoughts
                return {
                    "spoken_text": f"Astonishing perspective shift number {self.call_count} that breaks your thinking.",
                    "stock_video_query": "pottery wheel clay shaping satisfying"
                }
            elif "seamless circular outro" in user_prompt:
                return {
                    "spoken_text": "Which proves that when you look into glass...",
                    "stock_video_query": "sand pendulum harmonograph geometric"
                }
            return {
                "spoken_text": "Valid thought text that meets all standards.",
                "stock_video_query": "kinetic sand"
            }

    mock_llm = MockChainLLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(
        topic="Mind Bending Thoughts",
        target_duration=55,
        target_words_min=140,
        target_words_max=175
    )

    assert len(scenes) >= 10
    # Scene 1 is Hook
    assert scenes[0]["scene_id"] == 1
    # Scene 2 is Premise Anchor
    assert scenes[1]["scene_id"] == 2
    # SEO title is umbrella
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


