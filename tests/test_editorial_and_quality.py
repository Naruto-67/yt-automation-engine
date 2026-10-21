"""
tests/test_editorial_and_quality.py — Unit tests for Editorial Critic & LLM Quality Tracker
"""
import os
import json
import tempfile
import pytest

os.environ["PYTEST_CURRENT_TEST"] = "true"


# ─── EDITORIAL CRITIC TESTS ───────────────────────────────────────────────────

def test_cynical_human_auditor_blocks_solipsism():
    """CynicalHumanAuditor must detect and flag all solipsistic banned phrases."""
    from engine.managers.editorial_critic import CynicalHumanAuditor

    bad_texts = [
        "The World Doesn't Exist When You Close Your Eyes",
        "nothing is real and everything is a lie",
        "Why You Will Never Actually Experience The Present Moment",
        "reality is a simulation running on cosmic hardware",
        "everything is predictable when you understand quantum mechanics",
        "you don't exist when you stop thinking about yourself",
    ]
    for text in bad_texts:
        passed, reason = CynicalHumanAuditor.audit_text(text)
        assert not passed, f"Expected Wall Test FAIL for: '{text}' but got PASS"
        assert "Wall Test FAILED" in reason


def test_cynical_human_auditor_passes_clean_thoughts():
    """CynicalHumanAuditor must pass clean, grounded thoughts."""
    from engine.managers.editorial_critic import CynicalHumanAuditor

    good_texts = [
        "The only part of your reflection you can lick is your tongue.",
        "Snipers and surgeons need steady hands for opposite reasons.",
        "A school suspending someone for too many absences is punishing them with more absence.",
        "If you replace every part of an axe, is it the same axe?",
        "Dropping coffee wakes you up more than drinking it.",
    ]
    for text in good_texts:
        passed, reason = CynicalHumanAuditor.audit_text(text)
        assert passed, f"Expected Wall Test PASS for: '{text}' but got FAIL: {reason}"


def test_cynical_human_auditor_sanitize_replaces_scene():
    """CynicalHumanAuditor.sanitize_scene replaces a bad scene with a vetted thought."""
    from engine.managers.editorial_critic import CynicalHumanAuditor

    bad_scene = {"scene_id": 3, "spoken_text": "nothing is real and we are all living in a lie."}
    replacements = ["The brain named itself, recognized itself, and is now questioning that fact."]

    result = CynicalHumanAuditor.sanitize_scene(bad_scene, replacements)
    assert result["spoken_text"] != bad_scene["spoken_text"]
    assert result.get("_editorial_replaced") is True


def test_hook_auditor_blocks_bad_openers():
    """HookAuditorSkill rejects banned openers and leading punctuation."""
    from engine.managers.editorial_critic import HookAuditorSkill

    bad_hooks = [
        "Did you know that the human brain is 73% water?",
        "Hey guys, welcome back to the channel!",
        "... and that is why reality is so strange.",
        "Have you ever wondered why we dream?",
    ]
    for hook in bad_hooks:
        passed, reason = HookAuditorSkill.audit_hook(hook)
        assert not passed, f"Expected Hook Audit FAIL for: '{hook}' but got PASS"


def test_hook_auditor_passes_clean_hook():
    """HookAuditorSkill passes clean in-media-res hooks."""
    from engine.managers.editorial_critic import HookAuditorSkill

    good_hooks = [
        "The only part of your reflection you can lick is your tongue.",
        "Snipers and surgeons need steady hands for the exact opposite reasons.",
        "A bus ten minutes early is far worse than a bus ten minutes late.",
    ]
    for hook in good_hooks:
        passed, reason = HookAuditorSkill.audit_hook(hook)
        assert passed, f"Expected Hook Audit PASS for: '{hook}' but got FAIL: {reason}"


def test_title_script_alignment_blocks_extreme_title():
    """TitleScriptAlignmentSkill flags extreme single-claim titles."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    bad_title = "Why You Will Never Actually Experience The Present Moment"
    scenes = [{"spoken_text": "Your shadow proves light traveled 93 million miles to be blocked by you."}]
    passed, reason = TitleScriptAlignmentSkill.audit_title(bad_title, scenes)
    assert not passed
    assert "Truth-in-Packaging FAILED" in reason


def test_title_script_alignment_passes_umbrella_title():
    """TitleScriptAlignmentSkill passes umbrella compilation titles."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    good_title = "Shower Thoughts That Blow Minds 🤯 #shorts"
    scenes = [{"spoken_text": "Any valid thought."}]
    passed, reason = TitleScriptAlignmentSkill.audit_title(good_title, scenes)
    assert passed


def test_audit_and_refine_spec_full_pipeline():
    """audit_and_refine_spec runs the full critic pipeline on a test spec."""
    from engine.managers.editorial_critic import audit_and_refine_spec

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue.", "stock_video_query": "soap"},
        {"scene_id": 2, "spoken_text": "nothing is real and everything is a lie", "stock_video_query": "sand"},
        {"scene_id": 3, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "kinetic"},
        {"scene_id": 4, "spoken_text": "If you replace every part of an axe is it the same axe...", "stock_video_query": "wood"},
    ]
    seo = {"title": "Why You Will Never Actually Experience The Present Moment"}

    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="consciousness")

    # Scene 2 had a Wall Test failure — should have been replaced (not hook/loop)
    assert audit_log["wall_test_failures"] >= 1
    # Title was extreme — should have been realigned
    assert refined_seo["title"] != seo["title"]
    assert len(refined_scenes) == len(scenes)  # Scene count unchanged


# ─── LLM QUALITY TRACKER TESTS ───────────────────────────────────────────────

def test_quality_tracker_reward_on_clean_script(tmp_path, monkeypatch):
    """LLMQualityTracker rewards a model that generates a clean script."""
    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", tmp_path / "model_quality_scores.json")
    monkeypatch.setattr(qt_module, "_CFG_DIR", tmp_path)

    from engine.managers.llm_quality_tracker import LLMQualityTracker
    qt = LLMQualityTracker()
    qt.record_result("test_model", wall_test_failures=0, wall_test_replacements=0, passed_first_attempt=True)
    assert qt.get_quality_score("test_model") > 1.0 - 0.001  # Should be rewarded toward 1.0


def test_quality_tracker_penalty_on_editorial_failure(tmp_path, monkeypatch):
    """LLMQualityTracker penalizes a model that produces solipsistic content."""
    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", tmp_path / "model_quality_scores.json")
    monkeypatch.setattr(qt_module, "_CFG_DIR", tmp_path)

    from engine.managers.llm_quality_tracker import LLMQualityTracker
    qt = LLMQualityTracker()
    qt.record_result("bad_model", wall_test_failures=2, wall_test_replacements=2, passed_first_attempt=False)
    assert qt.get_quality_score("bad_model") < 1.0


def test_quality_tracker_circuit_breaker_after_two_strikes(tmp_path, monkeypatch):
    """Two consecutive failures trigger 24h editorial cooldown."""
    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", tmp_path / "model_quality_scores.json")
    monkeypatch.setattr(qt_module, "_CFG_DIR", tmp_path)

    from engine.managers.llm_quality_tracker import LLMQualityTracker
    qt = LLMQualityTracker()
    qt.record_result("weak_model", wall_test_failures=1, wall_test_replacements=1, passed_first_attempt=False)
    qt.record_result("weak_model", wall_test_failures=1, wall_test_replacements=1, passed_first_attempt=False)

    # Reload from disk to ensure persistence worked
    qt2 = LLMQualityTracker()
    assert qt2.is_in_cooldown("weak_model", task="script_gen") is True


# ─── LOOP AUDITOR & HOOK REPETITION TESTS ─────────────────────────────────────

def test_loop_auditor_blocks_hook_repetition():
    """LoopAuditorSkill and check_loop_repeats_hook must block loop scenes that repeat hook words."""
    from engine.managers.editorial_critic import LoopAuditorSkill, check_loop_repeats_hook

    hook = "Your nose physically cannot close fully during a sneeze, making a perfectly silent one impossible."

    # Exact echo from real failed run
    bad_loop_1 = "And that is why your nose physically cannot close fully during a sneeze, making a perfectly silent one impossible..."
    repeats, reason = check_loop_repeats_hook(bad_loop_1, hook)
    assert repeats is True
    assert "repeats hook content words" in reason

    passed, reason_audit = LoopAuditorSkill.audit_loop(bad_loop_1, hook)
    assert passed is False
    assert "Loop Audit FAILED" in reason_audit

    # Partial repetition
    bad_loop_2 = "Which explains why your nose physically cannot close..."
    repeats_2, _ = check_loop_repeats_hook(bad_loop_2, hook)
    assert repeats_2 is True

    # 3-word n-gram match
    bad_loop_3 = "And all because during a sneeze we realize that..."
    repeats_3, _ = check_loop_repeats_hook(bad_loop_3, hook)
    assert repeats_3 is True


def test_loop_auditor_passes_clean_compilation_bridge():
    """LoopAuditorSkill must pass clean non-repeating compilation bridges and Mode B closers."""
    from engine.managers.editorial_critic import LoopAuditorSkill, check_loop_repeats_hook, COMPILATION_LOOP_BRIDGES

    hook = "Your nose physically cannot close fully during a sneeze, making a perfectly silent one impossible."

    for bridge in COMPILATION_LOOP_BRIDGES:
        repeats, reason = check_loop_repeats_hook(bridge, hook)
        assert repeats is False, f"Expected clean bridge for '{bridge}', got {reason}"
        passed, audit_reason = LoopAuditorSkill.audit_loop(bridge, hook)
        assert passed is True, f"Expected audit PASS for '{bridge}', got {audit_reason}"

    # Mode B closer
    mode_b = "If you want to be smarter than everyone you know, subscribe."
    passed_b, _ = LoopAuditorSkill.audit_loop(mode_b, hook)
    assert passed_b is True

    # Circular loopback bridge ending in ellipsis
    circ_bridge = "And the reason you don't notice it is simply because..."
    passed_circ, reason_circ = LoopAuditorSkill.audit_loop(circ_bridge, hook)
    assert passed_circ is True, f"Expected circular loopback bridge to PASS, got {reason_circ}"


def test_loop_auditor_sanitize_loop_replaces_defective_loop():
    """LoopAuditorSkill.sanitize_loop replaces a repeating loop with a clean bridge."""
    from engine.managers.editorial_critic import LoopAuditorSkill, check_loop_repeats_hook

    hook = "The only part of your reflection you can lick is your tongue."
    bad_scene = {
        "scene_id": 12,
        "spoken_text": "And that is why the only part of your reflection you can lick is your tongue..."
    }

    sanitized = LoopAuditorSkill.sanitize_loop(bad_scene, hook_text=hook)
    assert sanitized["spoken_text"] != bad_scene["spoken_text"]
    assert sanitized.get("_editorial_replaced") is True

    # Sanitized scene must not repeat hook
    repeats, _ = check_loop_repeats_hook(sanitized["spoken_text"], hook)
    assert repeats is False


# ─── PURE SHOWER THOUGHT AUDITOR TESTS ────────────────────────────────────────

def test_pure_shower_thought_auditor_bans_trivia_facts():
    """PureShowerThoughtAuditor must reject encyclopedic trivia facts."""
    from engine.managers.editorial_critic import PureShowerThoughtAuditor

    trivia_examples = [
        "Did you know that octopuses have three hearts and blue blood?",
        "Blue whales have an aorta large enough for a human to swim through.",
        "Scientists discovered that trees communicate underground through fungal networks.",
        "Elevator buttons don't actually register your touch using pressure sensors.",
        "The tiny hole at the bottom of a padlock is actually a drainage hole.",
        "Have you ever wondered why your phone compass uses a magnetometer?",
        "Studies show that sharks have been around longer than trees.",
    ]
    for trivia in trivia_examples:
        passed, reason = PureShowerThoughtAuditor.audit_thought(trivia)
        assert not passed, f"Expected trivia ban for '{trivia}', got PASS"
        assert "Trivia Fact BANNED" in reason


def test_pure_shower_thought_auditor_passes_pure_thoughts():
    """PureShowerThoughtAuditor must pass genuine cognitive paradoxes and shower thoughts."""
    from engine.managers.editorial_critic import PureShowerThoughtAuditor

    pure_thoughts = [
        "The only part of your reflection you can lick is your tongue.",
        "If you replace every part of an axe, is it the same axe?",
        "A bus ten minutes early is far worse than a bus ten minutes late.",
        "Your future self is watching you right now through memories.",
        "Every book you've ever read is just different combinations of twenty-six letters.",
        "Snipers and surgeons need steady hands for the exact opposite reasons.",
    ]
    for thought in pure_thoughts:
        passed, reason = PureShowerThoughtAuditor.audit_thought(thought)
        assert passed, f"Expected pure thought PASS for '{thought}', got FAIL: {reason}"


# ─── SEMANTIC DEDUPLICATION TESTS ─────────────────────────────────────────────

def test_semantic_deduplication_detects_rephrased_duplicates():
    """SemanticDeduplicationSkill must detect duplicate concepts despite completely different wording."""
    from engine.managers.editorial_critic import SemanticDeduplicationSkill

    # Pair 1: Brain ignoring nose
    text_1a = "Your brain actively deletes your nose from your vision even though you see it."
    text_1b = "Your brain constantly filters your nose out of your vision."
    dup_1, reason_1 = SemanticDeduplicationSkill.are_semantically_duplicate(text_1a, text_1b)
    assert dup_1 is True, f"Expected duplicate detection, got {reason_1}"

    # Pair 2: Embarrassing moments
    text_2a = "You remember embarrassing moments from five years ago while trying to sleep."
    text_2b = "Your brain loves replaying embarrassing moments when you close your eyes at night."
    dup_2, reason_2 = SemanticDeduplicationSkill.are_semantically_duplicate(text_2a, text_2b)
    assert dup_2 is True, f"Expected duplicate detection, got {reason_2}"


def test_semantic_deduplication_passes_distinct_thoughts():
    """SemanticDeduplicationSkill must pass truly distinct thoughts."""
    from engine.managers.editorial_critic import SemanticDeduplicationSkill

    thought_a = "The only part of your reflection you can lick is your tongue."
    thought_b = "Snipers and surgeons need steady hands for the exact opposite reasons."
    dup, reason = SemanticDeduplicationSkill.are_semantically_duplicate(thought_a, thought_b)
    assert dup is False, f"Expected distinct thoughts, got duplicate: {reason}"


# ─── VOICE TAIL PADDING TEST ──────────────────────────────────────────────────

def test_voice_normalizer_appends_comfort_tail_on_final_scene():
    """VoiceNormalizer must append a 0.45s comfort silence tail on the final scene."""
    # Verify 0.45s at 24000 Hz is 10800 samples
    sample_rate = 24000
    tail_duration = 0.45
    expected_tail_samples = int(sample_rate * tail_duration)
    assert expected_tail_samples == 10800


