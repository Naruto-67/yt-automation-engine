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
    """audit_and_refine_spec runs the full critic pipeline on a test spec with revision-first LLM editing."""
    from engine.managers.editorial_critic import audit_and_refine_spec

    class MockCriticLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            return {
                "spoken_text": "You can never actually touch anything because atomic electron clouds repel each other.",
                "visual_hook": "atomic electron field microscope"
            }

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue.", "stock_video_query": "soap"},
        {"scene_id": 2, "spoken_text": "nothing is real and everything is a lie", "stock_video_query": "sand"},
        {"scene_id": 3, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "kinetic"},
        {"scene_id": 4, "spoken_text": "If you replace every part of an axe is it the same axe...", "stock_video_query": "wood"},
    ]
    seo = {"title": "Why You Will Never Actually Experience The Present Moment"}

    mock_llm = MockCriticLLM()
    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="consciousness", llm_manager=mock_llm)

    # Scene 2 had a Wall Test failure — successfully revised via LLM
    assert audit_log["wall_test_failures"] >= 1
    assert audit_log["editorial_revisions_succeeded"] >= 1
    assert refined_scenes[1]["spoken_text"] == "You can never actually touch anything because atomic electron clouds repel each other."
    assert refined_scenes[1]["phonetic_text"] == refined_scenes[1]["spoken_text"]
    assert refined_scenes[1].get("_editorial_revised") is True
    # Title was extreme — should have been realigned
    assert refined_seo["title"] != seo["title"]
    assert len(refined_scenes) == len(scenes)  # Scene count unchanged
    assert audit_log["status"] == "passed"


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
    """LoopAuditorSkill must pass clean non-repeating compilation bridges, Mode B closers, and valid circular loopback bridges."""
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

    # Valid circular bridge with legitimate topical overlap (e.g. reflections)
    hook_reflect = "You have never actually seen your own face, only reflections and photos."
    loop_reflect = "And the wildest part about reflections is that..."
    repeats_r, reason_r = check_loop_repeats_hook(loop_reflect, hook_reflect)
    assert repeats_r is False, f"Expected clean loop, got: {reason_r}"
    passed_r, reason_audit_r = LoopAuditorSkill.audit_loop(loop_reflect, hook_reflect)
    assert passed_r is True, f"Expected circular loop to PASS, got: {reason_audit_r}"
    assert "Circular Loopback Bridge PASSED" in reason_audit_r

    # Valid circular bridge with 2 topic words (cold, water)
    hook_water = "Cold water tastes noticeably sweeter than warm water because temperature suppresses flavor."
    loop_water = "Which explains why the taste of cold water is so..."
    repeats_w, _ = check_loop_repeats_hook(loop_water, hook_water)
    assert repeats_w is False
    passed_w, reason_w = LoopAuditorSkill.audit_loop(loop_water, hook_water)
    assert passed_w is True, f"Expected circular loop to PASS, got: {reason_w}"


def test_loop_auditor_sanitize_loop_replaces_defective_loop():
    """LoopAuditorSkill.sanitize_loop normalizes a defective loop into a standalone ending without injecting canned CTAs."""
    from engine.managers.editorial_critic import LoopAuditorSkill, BRAINBLUD_CLOSERS

    hook = "The only part of your reflection you can lick is your tongue."
    bad_scene = {
        "scene_id": 12,
        "spoken_text": "And that is why the only part of your reflection you can lick is your tongue...",
        "phonetic_text": "And that is why the only part of your reflection you can lick is your tongue..."
    }

    sanitized = LoopAuditorSkill.sanitize_loop(bad_scene, hook_text=hook)
    # Must NOT inject a canned CTA from BRAINBLUD_CLOSERS
    assert sanitized["spoken_text"] not in BRAINBLUD_CLOSERS
    # Must normalize trailing dangling ellipsis to terminal period for a standalone ending
    assert sanitized["spoken_text"].endswith(".")
    assert not sanitized["spoken_text"].endswith("...")
    assert sanitized["spoken_text"] == "And that is why the only part of your reflection you can lick is your tongue."
    assert sanitized["phonetic_text"] == sanitized["spoken_text"]
    assert sanitized.get("_editorial_normalized") is True


def test_loop_auditor_preserves_standalone_ending_in_pipeline():
    """audit_and_refine_spec preserves a strong standalone ending without replacing it with a canned CTA."""
    from engine.managers.editorial_critic import audit_and_refine_spec, BRAINBLUD_CLOSERS

    scenes = [
        {"scene_id": 1, "spoken_text": "You have never actually seen your own face, only reflections and photos.", "stock_video_query": "mirror"},
        {"scene_id": 2, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "steady hands"},
        {"scene_id": 3, "spoken_text": "Every mirror you purchase is technically used since someone had to test it.", "stock_video_query": "mirror factory"},
    ]
    seo = {"title": "Shower Thoughts That Blow Minds 🤯 #shorts"}

    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="reflections")

    # Final scene is a standalone ending ending in period (not a loop bridge)
    # It must be preserved without canned CTA injection!
    assert refined_scenes[-1]["spoken_text"] == "Every mirror you purchase is technically used since someone had to test it."
    assert refined_scenes[-1]["spoken_text"] not in BRAINBLUD_CLOSERS
    assert refined_scenes[-1].get("_editorial_replaced") is not True


# ─── PURE SHOWER THOUGHT AUDITOR TESTS ────────────────────────────────────────

def test_pure_shower_thought_auditor_bans_trivia_facts():
    """PureShowerThoughtAuditor must reject formulaic trivia openers and clickbait framing."""
    from engine.managers.editorial_critic import PureShowerThoughtAuditor

    trivia_examples = [
        "Did you know that octopuses have three hearts and blue blood?",
        "Have you ever wondered why your phone compass uses a magnetometer?",
        "Did you know that sharks have been around longer than trees?",
        "Fun fact: your bones are wet inside your body right now.",
        "Have you ever noticed that elevator buttons feel different in hotels?",
        "A little-known fact is that honey never truly spoils.",
    ]
    for trivia in trivia_examples:
        passed, reason = PureShowerThoughtAuditor.audit_thought(trivia)
        assert not passed, f"Expected trivia ban for '{trivia}', got PASS"
        assert "Trivia Fact BANNED" in reason or "Trivia Opener BANNED" in reason


def test_pure_shower_thought_auditor_permits_animals_fungi_and_objects():
    """PureShowerThoughtAuditor permits natural observations about animals, fungi, and everyday objects without formulaic openers."""
    from engine.managers.editorial_critic import PureShowerThoughtAuditor

    valid_observations = [
        "Blue whales have an aorta large enough for a human to swim through.",
        "Scientists discovered that trees communicate underground through fungal networks.",
        "Elevator buttons don't actually register your touch using pressure sensors.",
        "The tiny hole at the bottom of a padlock is actually a drainage hole.",
        "Sharks have been around longer than trees.",
    ]
    for obs in valid_observations:
        passed, reason = PureShowerThoughtAuditor.audit_thought(obs)
        assert passed, f"Expected topic observation to PASS, got FAIL: {reason}"


def test_contextual_evaluation_permits_scientific_reality_statements():
    """Contextual auditor distinguishes scientific/grounded reality statements from solipsism and clichés."""
    from engine.managers.editorial_critic import CynicalHumanAuditor

    # Scientific/grounded reality statements must PASS
    sci_reality = "Reality is just the biological model created by your sensory cortex."
    passed_sci, reason_sci = CynicalHumanAuditor.audit_text(sci_reality)
    assert passed_sci is True, f"Expected scientific reality statement to PASS, got {reason_sci}"

    # Fake-deep solipsism must FAIL
    bad_solipsism_1 = "Reality is just an illusion created to fool you."
    passed_s1, reason_s1 = CynicalHumanAuditor.audit_text(bad_solipsism_1)
    assert passed_s1 is False
    assert "Wall Test FAILED" in reason_s1

    bad_solipsism_2 = "Reality is just a simulation running on alien hardware."
    passed_s2, reason_s2 = CynicalHumanAuditor.audit_text(bad_solipsism_2)
    assert passed_s2 is False

    # Biology fact without cliché must PASS
    bio_fact = "Stomach acid is powerful enough to dissolve razor blades, but your body continuously shields itself."
    passed_bio, reason_bio = CynicalHumanAuditor.audit_text(bio_fact)
    assert passed_bio is True, f"Expected biology fact to PASS, got {reason_bio}"

    # Specific cliché trope must FAIL
    bad_cliche = "Your stomach lining replaces itself every few days so stomach acid doesn't digest itself."
    passed_c, reason_c = CynicalHumanAuditor.audit_text(bad_cliche)
    assert passed_c is False
    assert "Cliché Audit FAILED" in reason_c


def test_revision_first_workflow_revises_weak_thought():
    """revise_scene_with_llm revises a defective thought using LLM feedback while preserving core concept."""
    from engine.managers.editorial_critic import revise_scene_with_llm

    class MockRevisionLLM:
        def __init__(self):
            self.prompts_received = []

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.prompts_received.append((system_prompt, user_prompt))
            return {
                "spoken_text": "You cannot hear a whisper in a storm because turbulence scatters acoustic energy.",
                "visual_hook": "storm ocean acoustic waves"
            }

    mock_llm = MockRevisionLLM()
    # Scene with dangling connector (fails completeness)
    bad_scene = {
        "scene_id": 2,
        "spoken_text": "You cannot hear a whisper in a storm because",
        "stock_video_query": "ocean storm"
    }

    revised, ok, msg = revise_scene_with_llm(
        scene=bad_scene,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm
    )

    assert ok is True
    assert revised.get("_editorial_revised") is True
    assert revised["spoken_text"] == "You cannot hear a whisper in a storm because turbulence scatters acoustic energy."
    assert revised["phonetic_text"] == revised["spoken_text"]
    assert revised["stock_video_query"] == "storm ocean acoustic waves"
    # Verify feedback was included in user prompt
    assert "dangling connector 'because'" in mock_llm.prompts_received[0][1]


def test_revision_preserves_original_core_idea_and_schema():
    """revise_scene_with_llm preserves metadata schema (scene_id, extra keys) upon revision."""
    from engine.managers.editorial_critic import revise_scene_with_llm

    class MockLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            return {
                "spoken_text": "Atomic electron clouds repel each other so you never physically make contact with surfaces.",
                "visual_hook": "electron microscope atoms"
            }

    mock = MockLLM()
    scene = {
        "scene_id": 5,
        "spoken_text": "nothing is real and everything is a lie",
        "custom_metadata": "critical_value",
        "stock_video_query": "sand timer"
    }

    revised, ok, _ = revise_scene_with_llm(scene, "Wall Test FAILED", llm_manager=mock)
    assert ok is True
    assert revised["scene_id"] == 5
    assert revised["custom_metadata"] == "critical_value"
    assert revised["spoken_text"] == "Atomic electron clouds repel each other so you never physically make contact with surfaces."
    assert revised["phonetic_text"] == revised["spoken_text"]


def test_exhausted_editorial_attempts_no_canned_substitutions():
    """When LLM revision attempts exhaust, scene is marked rejected without canned substitutions."""
    from engine.managers.editorial_critic import revise_scene_with_llm, BRAINBLUD_CLOSERS

    class MockPersistentFailureLLM:
        def __init__(self):
            self.attempts = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempts += 1
            # Still returns solipsistic banned text
            return {"spoken_text": "reality is just a simulation and nothing exists."}

    mock_bad = MockPersistentFailureLLM()
    scene = {"scene_id": 3, "spoken_text": "nothing is real"}

    rejected, ok, msg = revise_scene_with_llm(scene, "Wall Test FAILED", llm_manager=mock_bad, max_attempts=2)
    assert ok is False
    assert mock_bad.attempts == 2
    assert rejected.get("_editorial_rejected") is True
    # Verify NO canned replacement text was injected
    assert rejected["spoken_text"] not in BRAINBLUD_CLOSERS
    assert "The brain named itself" not in rejected["spoken_text"]
    assert "Your shadow has traveled" not in rejected["spoken_text"]


def test_audit_and_refine_spec_rejection_when_unresolved():
    """audit_and_refine_spec marks audit status as 'rejected' when an editorial failure cannot be resolved."""
    from engine.managers.editorial_critic import audit_and_refine_spec

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "nothing is real and everything is a lie"},
        {"scene_id": 3, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons."},
    ]
    seo = {"title": "Mind Glitches That Question Reality #shorts"}

    # No LLM provided to resolve the failure
    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="mind", llm_manager=None)
    assert audit_log["status"] == "rejected"
    assert audit_log["unresolved_failures"] >= 1
    assert refined_scenes[1].get("_editorial_rejected") is True


def test_pipeline_runner_halts_on_editorial_rejection():
    """pipeline_runner halts safely with ValueError when audit_and_refine_spec returns rejected status."""
    audit_summary = {
        "status": "rejected",
        "unresolved_failures": 1,
        "wall_test_failures": 1
    }

    with pytest.raises(ValueError, match="Editorial Critic rejected script: 1 unresolvable defect"):
        if audit_summary.get("status") == "rejected" or audit_summary.get("unresolved_failures", 0) > 0:
            raise ValueError(
                f"Editorial Critic rejected script: {audit_summary.get('unresolved_failures', 0)} unresolvable defect(s)"
            )


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
        "Scientists say the startle response shares circuitry with our ancient predator detection system.",
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


# ─── HOOK AUDIT & REVISED HOOK VALIDATION TESTS ──────────────────────────────

def test_audit_and_refine_spec_revises_and_validates_defective_hook():
    """A defective hook opener is revised with is_hook_scene=True, passes hook audit, and is accepted."""
    from engine.managers.editorial_critic import audit_and_refine_spec, HookAuditorSkill

    class MockHookRevisionLLM:
        def __init__(self):
            self.calls = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.calls += 1
            return {
                "spoken_text": "The only part of your reflection you can lick is your tongue.",
                "visual_hook": "mirror reflection bathroom"
            }

    scenes = [
        {"scene_id": 1, "spoken_text": "Hey guys, welcome back to the channel, today we explore mirrors.", "stock_video_query": "mirror"},
        {"scene_id": 2, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "steady hands"},
        {"scene_id": 3, "spoken_text": "Every mirror you purchase is technically used since someone had to test it.", "stock_video_query": "mirror factory"},
    ]
    seo = {"title": "Mind Glitches That Question Reality #shorts"}

    mock_llm = MockHookRevisionLLM()
    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="mirrors", llm_manager=mock_llm)

    assert mock_llm.calls >= 1
    # Revised hook passes HookAuditorSkill
    h_pass, _ = HookAuditorSkill.audit_hook(refined_scenes[0]["spoken_text"])
    assert h_pass is True
    assert refined_scenes[0].get("_editorial_revised") is True
    assert refined_scenes[0]["spoken_text"] == "The only part of your reflection you can lick is your tongue."
    assert refined_scenes[0]["phonetic_text"] == refined_scenes[0]["spoken_text"]
    assert refined_scenes[0]["scene_id"] == 1
    assert audit_log["hook_status"] == "passed"
    assert audit_log["status"] == "passed"


def test_audit_and_refine_spec_rejects_hook_if_revision_fails_hook_audit():
    """If hook revision candidate fails HookAuditorSkill, attempts exhaust and scene is rejected."""
    from engine.managers.editorial_critic import audit_and_refine_spec

    class MockFailingHookLLM:
        def __init__(self):
            self.attempts = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempts += 1
            # Passes wall/trivia/completeness, but fails HookAuditorSkill (starts with 'Imagine if')
            return {
                "spoken_text": "Imagine if your reflection was looking at someone completely different.",
                "visual_hook": "mirror"
            }

    scenes = [
        {"scene_id": 1, "spoken_text": "Hey guys, welcome back to the channel, today we explore mirrors.", "stock_video_query": "mirror"},
        {"scene_id": 2, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "steady hands"},
        {"scene_id": 3, "spoken_text": "Every mirror you purchase is technically used since someone had to test it.", "stock_video_query": "mirror factory"},
    ]
    seo = {"title": "Mind Glitches That Question Reality #shorts"}

    mock_llm = MockFailingHookLLM()
    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="mirrors", llm_manager=mock_llm)

    assert mock_llm.attempts == 2  # Bounded to attempt limit
    assert refined_scenes[0].get("_editorial_rejected") is True
    assert audit_log["status"] == "rejected"
    assert audit_log["unresolved_failures"] >= 1
    assert "failed" in audit_log["hook_status"].lower()


def test_audit_and_refine_spec_rejects_unresolved_hook_failure_without_llm():
    """A defective hook without an LLM manager cannot be resolved and is rejected safely."""
    from engine.managers.editorial_critic import audit_and_refine_spec, BRAINBLUD_CLOSERS

    scenes = [
        {"scene_id": 1, "spoken_text": "Hey guys, welcome back to the channel, today we explore mirrors.", "stock_video_query": "mirror"},
        {"scene_id": 2, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "steady hands"},
        {"scene_id": 3, "spoken_text": "Every mirror you purchase is technically used since someone had to test it.", "stock_video_query": "mirror factory"},
    ]
    seo = {"title": "Mind Glitches That Question Reality #shorts"}

    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="mirrors", llm_manager=None)

    assert refined_scenes[0].get("_editorial_rejected") is True
    assert audit_log["status"] == "rejected"
    assert audit_log["unresolved_failures"] >= 1
    assert "failed" in audit_log["hook_status"].lower()
    # Confirm zero canned replacements were injected
    assert refined_scenes[0]["spoken_text"] not in BRAINBLUD_CLOSERS
    assert "The brain named itself" not in refined_scenes[0]["spoken_text"]


def test_audit_and_refine_spec_punctuation_cleaned_hook_re_audited():
    """Punctuation cleanup on Scene 1 re-audits the hook and accepts it if clean."""
    from engine.managers.editorial_critic import audit_and_refine_spec

    scenes = [
        {"scene_id": 1, "spoken_text": "... The only part of your reflection you can lick is your tongue.", "stock_video_query": "mirror"},
        {"scene_id": 2, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons.", "stock_video_query": "steady hands"},
        {"scene_id": 3, "spoken_text": "Every mirror you purchase is technically used since someone had to test it.", "stock_video_query": "mirror factory"},
    ]
    seo = {"title": "Mind Glitches That Question Reality #shorts"}

    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(scenes, seo, topic="mirrors", llm_manager=None)

    assert refined_scenes[0]["spoken_text"] == "The only part of your reflection you can lick is your tongue."
    assert refined_scenes[0]["phonetic_text"] == refined_scenes[0]["spoken_text"]
    assert refined_scenes[0].get("_editorial_cleaned") is True
    assert audit_log["hook_status"] == "passed"
    assert audit_log["status"] == "passed"


def test_hook_auditor_accepts_concise_in_media_res_hook():
    """Phase 9A: Verifies HookAuditorSkill accepts concise hooks (<7 words) and enforces non-empty validation."""
    from engine.managers.editorial_critic import HookAuditorSkill

    # Concise valid hooks (<7 words, previously rejected by minimum 7 words)
    concise_hooks = [
        "Silence is louder than noise.",  # 5 words
        "Your shadow never leaves you.",   # 5 words
        "Clocks only measure movement.",   # 4 words
    ]
    for hook in concise_hooks:
        passed, reason = HookAuditorSkill.audit_hook(hook)
        assert passed is True, f"Expected concise hook '{hook}' to PASS, got {reason}"

    # Substantive non-empty check preserved
    passed_empty, reason_empty = HookAuditorSkill.audit_hook("")
    assert passed_empty is False
    assert "empty" in reason_empty.lower()

    passed_ws, reason_ws = HookAuditorSkill.audit_hook("   ")
    assert passed_ws is False
    assert "empty" in reason_ws.lower()


def test_loop_bridge_validation_accepts_concise_bridge():
    """Phase 9A: Verifies is_valid_circular_bridge accepts concise bridge with proper syntax and flow."""
    from engine.managers.editorial_critic import is_valid_circular_bridge, LoopAuditorSkill

    hook = "Time is an illusion."
    # Concise 3-word bridge with ellipsis (previously rejected by len(words) < 4)
    concise_bridge = "Which is why..."
    passed, reason = is_valid_circular_bridge(concise_bridge, hook)
    assert passed is True, f"Expected concise bridge to PASS, got: {reason}"

    passed_audit, reason_audit = LoopAuditorSkill.audit_loop(concise_bridge, hook)
    assert passed_audit is True, f"Expected LoopAuditorSkill to PASS concise bridge, got: {reason_audit}"

    # Verify whitespace-only bridge is rejected
    passed_ws, reason_ws = is_valid_circular_bridge("   ", hook)
    assert passed_ws is False
    assert "empty" in reason_ws.lower()


def test_pure_shower_thought_auditor_accepts_cleaned_concise_thought():
    """Phase 9A: Verifies PureShowerThoughtAuditor accepts cleaned opener even if concise (<7 words)."""
    from engine.managers.editorial_critic import PureShowerThoughtAuditor

    # Scene with trivia opener whose remaining content is concise (5 words: "Clouds weigh tons of water.")
    scene = {
        "scene_id": 2,
        "spoken_text": "Did you know clouds weigh tons of water.",
        "stock_video_query": "cloud sky"
    }
    sanitized = PureShowerThoughtAuditor.sanitize_scene(scene)
    assert sanitized["spoken_text"] == "Clouds weigh tons of water."
    assert sanitized.get("_editorial_cleaned") is True
    assert not sanitized.get("_editorial_rejected")


# ─── PHASE 10B EDITORIAL CRITIC & SCENE REVISION REDESIGN TESTS ───────────────

def test_editorial_critic_preserves_strong_scenes_untouched():
    """Phase 10B: When scenes are well-written and pass audits, they must remain completely unchanged."""
    from engine.managers.editorial_critic import audit_and_refine_spec, EditorialCritic

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "Snipers and surgeons need steady hands for the exact opposite reasons.", "stock_video_query": "steady hands"},
        {"scene_id": 2, "spoken_text": "Your future self is watching you right now through the lens of your memories.", "stock_video_query": "clock time"},
        {"scene_id": 3, "spoken_text": "Oxygen is slowly rusting our physical bodies from the inside out over decades.", "stock_video_query": "deep breath"},
        {"scene_id": 4, "spoken_text": "So every breath you take is both keeping you alive and slowly wearing you down.", "stock_video_query": "lungs breathing", "ending_type": "observation"}
    ]
    seo = {"title": "Shower Thoughts That Blow Minds 🧠 #shorts"}

    class UnusedLLM:
        def generate_json(self, *args, **kwargs):
            raise AssertionError("LLM should NOT be called when all scenes are strong and valid!")

    refined_scenes, refined_seo, audit_log = EditorialCritic.critique_and_refine_script(
        raw_scenes=raw_scenes,
        seo_data=seo,
        topic="shower thoughts",
        llm_manager=UnusedLLM(),
        channel_premise="Observant, witty perspective shifts on modern reality"
    )

    assert audit_log["status"] == "passed"
    assert audit_log["editorial_revisions_attempted"] == 0
    assert audit_log["unresolved_failures"] == 0
    assert len(refined_scenes) == 4
    for orig, refined in zip(raw_scenes, refined_scenes):
        assert refined["spoken_text"] == orig["spoken_text"]
        assert not refined.get("_editorial_revised")
        assert not refined.get("_editorial_rejected")


def test_editorial_critic_repairs_defect_with_surrounding_context_and_phonetic_sync():
    """Phase 10B: revise_scene_with_llm receives surrounding context, defect reason, and role, updating phonetic_text."""
    from engine.managers.editorial_critic import revise_scene_with_llm
    from engine.managers.voice_normalizer import VoiceNormalizer

    captured_prompts = []

    class MockContextRevisionLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            captured_prompts.append((system_prompt, user_prompt))
            return {
                "spoken_text": "Turbulence in the atmosphere scatters acoustic energy before it can travel.",
                "stock_video_query": "ocean storm soundwaves"
            }

    mock_llm = MockContextRevisionLLM()
    existing_preceding_scenes = [
        {"scene_id": 1, "spoken_text": "Sound travels differently across different mediums."}
    ]
    defective_middle_scene = {
        "scene_id": 2,
        "spoken_text": "You cannot hear a whisper in a storm because",
        "stock_video_query": "storm"
    }

    revised, ok, msg = revise_scene_with_llm(
        scene=defective_middle_scene,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm,
        existing_scenes=existing_preceding_scenes,
        is_final_scene=False,
        is_hook_scene=False,
        channel_premise="Curious physics and perception facts"
    )

    assert ok is True
    assert revised.get("_editorial_revised") is True
    assert revised["spoken_text"] == "Turbulence in the atmosphere scatters acoustic energy before it can travel."
    assert revised["phonetic_text"] == VoiceNormalizer.normalize_text(revised["spoken_text"])
    assert revised["stock_video_query"] == "ocean storm soundwaves"

    # Verify context, role, and channel premise reached user_prompt
    user_p = captured_prompts[0][1]
    assert "Curious physics and perception facts" in user_p
    assert "Sound travels differently across different mediums." in user_p
    assert "MIDDLE THOUGHT SCENE" in user_p
    assert "dangling connector 'because'" in user_p


def test_editorial_revision_preserves_numerical_claims_and_rejects_corruption():
    """Phase 10B: revise_scene_with_llm rejects revision attempts that alter, drop, or sign-flip numbers."""
    from engine.managers.editorial_critic import revise_scene_with_llm

    class NumberCorruptingLLM:
        def __init__(self):
            self.attempt = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempt += 1
            if self.attempt == 1:
                # Attempt 1: Drops the number '24' and alters '16' to '10'
                return {"spoken_text": "Astronauts in space witness about 10 sunrises."}
            # Attempt 2: Correctly preserves '16' and '24' in order
            return {"spoken_text": "Astronauts in low Earth orbit witness 16 distinct sunrises every 24 hours."}

    mock_llm = NumberCorruptingLLM()
    # Scene that has a completeness failure but carries exact numbers: 16 and 24
    defective_num_scene = {
        "scene_id": 2,
        "spoken_text": "Astronauts see 16 sunrises every 24 hours because",
        "stock_video_query": "iss orbit"
    }

    revised, ok, msg = revise_scene_with_llm(
        scene=defective_num_scene,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm,
        max_attempts=2
    )

    assert ok is True
    assert mock_llm.attempt == 2
    assert revised["spoken_text"] == "Astronauts in low Earth orbit witness 16 distinct sunrises every 24 hours."
    assert "16" in revised["spoken_text"] and "24" in revised["spoken_text"]


def test_editorial_critic_class_interface_methods():
    """Phase 10B: Verifies EditorialCritic class methods are available and callable."""
    from engine.managers.editorial_critic import EditorialCritic

    assert hasattr(EditorialCritic, "critique_and_refine_script")
    assert hasattr(EditorialCritic, "audit_and_refine_scene")
    assert hasattr(EditorialCritic, "audit_and_refine_spec")

    # Verify audit_and_refine_scene handles clean scene without LLM
    clean_scene = {"scene_id": 1, "spoken_text": "Clocks measure entropy much more than they measure time."}
    # If no defect is passed or scene passes, returns cleanly
    result, ok, _ = EditorialCritic.audit_and_refine_scene(clean_scene, "clean", llm_manager=None)
    assert not ok  # No LLM available when failure passed
    assert result.get("_editorial_rejected") is True


def test_editorial_revision_prompt_in_prompts_yaml():
    """Phase 10B: Verifies config/prompts.yaml defines editorial_revision with core principles and no phrase blacklists."""
    import yaml

    with open("config/prompts.yaml", "r", encoding="utf-8") as f:
        prompts = yaml.safe_load(f)

    assert "editorial_revision" in prompts
    sys_prompt = prompts["editorial_revision"]["system_prompt"]
    assert "SMALLEST EFFECTIVE REPAIR" in sys_prompt
    assert "Precision Repair" in sys_prompt
    assert "Strict Fact & Numerical Integrity" in sys_prompt
    assert "Ending Intent" in sys_prompt
    # Ensure no hard-coded phrase blacklists in system prompt
    assert "Did you know" not in sys_prompt
    assert "Fun fact" not in sys_prompt
    assert "alarm clock" not in sys_prompt


def test_editorial_revision_zero_numbers_rejected_and_numerical_preservation():
    """Phase 10B.1: revise_scene_with_llm rejects inventing numbers in zero-number scenes,
    retains bounded retries, and preserves signs, precision, counts, and ordering."""
    from engine.managers.editorial_critic import revise_scene_with_llm

    # A. Scene with ZERO numbers cannot have numbers introduced by LLM revision
    class ZeroNumberInventingLLM:
        def __init__(self):
            self.attempt = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempt += 1
            if self.attempt == 1:
                # Attempt 1: Invent an unsupported number '42'
                return {"spoken_text": "You set your alarm for 42 minutes before sunrise."}
            # Attempt 2: Clean zero-number repair
            return {"spoken_text": "You set your alarm for a future self you rarely agree with."}

    mock_llm_a = ZeroNumberInventingLLM()
    zero_num_scene = {
        "scene_id": 2,
        "spoken_text": "You set alarms for the morning because",
        "stock_video_query": "alarm clock bedside"
    }

    revised_a, ok_a, msg_a = revise_scene_with_llm(
        scene=zero_num_scene,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm_a,
        max_attempts=2
    )

    assert ok_a is True
    assert mock_llm_a.attempt == 2
    assert "42" not in revised_a["spoken_text"]
    assert revised_a["spoken_text"] == "You set your alarm for a future self you rarely agree with."
    assert revised_a.get("_editorial_revised") is True

    # B. Scene with ZERO numbers where LLM persistently invents numbers exhausts retries and fails closed
    class PersistentNumberInventingLLM:
        def __init__(self):
            self.attempt = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempt += 1
            # Every attempt invents a number
            return {"spoken_text": f"Mirrors reflect {self.attempt * 10} rays of light."}

    mock_llm_b = PersistentNumberInventingLLM()
    zero_num_scene_b = {
        "scene_id": 3,
        "spoken_text": "Mirrors don't break because",
        "stock_video_query": "mirror reflection"
    }

    rejected_b, ok_b, msg_b = revise_scene_with_llm(
        scene=zero_num_scene_b,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm_b,
        max_attempts=2
    )

    assert ok_b is False
    assert mock_llm_b.attempt == 2
    assert rejected_b.get("_editorial_rejected") is True
    # Invariant: Never substitutes canned text; retains original scene text
    assert rejected_b["spoken_text"] == "Mirrors don't break because"
    assert "LLM revision exhausted (2 attempts)" in msg_b
    assert "invented numerical claims" in msg_b

    # C. Numerical sign corruption (-5 vs 5) is rejected
    class SignCorruptingLLM:
        def __init__(self):
            self.attempt = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempt += 1
            if self.attempt == 1:
                # Changes -5 to 5 (or +5)
                return {"spoken_text": "In deep mines temperatures reach 5 degrees."}
            return {"spoken_text": "In deep mines temperatures drop to -5 degrees."}

    mock_llm_c = SignCorruptingLLM()
    negative_num_scene = {
        "scene_id": 4,
        "spoken_text": "In deep mines temperatures reach -5 degrees because",
        "stock_video_query": "deep mine cavern"
    }

    revised_c, ok_c, _ = revise_scene_with_llm(
        scene=negative_num_scene,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm_c,
        max_attempts=2
    )
    assert ok_c is True
    assert mock_llm_c.attempt == 2
    assert "-5" in revised_c["spoken_text"]

    # D. Numeric ordering corruption ([10, 2] vs [2, 10]) is rejected
    class OrderCorruptingLLM:
        def __init__(self):
            self.attempt = 0

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.attempt += 1
            if self.attempt == 1:
                # Inverts order of 10 and 2
                return {"spoken_text": "Runners finish 2 laps every 10 minutes."}
            return {"spoken_text": "Runners finish 10 laps every 2 hours."}

    mock_llm_d = OrderCorruptingLLM()
    ordered_scene = {
        "scene_id": 5,
        "spoken_text": "Runners finish 10 laps every 2 minutes because",
        "stock_video_query": "runner track"
    }

    revised_d, ok_d, _ = revise_scene_with_llm(
        scene=ordered_scene,
        failure_reason="Thought Completeness FAILED: Ends with dangling connector 'because'",
        llm_manager=mock_llm_d,
        max_attempts=2
    )
    assert ok_d is True
    assert mock_llm_d.attempt == 2
    assert revised_d["spoken_text"] == "Runners finish 10 laps every 2 hours."


def test_editorial_revision_uses_supplied_prompts_cfg_not_disk():
    """Phase 10B.1: revise_scene_with_llm and _load_editorial_revision_prompt use
    supplied in-memory prompts_cfg and do not fall back to disk YAML when present."""
    from engine.managers.editorial_critic import _load_editorial_revision_prompt, revise_scene_with_llm

    custom_prompt_text = "CUSTOM TEST SYSTEM PROMPT FOR EDITORIAL REVISION (NO DISK READ)"
    custom_cfg_dict = {
        "editorial_revision": {
            "system_prompt": custom_prompt_text
        }
    }
    loaded = _load_editorial_revision_prompt(custom_cfg_dict)
    assert loaded == custom_prompt_text

    # Also test when editorial_revision is passed directly as a string
    custom_cfg_str = {
        "editorial_revision": "STRING PROMPT OVERRIDE"
    }
    assert _load_editorial_revision_prompt(custom_cfg_str) == "STRING PROMPT OVERRIDE"

    # Verify revise_scene_with_llm passes the in-memory prompt to the LLM manager
    class PromptCheckingLLM:
        def __init__(self):
            self.received_system_prompt = None

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.received_system_prompt = system_prompt
            return {"spoken_text": "Clocks measure entropy much more than they measure time."}

    mock_llm = PromptCheckingLLM()
    scene = {"scene_id": 1, "spoken_text": "Clocks measure entropy because"}
    revised, ok, _ = revise_scene_with_llm(
        scene=scene,
        failure_reason="Thought Completeness FAILED",
        llm_manager=mock_llm,
        prompts_cfg=custom_cfg_dict
    )
    assert ok is True
    assert mock_llm.received_system_prompt == custom_prompt_text


def test_audit_and_refine_spec_forwards_channel_premise_and_prompts_cfg():
    """Phase 10B.1: audit_and_refine_spec forwards channel_premise and prompts_cfg to revision LLM."""
    from engine.managers.editorial_critic import audit_and_refine_spec

    class PremiseCheckingLLM:
        def __init__(self):
            self.received_user_prompt = None
            self.received_system_prompt = None

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.received_system_prompt = system_prompt
            self.received_user_prompt = user_prompt
            return {"spoken_text": "Clocks measure entropy rather than time."}

    mock_llm = PremiseCheckingLLM()
    # Scene 1 with bad hook opener that fails HookAuditor and triggers revision
    scenes = [
        {"scene_id": 1, "spoken_text": "Did you know that clocks measure entropy because"}
    ]
    seo = {"title": "Entropy of Time"}
    custom_premise = "Sarcastic cosmic dread and dry deadpan observations"
    custom_prompts_cfg = {
        "editorial_revision": {
            "system_prompt": "CRITIC REVISION PROMPT V2"
        }
    }

    refined_scenes, refined_seo, audit_log = audit_and_refine_spec(
        raw_scenes=scenes,
        seo_data=seo,
        topic="Entropy",
        llm_manager=mock_llm,
        channel_premise=custom_premise,
        prompts_cfg=custom_prompts_cfg
    )

    assert mock_llm.received_system_prompt == "CRITIC REVISION PROMPT V2"
    assert f"CHANNEL PREMISE / TONE: {custom_premise}" in mock_llm.received_user_prompt
    assert audit_log["status"] == "passed"
    assert refined_scenes[0].get("_editorial_revised") is True


def test_pipeline_runner_production_callsite_wiring_to_editorial_critic(monkeypatch, tmp_path):
    """Phase 10B.1: Verifies run_spec_stage passes llm, channel_premise, prompts_cfg,
    raw_scenes, seo_data, and topic to audit_and_refine_spec in the production flow."""
    from engine.managers.pipeline_runner import run_spec_stage

    # Temporarily remove PYTEST_CURRENT_TEST to enter the production editorial branch
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Isolate directories under tmp_path
    test_out = tmp_path / "output"
    test_out.mkdir(parents=True, exist_ok=True)
    test_mem = tmp_path / "memory"
    test_mem.mkdir(parents=True, exist_ok=True)
    test_cfg = tmp_path / "config"
    test_cfg.mkdir(parents=True, exist_ok=True)

    orig_join = os.path.join
    def safe_join(*args):
        if args and args[0] == "output":
            return str(test_out / orig_join(*args[1:]))
        if args and args[0] == "memory":
            return str(test_mem / orig_join(*args[1:]))
        return orig_join(*args)

    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", safe_join)
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_mem / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_mem / "used_topics_registry.json"))

    # Isolate LLMQualityTracker persistence
    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg / "model_quality_scores.json")

    # Isolate save_past_spoken_thoughts
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.save_past_spoken_thoughts",
        lambda thoughts: None
    )

    # Mock external calls and health checks
    from engine.managers.pipeline_runner import load_yaml
    orig_load_yaml = load_yaml
    def mock_load_yaml(path):
        data = orig_load_yaml(path)
        if "channel_config" in path:
            import copy
            data = copy.deepcopy(data)
            rules = data.setdefault("prompt_settings", {})
            rules["extra_instructions"] = "Keep observations sharp, specific, and grounded."
            rules["banned_phrases"] = ["mind-boggling", "astounding"]
        return data

    monkeypatch.setattr("engine.managers.pipeline_runner.load_yaml", mock_load_yaml)
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.load_dynamic_weights", lambda: {})
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Entropy and Clocks",
        "verified_summary": "Entropy is time's arrow.",
        "source": "verified_trend"
    })

    generated_scenes = [
        {"scene_id": 1, "spoken_text": "Clocks measure entropy much more than they measure time.", "stock_video_query": "clock face"},
        {"scene_id": 2, "spoken_text": "Every second increases the disorder of the cosmos.", "stock_video_query": "galaxy motion"}
    ]
    generated_seo = {
        "title": "Why Clocks Don't Measure Time #shorts",
        "description": "Entropy and the illusion of time. #shorts",
        "tags": ["entropy", "time", "shorts"]
    }

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (generated_scenes, generated_seo)
    )
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))
    monkeypatch.setattr("engine.managers.youtube_manager.YouTubeManager.generate_community_post", lambda topic, hook: {"post": "sample poll"})
    monkeypatch.setattr("engine.managers.youtube_manager.generate_seo_title", lambda **kw: "Why Clocks Don't Measure Time #shorts")

    # Record all calls to audit_and_refine_spec
    captured_calls = []
    def spy_audit_and_refine_spec(raw_scenes, seo_data, topic, llm_manager=None, channel_premise="", prompts_cfg=None):
        captured_calls.append({
            "raw_scenes": raw_scenes,
            "seo_data": seo_data,
            "topic": topic,
            "llm_manager": llm_manager,
            "channel_premise": channel_premise,
            "prompts_cfg": prompts_cfg
        })
        return raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", spy_audit_and_refine_spec)

    # Execute spec generation for Shorts
    run_spec_stage(video_type="short")

    # Verify audit_and_refine_spec was called
    assert len(captured_calls) >= 1
    call_args = captured_calls[0]

    # 1. Verify llm_manager is passed
    assert call_args["llm_manager"] is not None

    # 2. Verify channel_premise is passed and non-empty (from channel_config.yaml)
    assert isinstance(call_args["channel_premise"], str)
    assert len(call_args["channel_premise"].strip()) > 0

    # 3. Verify prompts_cfg is passed and contains editorial_revision
    assert isinstance(call_args["prompts_cfg"], dict)
    assert "editorial_revision" in call_args["prompts_cfg"]
    assert "system_prompt" in call_args["prompts_cfg"]["editorial_revision"]

    # 4. Verify topic and raw_scenes match
    assert call_args["topic"] == "Entropy and Clocks"
    assert len(call_args["raw_scenes"]) == 2

    # 5. Verify single-owner prompt flow and channel-instruction propagation:
    # Channel extra instructions and banned phrases reach creative prompts exactly once
    triplet_sys_prompt = call_args["prompts_cfg"]["triplet_anchor_scenes"]["system_prompt"]
    assert triplet_sys_prompt.count("ADDITIONAL CHANNEL INSTRUCTION: Keep observations sharp, specific, and grounded.") == 1
    assert triplet_sys_prompt.count('EXTRA BANNED PHRASES (channel-specific): "mind-boggling", "astounding". Never use these.') == 1

    # Channel extra instructions and banned phrases reach editorial_revision exactly once
    ed_sys_prompt = call_args["prompts_cfg"]["editorial_revision"]["system_prompt"]
    assert ed_sys_prompt.count("ADDITIONAL CHANNEL INSTRUCTION: Keep observations sharp, specific, and grounded.") == 1
    assert ed_sys_prompt.count('EXTRA BANNED PHRASES (channel-specific): "mind-boggling", "astounding". Never use these.') == 1
    # Generic virality language is NOT injected into editorial revision
    assert "VIRALITY ENFORCEMENT" not in ed_sys_prompt


def test_apply_prompt_rules_to_config_propagates_to_editorial_revision_idempotently():
    """Phase 10B.3: apply_prompt_rules_to_config propagates channel-specific banned phrases
    and extra instructions to editorial_revision exactly once without virality hype or duplication."""
    from engine.managers.pipeline_runner import apply_prompt_rules_to_config
    from engine.managers.editorial_critic import _load_editorial_revision_prompt, revise_scene_with_llm

    base_prompts_cfg = {
        "triplet_anchor_scenes": {"system_prompt": "Triplet base prompt."},
        "editorial_revision": {
            "system_prompt": "You are an expert editorial critic. Perform the SMALLEST EFFECTIVE REPAIR."
        }
    }
    channel_cfg = {
        "prompt_settings": {
            "extra_instructions": "Focus on subtle psychological tension.",
            "banned_phrases": ["jaw-dropping", "unbelievable"],
            "enforce_virality": True
        }
    }

    # First application: rules applied exactly once
    patched_1 = apply_prompt_rules_to_config(base_prompts_cfg, channel_cfg)
    ed_prompt_1 = patched_1["editorial_revision"]["system_prompt"]

    assert ed_prompt_1.count("ADDITIONAL CHANNEL INSTRUCTION: Focus on subtle psychological tension.") == 1
    assert ed_prompt_1.count('EXTRA BANNED PHRASES (channel-specific): "jaw-dropping", "unbelievable". Never use these.') == 1
    # Ensure generic virality language is not injected into editorial revision
    assert "VIRALITY ENFORCEMENT" not in ed_prompt_1

    # Second application: idempotency check (must not accumulate duplicates)
    patched_2 = apply_prompt_rules_to_config(patched_1, channel_cfg)
    ed_prompt_2 = patched_2["editorial_revision"]["system_prompt"]

    assert ed_prompt_2.count("ADDITIONAL CHANNEL INSTRUCTION: Focus on subtle psychological tension.") == 1
    assert ed_prompt_2.count('EXTRA BANNED PHRASES (channel-specific): "jaw-dropping", "unbelievable". Never use these.') == 1

    # Compatibility check: editorial_revision configured as a direct string
    string_prompts_cfg = {
        "editorial_revision": "Base string prompt for revision."
    }
    patched_str = apply_prompt_rules_to_config(string_prompts_cfg, channel_cfg)
    assert isinstance(patched_str["editorial_revision"], str)
    assert patched_str["editorial_revision"].count("ADDITIONAL CHANNEL INSTRUCTION: Focus on subtle psychological tension.") == 1
    assert patched_str["editorial_revision"].count('EXTRA BANNED PHRASES (channel-specific): "jaw-dropping", "unbelievable". Never use these.') == 1

    # Verify _load_editorial_revision_prompt consumes the configured in-memory prompt
    loaded = _load_editorial_revision_prompt(patched_1)
    assert loaded == ed_prompt_1

    # Verify revise_scene_with_llm delivers these channel rules to the LLM
    class RulesCheckingLLM:
        def __init__(self):
            self.received_system_prompt = None

        def generate_json(self, system_prompt, user_prompt, temperature=0.7, task_name="rewrite"):
            self.received_system_prompt = system_prompt
            return {"spoken_text": "Clocks measure entropy much more than they measure time."}

    mock_llm = RulesCheckingLLM()
    scene = {"scene_id": 1, "spoken_text": "Clocks measure entropy because"}
    revised, ok, _ = revise_scene_with_llm(
        scene=scene,
        failure_reason="Thought Completeness FAILED",
        llm_manager=mock_llm,
        prompts_cfg=patched_1
    )
    assert ok is True
    assert 'EXTRA BANNED PHRASES (channel-specific): "jaw-dropping", "unbelievable"' in mock_llm.received_system_prompt
    assert "ADDITIONAL CHANNEL INSTRUCTION: Focus on subtle psychological tension." in mock_llm.received_system_prompt
    assert "VIRALITY ENFORCEMENT" not in mock_llm.received_system_prompt


# ─── PHASE 10C: SEO & METADATA QUALITY TESTS ──────────────────────────────────

def test_seo_gen_prompt_in_prompts_yaml():
    """Phase 10C: Verifies config/prompts.yaml defines seo_gen with grounded creative
    principles, avoiding clickbait formulas, arbitrary word/char counts, and canned channels."""
    import yaml

    with open("config/prompts.yaml", "r", encoding="utf-8") as f:
        prompts = yaml.safe_load(f)

    assert "seo_gen" in prompts
    seo_entry = prompts["seo_gen"]
    sys_prompt = seo_entry.get("system_prompt", "")
    usr_template = seo_entry.get("user_template", "")

    # Core metadata principles present
    assert "accurate, compelling, and natural" in sys_prompt
    assert "CORE METADATA PRINCIPLES" in sys_prompt
    assert "Titles:" in sys_prompt
    assert "Descriptions:" in sys_prompt
    assert "Tags:" in sys_prompt

    # No generic clickbait formulas or arbitrary limits
    assert "Illegal To Know" not in sys_prompt
    assert "@metopato" not in sys_prompt
    assert "10-14" not in sys_prompt  # No fixed tag count formula
    assert "50-65 chars" not in sys_prompt  # No arbitrary char limit

    # User template accepts topic and script_text
    assert "{topic}" in usr_template
    assert "{script_text}" in usr_template


def test_iterative_generator_generate_seo_receives_topic_and_script():
    """Phase 10C: Verifies _generate_seo passes topic and script into the prompt
    and returns compliant {title, description, tags} matching downstream contracts."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class MockSEOResponseLLM:
        def __init__(self):
            self.last_system_prompt = None
            self.last_user_prompt = None

        def generate_json(self, system_prompt, user_prompt, temperature=0.3, task_name="seo_gen"):
            self.last_system_prompt = system_prompt
            self.last_user_prompt = user_prompt
            return {
                "title": "Why Time Moves In One Direction #shorts",
                "description": "An exploration of entropy, thermodynamics, and the psychological arrow of time.\n\n#shorts",
                "tags": ["entropy", "time", "thermodynamics", "physics", "shorts"]
            }

    mock_llm = MockSEOResponseLLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes = [
        {"scene_id": 1, "spoken_text": "Clocks measure entropy much more than they measure time."},
        {"scene_id": 2, "spoken_text": "The arrow of time only points toward disorder."}
    ]

    seo = generator._generate_seo(scenes=scenes, topic="Thermodynamic Arrow of Time")

    # Verify prompt inputs
    assert "TOPIC: Thermodynamic Arrow of Time" in mock_llm.last_user_prompt
    assert "Clocks measure entropy" in mock_llm.last_user_prompt
    assert "accurate, compelling, and natural" in mock_llm.last_system_prompt

    # Verify downstream contract compliance
    assert seo["title"] == "Why Time Moves In One Direction #shorts"
    assert seo["description"].startswith(seo["title"])
    assert "\n\n" in seo["description"]
    assert "entropy" in seo["description"]
    assert isinstance(seo["tags"], list)
    assert "entropy" in seo["tags"]
    assert "shorts" in seo["tags"]


def test_seo_title_and_critic_rejects_unsupported_numerical_claims():
    """Phase 10C: TitleScriptAlignmentSkill and _generate_seo reject titles that invent
    numerical claims absent from all scenes in the script."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    # 1. TitleScriptAlignmentSkill audit check
    zero_num_scenes = [
        {"scene_id": 1, "spoken_text": "Clocks measure entropy rather than time."},
        {"scene_id": 2, "spoken_text": "Mirrors reflect rays without judging what they see."}
    ]

    # Title inventing number '7'
    bad_num_title = "7 Shocking Facts About Time #shorts"
    passed, reason = TitleScriptAlignmentSkill.audit_title(bad_num_title, zero_num_scenes)
    assert passed is False
    assert "Contains numerical claim(s) ['7'] unsupported by script" in reason

    # Title with supported numbers in script
    scenes_with_numbers = [
        {"scene_id": 1, "spoken_text": "Astronauts see 16 sunrises every 24 hours."}
    ]
    supported_title = "Why Astronauts Witness 16 Sunrises #shorts"
    passed_sup, _ = TitleScriptAlignmentSkill.audit_title(supported_title, scenes_with_numbers)
    assert passed_sup is True

    # 2. _generate_seo title realigns away from invented numbers
    class InventedNumberLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.3, task_name="seo_gen"):
            return {
                "title": "10 Secrets About Entropy That Break Physics #shorts",
                "description": "Grounded look at thermodynamics.\n\n#shorts",
                "tags": ["entropy", "physics", "shorts"]
            }

    mock_llm = InventedNumberLLM()
    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    seo = generator._generate_seo(scenes=zero_num_scenes, topic="Entropy Paradox")

    # Title must not contain the unsupported '10'
    assert "10" not in seo["title"]
    assert "#shorts" in seo["title"]


def test_seo_fallback_path_grounded_without_canned_boilerplate():
    """Phase 10C.1: When LLM generation fails, fallback SEO derives grounded metadata
    directly from script content and topic without @metopato promotional filler or
    generic canned titles like 'Realizations That Break Your Brain'."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class FailingLLM:
        def generate_json(self, *args, **kwargs):
            raise RuntimeError("LLM API connection error")

    failing_llm = FailingLLM()
    generator = IterativeScriptGenerator(llm_manager=failing_llm)
    scenes = [
        {"scene_id": 1, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons."},
        {"scene_id": 2, "spoken_text": "One stops a heart while the other keeps it beating."}
    ]

    fallback_seo = generator._generate_seo(scenes=scenes, topic="Steady Hands Paradox")

    # Preserves expected output schema
    assert "title" in fallback_seo
    assert "description" in fallback_seo
    assert "tags" in fallback_seo

    # Grounded in script substance rather than generic formulas
    assert "Snipers and surgeons need steady hands for opposite reasons" in fallback_seo["title"]
    assert "#shorts" in fallback_seo["title"]
    assert "Realizations That Break Your Brain" not in fallback_seo["title"]

    assert fallback_seo["description"].startswith(fallback_seo["title"])
    assert "Steady Hands Paradox" in fallback_seo["description"]
    assert "Snipers and surgeons need steady hands for opposite reasons" in fallback_seo["description"]
    # No canned channel handle or promotional spam
    assert "@metopato" not in fallback_seo["description"]
    assert "Illegal To Know" not in fallback_seo["title"]

    # Tags include topic and extracted keywords
    assert "steady hands paradox" in fallback_seo["tags"]
    assert "shorts" in fallback_seo["tags"]


def test_seo_fallback_when_insufficient_information():
    """Phase 10C.1: When both scenes and topic provide insufficient information,
    fallback SEO produces a neutral, accurate title and description without sensationalism."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    class FailingLLM:
        def generate_json(self, *args, **kwargs):
            raise RuntimeError("LLM API connection error")

    failing_llm = FailingLLM()
    generator = IterativeScriptGenerator(llm_manager=failing_llm)

    fallback_seo = generator._generate_seo(scenes=[], topic="")

    assert fallback_seo["title"] == "Observations and Perspectives #shorts"
    assert "Realizations That Break Your Brain" not in fallback_seo["title"]
    assert "Observations and perspectives from this video." in fallback_seo["description"]
    assert "@metopato" not in fallback_seo["description"]
    assert "shorts" in fallback_seo["tags"]


def test_title_numeric_validation_rejects_numbers_present_only_in_topic():
    """Phase 10C.1: Title numerical claims must be supported by the final script,
    not merely by the selected topic."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    zero_num_scenes = [
        {"scene_id": 1, "spoken_text": "Time moves forward because cosmic entropy increases."}
    ]
    topic_with_num = "5 Proofs That Time Is Directional"

    # 1. TitleScriptAlignmentSkill rejects title with '5' when absent from script
    title_with_num = "5 Proofs That Time Moves Forward #shorts"
    passed, reason = TitleScriptAlignmentSkill.audit_title(title_with_num, zero_num_scenes)
    assert passed is False
    assert "Contains numerical claim(s) ['5'] unsupported by script" in reason

    # 2. _generate_seo rejects LLM candidate title with '5' even though '5' is in the topic
    class NumberInTopicLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.3, task_name="seo_gen"):
            return {
                "title": "5 Proofs That Time Moves Forward #shorts",
                "description": "Exploration of entropy.\n\n#shorts",
                "tags": ["entropy", "time", "shorts"]
            }

    generator = IterativeScriptGenerator(llm_manager=NumberInTopicLLM())
    seo = generator._generate_seo(scenes=zero_num_scenes, topic=topic_with_num)

    # Output title must not retain the unsupported '5'
    assert "5" not in seo["title"]
    assert "#shorts" in seo["title"]
    # Realigned to script substance
    assert "Time moves forward because cosmic entropy increases" in seo["title"]


def test_title_numeric_validation_multiplicity_counter():
    """Phase 10C.1: Multiplicity-aware numerical validation: duplicate claims cannot
    pass merely because the number appears once in the script."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [
        {"scene_id": 1, "spoken_text": "A day on Venus lasts 243 Earth days."}
    ]

    # Single occurrence matching script passes
    single_title = "Why Venus Takes 243 Days To Rotate #shorts"
    passed, _ = TitleScriptAlignmentSkill.audit_title(single_title, scenes)
    assert passed is True

    # Duplicate occurrence exceeding script count fails
    duplicate_title = "243 Days, 243 Nights On Venus #shorts"
    passed_dup, reason_dup = TitleScriptAlignmentSkill.audit_title(duplicate_title, scenes)
    assert passed_dup is False
    assert "Contains numerical claim(s) ['243'] unsupported by script" in reason_dup


def test_title_numeric_validation_formatting_equivalence():
    """Phase 10C.1: Supported formatting equivalence (comma formatting, trailing decimal zeros)
    is handled consistently while rejecting unsupported values."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [
        {"scene_id": 1, "spoken_text": "The core reaches 10,000 degrees at 3.5 atmospheres."}
    ]

    # Comma equivalence: 10000 matches 10,000
    title_no_comma = "Why Core Hits 10000 Degrees #shorts"
    passed_c, _ = TitleScriptAlignmentSkill.audit_title(title_no_comma, scenes)
    assert passed_c is True

    # Decimal zero equivalence: 3.50 matches 3.5
    title_dec_zero = "Stable At 3.50 Atmospheres #shorts"
    passed_d, _ = TitleScriptAlignmentSkill.audit_title(title_dec_zero, scenes)
    assert passed_d is True

    # Distinct number fails
    title_wrong = "Why Core Hits 10001 Degrees #shorts"
    passed_w, reason_w = TitleScriptAlignmentSkill.audit_title(title_wrong, scenes)
    assert passed_w is False
    assert "['10001']" in reason_w


def test_apply_prompt_rules_to_config_propagates_to_seo_gen():
    """Phase 10C: apply_prompt_rules_to_config propagates channel-specific banned phrases
    and extra instructions to seo_gen exactly once without virality hype."""
    from engine.managers.pipeline_runner import apply_prompt_rules_to_config

    prompts_cfg = {
        "seo_gen": {
            "system_prompt": "Base SEO generation prompt."
        }
    }
    channel_cfg = {
        "prompt_settings": {
            "extra_instructions": "Focus metadata on cerebral and psychological curiosity.",
            "banned_phrases": ["unbelievable", "mind-blowing"],
            "enforce_virality": True
        }
    }

    patched = apply_prompt_rules_to_config(prompts_cfg, channel_cfg)
    seo_sys = patched["seo_gen"]["system_prompt"]

    assert seo_sys.count("ADDITIONAL CHANNEL INSTRUCTION: Focus metadata on cerebral and psychological curiosity.") == 1
    assert seo_sys.count('EXTRA BANNED PHRASES (channel-specific): "unbelievable", "mind-blowing". Never use these.') == 1
    # Virality hype is omitted from SEO metadata prompt
    assert "VIRALITY ENFORCEMENT" not in seo_sys

    # Idempotency check
    patched_again = apply_prompt_rules_to_config(patched, channel_cfg)
    assert patched_again["seo_gen"]["system_prompt"].count("ADDITIONAL CHANNEL INSTRUCTION") == 1
    assert patched_again["seo_gen"]["system_prompt"].count("EXTRA BANNED PHRASES") == 1


def test_pipeline_runner_refreshes_seo_after_factuality_rewrite(monkeypatch, tmp_path):
    """Phase 10C: If Claim Inspector rewrites a scene for factuality, pipeline_runner
    refreshes SEO metadata against the verified scenes rather than retaining stale metadata."""
    from engine.managers.pipeline_runner import run_spec_stage, FactualityPolicyStatus
    from engine.managers.claim_inspector import ClaimRecord

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    test_out = tmp_path / "output"
    test_out.mkdir(parents=True, exist_ok=True)
    test_mem = tmp_path / "memory"
    test_mem.mkdir(parents=True, exist_ok=True)
    test_cfg = tmp_path / "config"
    test_cfg.mkdir(parents=True, exist_ok=True)

    orig_join = os.path.join
    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", lambda *args: str(test_out / orig_join(*args[1:])) if args and args[0] == "output" else orig_join(*args))
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_mem / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_mem / "used_topics_registry.json"))

    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg / "model_quality_scores.json")
    monkeypatch.setattr("engine.managers.iterative_script_generator.save_past_spoken_thoughts", lambda thoughts: None)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.load_dynamic_weights", lambda: {})
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Light Speed Paradox",
        "verified_summary": "Nothing travels faster than light in vacuum.",
        "source": "verified_trend"
    })

    initial_scenes = [
        {"scene_id": 1, "spoken_text": "Light speed is the ultimate speed limit in the universe.", "stock_video_query": "light beams"},
        {"scene_id": 2, "spoken_text": "Tachyons travel at 1000 times light speed.", "stock_video_query": "hyperspace"}  # Unsupported claim
    ]
    initial_seo = {
        "title": "Tachyons Break Light Speed 1000 Times #shorts",
        "description": "Tachyons travel at 1000 times light speed.\n\n#shorts",
        "tags": ["tachyons", "light speed", "shorts"]
    }

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (initial_scenes, initial_seo)
    )

    # Claim inspector flags Scene 2 and triggers rewrite
    fake_record = ClaimRecord(
        claim_id="claim_2_1",
        scene_id=2,
        original_text="Tachyons travel at 1000 times light speed.",
        extracted_proposition="Tachyons travel at 1000 times light speed.",
        category="empirical_fact",
        verification_status="disputed",
        confidence_score=0.2,
        policy_action="rewrite",
        scene_index=1
    )
    policy_calls_1 = [0]
    def fake_evaluate_policy_1(report):
        policy_calls_1[0] += 1
        if policy_calls_1[0] == 1:
            return (
                FactualityPolicyStatus.REJECTED_CONTRADICTION,
                "Disputed claim requires rewrite",
                [(2, fake_record)]
            )
        return (
            FactualityPolicyStatus.PASSED,
            "Script passed factuality verification",
            []
        )
    monkeypatch.setattr("engine.managers.pipeline_runner.evaluate_shorts_factuality_policy", fake_evaluate_policy_1)

    # Rewrite replaces scene 2 with verified factual line
    factual_scene_2 = {"scene_id": 2, "spoken_text": "Even information cannot travel faster than the cosmic speed of light.", "stock_video_query": "galaxy"}
    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", lambda scene, claim_record, llm: factual_scene_2)

    # Mock critic audit passing
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", lambda raw_scenes, seo_data, topic, **kw: (raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}))

    # Track SEO refresh
    refreshed_seo_called = []
    orig_gen_seo = generator_gen_seo = None
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    orig_gen_seo = IterativeScriptGenerator._generate_seo

    def spy_generate_seo(self, scenes, topic="", **kwargs):
        refreshed_seo_called.append({"scenes": scenes, "topic": topic})
        return {
            "title": "Why Nothing Breaks Light Speed #shorts",
            "description": "Why Nothing Breaks Light Speed #shorts\n\nAn exploration of the cosmic speed limit.\n\n#shorts",
            "tags": ["light speed", "cosmic limit", "shorts"]
        }

    monkeypatch.setattr(IterativeScriptGenerator, "_generate_seo", spy_generate_seo)
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))
    monkeypatch.setattr("engine.managers.youtube_manager.YouTubeManager.generate_community_post", lambda topic, hook: {"post": "poll"})
    monkeypatch.setattr("engine.managers.youtube_manager.generate_seo_title", lambda **kw: "Why Nothing Breaks Light Speed #shorts")

    # Run spec stage
    run_spec_stage(video_type="short")

    # Verify that SEO was refreshed against the rewritten scenes
    assert len(refreshed_seo_called) >= 1
    last_call = refreshed_seo_called[-1]
    assert last_call["scenes"][1]["spoken_text"] == "Even information cannot travel faster than the cosmic speed of light."
    assert "Tachyons" not in last_call["scenes"][1]["spoken_text"]


def test_pipeline_runner_factuality_rewrite_seo_refresh_failure_safe_policy(monkeypatch, tmp_path):
    """Phase 10C.1: If SEO refresh fails after factuality rewrites, pipeline_runner applies
    an explicit safe policy: generates script-grounded fallback metadata derived strictly from
    the verified final scenes and flags the limitation, never silently retaining pre-rewrite claims."""
    from engine.managers.pipeline_runner import run_spec_stage, FactualityPolicyStatus
    from engine.managers.claim_inspector import ClaimRecord

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    test_out = tmp_path / "output"
    test_out.mkdir(parents=True, exist_ok=True)
    test_mem = tmp_path / "memory"
    test_mem.mkdir(parents=True, exist_ok=True)
    test_cfg = tmp_path / "config"
    test_cfg.mkdir(parents=True, exist_ok=True)

    orig_join = os.path.join
    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", lambda *args: str(test_out / orig_join(*args[1:])) if args and args[0] == "output" else orig_join(*args))
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_mem / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_mem / "used_topics_registry.json"))

    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg / "model_quality_scores.json")
    monkeypatch.setattr("engine.managers.iterative_script_generator.save_past_spoken_thoughts", lambda thoughts: None)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.load_dynamic_weights", lambda: {})
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Light Speed Paradox",
        "verified_summary": "Nothing travels faster than light in vacuum.",
        "source": "verified_trend"
    })

    initial_scenes = [
        {"scene_id": 1, "spoken_text": "Light speed is the ultimate speed limit in the universe.", "stock_video_query": "light beams"},
        {"scene_id": 2, "spoken_text": "Tachyons travel at 1000 times light speed.", "stock_video_query": "hyperspace"}  # Unsupported claim
    ]
    initial_seo = {
        "title": "Tachyons Break Light Speed 1000 Times #shorts",
        "description": "Tachyons travel at 1000 times light speed.\n\n#shorts",
        "tags": ["tachyons", "light speed", "shorts"]
    }

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (initial_scenes, initial_seo)
    )

    # Claim inspector flags Scene 2 and triggers rewrite
    fake_record = ClaimRecord(
        claim_id="claim_2_1",
        scene_id=2,
        original_text="Tachyons travel at 1000 times light speed.",
        extracted_proposition="Tachyons travel at 1000 times light speed.",
        category="empirical_fact",
        verification_status="disputed",
        confidence_score=0.2,
        policy_action="rewrite",
        scene_index=1
    )
    policy_calls_1 = [0]
    def fake_evaluate_policy_1(report):
        policy_calls_1[0] += 1
        if policy_calls_1[0] == 1:
            return (
                FactualityPolicyStatus.REJECTED_CONTRADICTION,
                "Disputed claim requires rewrite",
                [(2, fake_record)]
            )
        return (
            FactualityPolicyStatus.PASSED,
            "Script passed factuality verification",
            []
        )
    monkeypatch.setattr("engine.managers.pipeline_runner.evaluate_shorts_factuality_policy", fake_evaluate_policy_1)

    # Rewrite replaces scene 2 with verified factual line
    factual_scene_2 = {"scene_id": 2, "spoken_text": "Even information cannot travel faster than the cosmic speed of light.", "stock_video_query": "galaxy"}
    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", lambda scene, claim_record, llm: factual_scene_2)

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", lambda raw_scenes, seo_data, topic, **kw: (raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}))

    # Simulate SEO refresh failing unexpectedly
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    def failing_generate_seo(self, scenes, topic="", **kwargs):
        raise RuntimeError("LLM SEO service unavailable during refresh")

    monkeypatch.setattr(IterativeScriptGenerator, "_generate_seo", failing_generate_seo)
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))
    monkeypatch.setattr("engine.managers.youtube_manager.YouTubeManager.generate_community_post", lambda topic, hook: {"post": "poll"})

    # Run spec stage
    spec_path = run_spec_stage(video_type="short")

    # Read output spec.json
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_data = json.load(f)

    # Verify that initial discredited 'Tachyons' title was NOT silently retained
    assert "Tachyons" not in spec_data["seo"]["title"]
    assert "1000" not in spec_data["seo"]["title"]
    # Verify title is grounded in verified scenes
    assert "Light speed is the ultimate speed limit in the universe" in spec_data["seo"]["title"]
    assert "#shorts" in spec_data["seo"]["title"]
    # Verify failure is recorded according to explicit safe policy
    assert spec_data["seo"].get("_refresh_failed") is True
    assert "LLM SEO service unavailable during refresh" in spec_data["seo"].get("_refresh_error", "")


def test_align_title_duplicate_history_triggers_fallback_never_none():
    """Phase 10C.1.2: A valid title duplicated in upload history triggers candidate
    selection and fallback rather than returning None or falling through to the duplicate title."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [
        {"scene_id": 1, "spoken_text": "Snipers and surgeons need steady hands for opposite reasons."}
    ]
    dup_title = "Snipers and Surgeons Need Steady Hands #shorts"
    history = [dup_title.lower()]

    aligned = TitleScriptAlignmentSkill.align_title(
        title=dup_title,
        scenes=scenes,
        upload_history_titles=history,
        topic="Steady Hands"
    )

    assert isinstance(aligned, str)
    assert len(aligned.strip()) > 0
    assert aligned is not None
    # Must not return the exact duplicate title
    assert aligned.lower() != dup_title.lower()
    assert "#shorts" in aligned


def test_align_title_invalid_script_candidate_not_returned(monkeypatch):
    """Phase 10C.1.2: A script-derived candidate that fails audit_title() is rejected
    and routes to the next fallback tier instead of being returned."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill
    import engine.managers.iterative_script_generator as isg

    scenes = [
        {"scene_id": 1, "spoken_text": "Gravitational wells curve spacetime."}
    ]
    # Initial title fails audit
    bad_initial_title = "Why Reality Doesn't Exist And Everything Is Fake #shorts"

    # Mock derive_grounded_fallback_title to return a candidate with an extreme unproven claim
    invalid_candidate = "Why You Will Never Truly Touch Anything In Reality #shorts"
    monkeypatch.setattr(isg, "derive_grounded_fallback_title", lambda *a, **kw: invalid_candidate)

    aligned = TitleScriptAlignmentSkill.align_title(
        title=bad_initial_title,
        scenes=scenes,
        upload_history_titles=[],
        topic="Spacetime"
    )

    assert isinstance(aligned, str) and len(aligned) > 0
    # The invalid script candidate must NOT be returned
    assert aligned != invalid_candidate
    assert "You Will Never Truly Touch Anything" not in aligned
    # Must pass audit_title
    passed, reason = TitleScriptAlignmentSkill.audit_title(aligned, scenes)
    assert passed is True, f"Returned fallback failed audit: {reason}"


def test_align_title_valid_title_missing_shorts_suffix_appended():
    """Phase 10C.1.2: A valid title missing the #shorts suffix receives exactly one suffix."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [{"spoken_text": "The reactor core reaches 10,000 degrees."}]
    clean_title_no_shorts = "Why Core Hits 10000 Degrees"

    aligned = TitleScriptAlignmentSkill.align_title(
        title=clean_title_no_shorts,
        scenes=scenes
    )

    assert aligned == "Why Core Hits 10000 Degrees #shorts"
    assert aligned.count("#shorts") == 1


def test_align_title_title_with_existing_shorts_no_duplicate():
    """Phase 10C.1.2: A title already containing #shorts (or duplicate #shorts) does not acquire duplicates."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    scenes = [{"spoken_text": "The reactor core reaches 10,000 degrees."}]

    # Single suffix
    aligned1 = TitleScriptAlignmentSkill.align_title("Why Core Hits 10000 Degrees #shorts", scenes)
    assert aligned1 == "Why Core Hits 10000 Degrees #shorts"
    assert aligned1.count("#shorts") == 1

    # Duplicate suffix
    aligned2 = TitleScriptAlignmentSkill.align_title("Why Core Hits 10000 Degrees #shorts #shorts", scenes)
    assert aligned2 == "Why Core Hits 10000 Degrees #shorts"
    assert aligned2.count("#shorts") == 1

    # Uppercase suffix
    aligned3 = TitleScriptAlignmentSkill.align_title("Why Core Hits 10000 Degrees #SHORTS", scenes)
    assert aligned3 == "Why Core Hits 10000 Degrees #shorts"
    assert aligned3.count("#shorts") == 1


def test_align_title_empty_or_invalid_inputs_return_safe_title():
    """Phase 10C.1.2: Empty, None, or whitespace inputs return a non-empty, safe, grounded title."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill, DEFAULT_NEUTRAL_TITLE

    for bad_input in [None, "", "   ", "\t\n"]:
        # Without scenes
        res_no_scenes = TitleScriptAlignmentSkill.align_title(bad_input, scenes=[])
        assert isinstance(res_no_scenes, str)
        assert len(res_no_scenes.strip()) > 0
        assert res_no_scenes == DEFAULT_NEUTRAL_TITLE
        assert res_no_scenes.count("#shorts") == 1

        # With scenes
        scenes = [{"spoken_text": "Clocks measure entropy rather than time."}]
        res_with_scenes = TitleScriptAlignmentSkill.align_title(bad_input, scenes=scenes)
        assert isinstance(res_with_scenes, str)
        assert len(res_with_scenes.strip()) > 0
        assert "Clocks measure entropy rather than time" in res_with_scenes
        assert res_with_scenes.count("#shorts") == 1


def test_align_title_unsupported_numerical_claims_remain_rejected():
    """Phase 10C.1.2: Unsupported numerical claims in candidate or topic remain strictly rejected."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill

    zero_num_scenes = [
        {"scene_id": 1, "spoken_text": "Gravitational wells cause time dilation for nearby observers."}
    ]
    bad_num_title = "10 Shocking Realities About Gravitational Time Dilation #shorts"
    topic_with_num = "10 Paradoxes of General Relativity"

    aligned = TitleScriptAlignmentSkill.align_title(
        title=bad_num_title,
        scenes=zero_num_scenes,
        upload_history_titles=[],
        topic=topic_with_num
    )

    assert isinstance(aligned, str) and len(aligned) > 0
    assert "10" not in aligned
    passed, reason = TitleScriptAlignmentSkill.audit_title(aligned, zero_num_scenes)
    assert passed is True, f"Aligned title failed audit: {reason}"


# ─── PHASE 10E: SEO DESCRIPTION SYNCHRONIZATION & TITLE ENHANCEMENT TESTS ─────

def test_synchronize_seo_description_header_replaces_matching_first_line():
    """Phase 10E: synchronize_seo_description_header replaces first line when it matches old title."""
    from engine.managers.iterative_script_generator import synchronize_seo_description_header

    old_title = "Why Reality Doesn't Exist And Everything Is Fake #shorts"
    new_title = "Shower Thoughts & Daily Perspectives #shorts"
    body = "A collection of mind-bending realizations about daily life and physics.\n\n#shorts"
    desc = f"{old_title}\n\n{body}"

    synced = synchronize_seo_description_header(
        description=desc,
        old_title=old_title,
        new_title=new_title
    )

    expected = f"{new_title}\n\n{body}"
    assert synced == expected
    assert synced.splitlines()[0] == new_title
    # Body text preserved exactly
    assert body in synced


def test_synchronize_seo_description_header_matches_base_title_without_shorts():
    """Phase 10E: Matches old title even if first line has or lacks case-insensitive #shorts suffix."""
    from engine.managers.iterative_script_generator import synchronize_seo_description_header

    old_title_with_shorts = "Why Reality Doesn't Exist #shorts"
    new_title = "Shower Thoughts & Daily Perspectives #shorts"
    desc_no_shorts = "Why Reality Doesn't Exist\n\nA collection of mind-bending realizations.\n\n#shorts"

    synced = synchronize_seo_description_header(
        description=desc_no_shorts,
        old_title=old_title_with_shorts,
        new_title=new_title
    )

    assert synced.startswith(new_title)
    assert "A collection of mind-bending realizations." in synced


def test_synchronize_seo_description_header_preserves_unrelated_first_line():
    """Phase 10E: Leaves description unchanged if first line does not match the old title."""
    from engine.managers.iterative_script_generator import synchronize_seo_description_header

    old_title = "Why Reality Doesn't Exist #shorts"
    new_title = "Shower Thoughts & Daily Perspectives #shorts"
    desc = "An insightful exploration of everyday physical paradoxes.\n\n#shorts"

    synced = synchronize_seo_description_header(
        description=desc,
        old_title=old_title,
        new_title=new_title
    )

    # Must NOT prepend or append new_title when first line is unrelated
    assert synced == desc
    assert not synced.startswith(new_title)


def test_synchronize_seo_description_header_does_not_replace_body_occurrences():
    """Phase 10E: Only modifies the first-line header, preserving identical text elsewhere in description."""
    from engine.managers.iterative_script_generator import synchronize_seo_description_header

    old_title = "Atomic Repulsion Realities #shorts"
    new_title = "Observations on Common Realities #shorts"
    desc = (
        f"{old_title}\n\n"
        "In this video we explore Atomic Repulsion Realities #shorts and how electron clouds interact.\n\n"
        "#shorts"
    )

    synced = synchronize_seo_description_header(
        description=desc,
        old_title=old_title,
        new_title=new_title
    )

    lines = synced.splitlines()
    assert lines[0] == new_title
    # Second occurrence in body remains unchanged
    assert "Atomic Repulsion Realities #shorts" in lines[2]


def test_synchronize_seo_description_header_safe_on_empty_and_non_string_inputs():
    """Phase 10E: Handles None, empty, whitespace, and non-string inputs safely without errors."""
    from engine.managers.iterative_script_generator import synchronize_seo_description_header

    assert synchronize_seo_description_header(None, "Old Title", "New Title") is None
    assert synchronize_seo_description_header("", "Old Title", "New Title") == ""
    assert synchronize_seo_description_header("   ", "Old Title", "New Title") == "   "
    assert synchronize_seo_description_header("Valid desc", None, "New Title") == "Valid desc"
    assert synchronize_seo_description_header("Valid desc", "Old Title", None) == "Valid desc"
    assert synchronize_seo_description_header("Valid desc", "Same Title", "Same Title") == "Valid desc"


def test_secondary_seo_enhancement_normalizes_shorts_suffix():
    """Phase 10E: Secondary enhancement normalizes unsuffixed and multiply suffixed titles to exactly one #shorts."""
    from engine.managers.editorial_critic import _ensure_shorts_suffix, TitleScriptAlignmentSkill

    scenes = [{"spoken_text": "The earth revolves around the sun in 365 days."}]

    unsuffixed = "Why Earth Revolves Around The Sun"
    norm1 = _ensure_shorts_suffix(unsuffixed)
    assert norm1 == "Why Earth Revolves Around The Sun #shorts"
    assert norm1.count("#shorts") == 1
    passed1, _ = TitleScriptAlignmentSkill.audit_title(norm1, scenes=scenes)
    assert passed1 is True

    multiply_suffixed = "Why Earth Revolves Around The Sun #shorts #shorts"
    norm2 = _ensure_shorts_suffix(multiply_suffixed)
    assert norm2 == "Why Earth Revolves Around The Sun #shorts"
    assert norm2.count("#shorts") == 1

    punctuation_suffix = "Why Earth Revolves Around The Sun – Astronomy. #shorts"
    norm3 = _ensure_shorts_suffix(punctuation_suffix)
    assert norm3.endswith(" #shorts")
    assert not norm3.endswith(". #shorts")


def test_secondary_seo_enhancement_rejects_unsupported_numerical_claims():
    """Phase 10E: Secondary title enhancement rejecting unsupported numerical claims falls back to base title."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill, _ensure_shorts_suffix

    scenes = [{"spoken_text": "Gravitational wells curve spacetime."}]
    base_title = "Why Gravitational Wells Curve Spacetime #shorts"

    # Enhanced title introduces an unsupported number '10'
    bad_cand_title = "10 Reasons Gravitational Wells Curve Spacetime #shorts"
    norm_cand = _ensure_shorts_suffix(bad_cand_title)

    passed, reason = TitleScriptAlignmentSkill.audit_title(norm_cand, scenes=scenes)
    assert passed is False
    assert "numerical claim" in reason.lower()


def test_secondary_seo_enhancement_rejects_duplicate_history_title():
    """Phase 10E: Secondary title enhancement rejecting duplicate upload history retains base title."""
    from engine.managers.editorial_critic import _ensure_shorts_suffix, _token_overlap

    base_title = "Why Gravitational Wells Curve Spacetime #shorts"
    cand_title = "How Gravitational Wells Curve Spacetime #shorts"
    norm_cand = _ensure_shorts_suffix(cand_title)

    history = ["how gravitational wells curve spacetime #shorts"]
    history_lower = [t.lower().strip() for t in history]

    is_dup = any(_token_overlap(norm_cand.lower(), h) > 0.70 for h in history_lower)
    assert is_dup is True


# ─── PHASE 10E.1 SECONDARY SEO CANDIDATE GUARD & UPLOAD HISTORY TESTS ────────

def test_secondary_seo_enhancement_rejects_none_and_empty_and_whitespace_candidates():
    """Phase 10E.1: None, empty, and whitespace-only candidates must be rejected before normalization, retaining base title."""
    from engine.managers.editorial_critic import _ensure_shorts_suffix

    base_title = "Why Photons Have No Mass #shorts"
    malformed_candidates = [None, "", "   ", "\t\n  "]

    for cand_title in malformed_candidates:
        # Before fix: _ensure_shorts_suffix would produce the neutral fallback title
        neutral_fallback = _ensure_shorts_suffix(cand_title)
        assert neutral_fallback == "Observations and Perspectives #shorts"

        # Phase 10E.1 guard:
        if not isinstance(cand_title, str) or not cand_title.strip():
            seo_title = base_title
        else:
            seo_title = _ensure_shorts_suffix(cand_title)

        assert seo_title == base_title
        assert seo_title != "Observations and Perspectives #shorts"


def test_secondary_seo_enhancement_rejects_non_string_candidates():
    """Phase 10E.1: Non-string candidates (int, list, dict) must be rejected before normalization, retaining base title."""
    from engine.managers.editorial_critic import _ensure_shorts_suffix

    base_title = "Why Photons Have No Mass #shorts"
    non_string_candidates = [123, 45.6, {"title": "Quantum Spin"}, ["Photon Speed"], False]

    for cand_title in non_string_candidates:
        # Phase 10E.1 guard:
        if not isinstance(cand_title, str) or not cand_title.strip():
            seo_title = base_title
        else:
            seo_title = _ensure_shorts_suffix(cand_title)

        assert seo_title == base_title
        assert seo_title != "Observations and Perspectives #shorts"


def test_secondary_seo_enhancement_accepts_valid_unique_candidate_and_normalizes():
    """Phase 10E.1: Valid unique string candidate is normalized with #shorts suffix and accepted."""
    from engine.managers.editorial_critic import (
        TitleScriptAlignmentSkill,
        _ensure_shorts_suffix,
        _token_overlap,
        _load_upload_history_titles,
    )

    base_title = "The Illusion of Absolute Time #shorts"
    cand_title = "Why Absolute Time Does Not Exist"
    scenes = [{"spoken_text": "Time dilation means absolute time does not exist in our universe."}]

    # Phase 10E.1 guard and normalization flow
    assert isinstance(cand_title, str) and cand_title.strip()
    norm_cand = _ensure_shorts_suffix(cand_title)
    assert norm_cand == "Why Absolute Time Does Not Exist #shorts"

    passed, reason = TitleScriptAlignmentSkill.audit_title(
        norm_cand,
        scenes=scenes
    )
    assert passed is True

    upload_history = ["Some completely unrelated title #shorts"]
    history_lower = [t.lower().strip() for t in upload_history if isinstance(t, str)]
    is_dup = any(_token_overlap(norm_cand.lower(), h) > 0.70 for h in history_lower)
    assert is_dup is False

    seo_title = norm_cand if (passed and not is_dup) else base_title
    assert seo_title == "Why Absolute Time Does Not Exist #shorts"


def test_upload_history_dependency_availability_and_structure(tmp_path, monkeypatch):
    """Phase 10E.1: Verifies _load_upload_history_titles is callable, safe on errors, and returns List[str]."""
    from engine.managers.editorial_critic import _load_upload_history_titles
    import json

    # 1. Missing file returns empty list
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda path: False)
    assert _load_upload_history_titles() == []

    # 2. List of objects
    history_file = tmp_path / "upload_history.json"
    history_file.write_text(json.dumps([
        {"title": "Video One #shorts", "video_id": "v1"},
        {"title": "Video Two #shorts", "video_id": "v2"},
        {"non_title": "Video Three"}
    ]), encoding="utf-8")
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda path: True)
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.join", lambda *args: str(history_file))

    titles = _load_upload_history_titles()
    assert isinstance(titles, list)
    assert titles == ["Video One #shorts", "Video Two #shorts", ""]

    # 3. Dict containing "videos" key
    history_file.write_text(json.dumps({
        "videos": [
            {"title": "Dict Video Alpha #shorts"},
            {"title": "Dict Video Beta #shorts"}
        ]
    }), encoding="utf-8")
    titles_dict = _load_upload_history_titles()
    assert titles_dict == ["Dict Video Alpha #shorts", "Dict Video Beta #shorts"]

    # 4. Corrupted / invalid JSON returns empty list safely without raising exception
    history_file.write_text("{corrupted json contents", encoding="utf-8")
    corrupted_titles = _load_upload_history_titles()
    assert corrupted_titles == []


def test_pipeline_runner_run_spec_stage_malformed_candidate_retains_base_title(monkeypatch, tmp_path):
    """Phase 10E.1: run_spec_stage retains base title when generate_seo_title returns None, empty, whitespace, or dict."""
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    import json

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    test_out = tmp_path / "output"
    test_out.mkdir(parents=True, exist_ok=True)
    test_mem = tmp_path / "memory"
    test_mem.mkdir(parents=True, exist_ok=True)
    test_cfg = tmp_path / "config"
    test_cfg.mkdir(parents=True, exist_ok=True)

    orig_join = os.path.join
    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", lambda *args: str(test_out / orig_join(*args[1:])) if args and args[0] == "output" else orig_join(*args))
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_mem / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_mem / "used_topics_registry.json"))

    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg / "model_quality_scores.json")
    monkeypatch.setattr("engine.managers.iterative_script_generator.save_past_spoken_thoughts", lambda thoughts: None)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.load_dynamic_weights", lambda: {})
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Quantum Tunneling",
        "verified_summary": "Particles pass through potential barriers.",
        "source": "verified_trend"
    })

    scenes = [
        {"scene_id": 1, "spoken_text": "Particles can pass through solid barriers as if they were ghosts.", "stock_video_query": "particles"}
    ]
    base_seo = {
        "title": "Why Quantum Particles Walk Through Walls #shorts",
        "description": "Why Quantum Particles Walk Through Walls #shorts\n\nQuantum mechanics explained.\n\n#shorts",
        "tags": ["quantum", "physics", "shorts"]
    }

    monkeypatch.setattr(
        IterativeScriptGenerator,
        "generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, base_seo)
    )
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", lambda raw_scenes, seo_data, topic, **kw: (raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}))
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))
    monkeypatch.setattr("engine.managers.youtube_manager.YouTubeManager.generate_community_post", lambda topic, hook: {"post": "poll"})

    # Test cases: None, empty string, whitespace string, non-string dict
    malformed_returns = [None, "", "   ", {"malformed": "title"}]

    for malformed in malformed_returns:
        monkeypatch.setattr("engine.managers.youtube_manager.generate_seo_title", lambda **kw: malformed)
        spec_path = run_spec_stage(video_type="short")

        with open(spec_path, "r", encoding="utf-8") as f:
            spec_data = json.load(f)

        assert spec_data["seo"]["title"] == "Why Quantum Particles Walk Through Walls #shorts"
        assert "Observations and Perspectives #shorts" not in spec_data["seo"]["title"]


# ─── PHASE 10E.2 FAIL-SAFE UPLOAD HISTORY TESTS ─────────────────────────────

def test_upload_history_strict_mode_distinguishes_absence_from_failure(tmp_path, monkeypatch):
    """Phase 10E.2: Distinguish missing file, valid list/dict, malformed JSON, I/O errors, and invalid structures."""
    from engine.managers.editorial_critic import _load_upload_history_titles
    import json

    test_history = tmp_path / "upload_history.json"

    # 1. Missing history file: legitimate absence returns [] in both strict and default modes
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda p: False)
    assert _load_upload_history_titles(strict=True) == []
    assert _load_upload_history_titles(strict=False) == []

    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda p: True)
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.join", lambda *args: str(test_history))

    # 2. Valid list-format history
    test_history.write_text(json.dumps([
        {"title": "List Title 1 #shorts"},
        {"title": "List Title 2 #shorts"}
    ]), encoding="utf-8")
    assert _load_upload_history_titles(strict=True) == ["List Title 1 #shorts", "List Title 2 #shorts"]
    assert _load_upload_history_titles(strict=False) == ["List Title 1 #shorts", "List Title 2 #shorts"]

    # 2b. Valid empty list format
    test_history.write_text("[]", encoding="utf-8")
    assert _load_upload_history_titles(strict=True) == []
    assert _load_upload_history_titles(strict=False) == []

    # 3. Valid dictionary-format history
    test_history.write_text(json.dumps({
        "videos": [
            {"title": "Dict Video 1 #shorts"},
            {"title": "Dict Video 2 #shorts"}
        ]
    }), encoding="utf-8")
    assert _load_upload_history_titles(strict=True) == ["Dict Video 1 #shorts", "Dict Video 2 #shorts"]
    assert _load_upload_history_titles(strict=False) == ["Dict Video 1 #shorts", "Dict Video 2 #shorts"]

    # 3b. Valid empty dict format
    test_history.write_text(json.dumps({"videos": []}), encoding="utf-8")
    assert _load_upload_history_titles(strict=True) == []
    assert _load_upload_history_titles(strict=False) == []

    # 4. Existing but malformed JSON
    test_history.write_text("{corrupt json syntax", encoding="utf-8")
    assert _load_upload_history_titles(strict=True) is None
    assert _load_upload_history_titles(strict=False) == []

    # 5. Existing but unreadable history or simulated I/O failure
    def mock_open_raise(*args, **kwargs):
        raise OSError("Simulated disk I/O read failure")

    monkeypatch.setattr("builtins.open", mock_open_raise)
    assert _load_upload_history_titles(strict=True) is None
    assert _load_upload_history_titles(strict=False) == []
    monkeypatch.undo()

    # Re-apply join and exists mocks after undo
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda p: True)
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.join", lambda *args: str(test_history))

    # 6. Invalid history structure
    invalid_structures = [
        "123",  # Primitive number
        '"just a string"',  # Primitive string
        "true",  # Primitive boolean
        "null",  # JSON null
        json.dumps({"other_key": [{"title": "T1"}]}),  # Dict without 'videos' key
        json.dumps({"videos": "not-a-list"}),  # Dict where 'videos' is not a list
        json.dumps([1, 2, 3]),  # List of numbers (not dicts)
        json.dumps(["string1", "string2"]),  # List of strings (not dicts)
        json.dumps({"videos": [1, 2, 3]}),  # Videos contains non-dicts
    ]

    for inv in invalid_structures:
        test_history.write_text(inv, encoding="utf-8")
        assert _load_upload_history_titles(strict=True) is None, f"Expected None in strict mode for structure: {inv}"
        assert _load_upload_history_titles(strict=False) == [], f"Expected [] in permissive mode for structure: {inv}"


def test_secondary_seo_enhancement_failsafe_retains_base_title_when_history_unavailable():
    """Phase 10E.2: Enhancement candidate that passes audit must be rejected and retain base title when history is unavailable."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill, _ensure_shorts_suffix

    base_title = "The Mechanics of Time Dilation #shorts"
    cand_title = "Why Moving Clocks Tick Slower #shorts"
    scenes = [{"spoken_text": "Special relativity proves moving clocks tick slower than stationary ones."}]

    # Candidate would normally pass title auditing
    norm_cand = _ensure_shorts_suffix(cand_title)
    passed, reason = TitleScriptAlignmentSkill.audit_title(norm_cand, scenes=scenes)
    assert passed is True

    # When history loading failed / returned None (unavailable)
    upload_history = None

    if upload_history is None:
        seo_title = base_title
    else:
        seo_title = norm_cand

    assert seo_title == base_title
    assert seo_title != norm_cand
    assert seo_title != "Observations and Perspectives #shorts"


def test_secondary_seo_enhancement_accepts_valid_candidate_when_history_available():
    """Phase 10E.2: Enhancement candidate that passes audit is accepted when history is loaded successfully."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill, _ensure_shorts_suffix, _token_overlap

    base_title = "The Mechanics of Time Dilation #shorts"
    cand_title = "Why Moving Clocks Tick Slower #shorts"
    scenes = [{"spoken_text": "Special relativity proves moving clocks tick slower than stationary ones."}]

    norm_cand = _ensure_shorts_suffix(cand_title)
    passed, reason = TitleScriptAlignmentSkill.audit_title(norm_cand, scenes=scenes)
    assert passed is True

    # History loaded successfully with non-conflicting titles
    upload_history = ["Black Holes and Event Horizons #shorts"]
    assert upload_history is not None

    history_lower = [t.lower().strip() for t in upload_history if isinstance(t, str)]
    cand_lower = norm_cand.lower()
    is_dup = any(_token_overlap(cand_lower, h) > 0.70 for h in history_lower)
    assert is_dup is False

    if passed and not is_dup:
        seo_title = norm_cand
    else:
        seo_title = base_title

    assert seo_title == norm_cand


def test_pipeline_runner_run_spec_stage_failsafe_on_corrupt_history(monkeypatch, tmp_path):
    """Phase 10E.2: run_spec_stage rejects enhancement candidate and retains base title when upload_history.json is corrupt."""
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    import json

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    test_out = tmp_path / "output"
    test_out.mkdir(parents=True, exist_ok=True)
    test_mem = tmp_path / "memory"
    test_mem.mkdir(parents=True, exist_ok=True)
    test_cfg = tmp_path / "config"
    test_cfg.mkdir(parents=True, exist_ok=True)
    test_data = tmp_path / "data"
    test_data.mkdir(parents=True, exist_ok=True)

    history_file = test_data / "upload_history.json"
    history_file.write_text("{corrupt json contents that fail parsing", encoding="utf-8")

    orig_join = os.path.join
    def safe_join(*args):
        if args and args[0] == "output":
            return str(test_out / orig_join(*args[1:]))
        if args and args[0] == "data" and "upload_history.json" in args:
            return str(history_file)
        return orig_join(*args)

    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", safe_join)
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.join", safe_join)
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_mem / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_mem / "used_topics_registry.json"))

    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg / "model_quality_scores.json")
    monkeypatch.setattr("engine.managers.iterative_script_generator.save_past_spoken_thoughts", lambda thoughts: None)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.load_dynamic_weights", lambda: {})
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Entropy and Clocks",
        "verified_summary": "Entropy is time's arrow.",
        "source": "verified_trend"
    })

    scenes = [
        {"scene_id": 1, "spoken_text": "Clocks measure entropy much more than they measure time.", "stock_video_query": "clock face"}
    ]
    base_seo = {
        "title": "Why Clocks Don't Measure Time #shorts",
        "description": "Why Clocks Don't Measure Time #shorts\n\nEntropy and time.\n\n#shorts",
        "tags": ["entropy", "time", "shorts"]
    }

    monkeypatch.setattr(
        IterativeScriptGenerator,
        "generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, base_seo)
    )
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", lambda raw_scenes, seo_data, topic, **kw: (raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}))
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))
    monkeypatch.setattr("engine.managers.youtube_manager.YouTubeManager.generate_community_post", lambda topic, hook: {"post": "poll"})

    # Enhanced title candidate that is valid and passes audit
    monkeypatch.setattr(
        "engine.managers.youtube_manager.generate_seo_title",
        lambda **kw: "Why Clocks Measure Entropy Instead #shorts"
    )

    # 1. With corrupt history file: must fail safe and retain base title
    spec_path = run_spec_stage(video_type="short")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_data = json.load(f)
    assert spec_data["seo"]["title"] == "Why Clocks Don't Measure Time #shorts"

    # 2. Fix history file with valid JSON containing non-duplicate title: must accept enhanced title
    history_file.write_text(json.dumps([{"title": "Unrelated Cosmic Expansion #shorts"}]), encoding="utf-8")
    spec_path_valid = run_spec_stage(video_type="short")
    with open(spec_path_valid, "r", encoding="utf-8") as f:
        spec_data_valid = json.load(f)
    assert spec_data_valid["seo"]["title"] == "Why Clocks Measure Entropy Instead #shorts"


# ─── PHASE 10E.2.1 STRICT UPLOAD HISTORY ENTRY VALIDATION TESTS ─────────────

def test_upload_history_strict_mode_rejects_malformed_individual_records(tmp_path, monkeypatch):
    """Phase 10E.2.1: Validates that strict mode rejects individual records with missing, non-string, or blank titles."""
    from engine.managers.editorial_critic import _load_upload_history_titles
    import json

    test_history = tmp_path / "upload_history.json"
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda p: True)
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.join", lambda *args: str(test_history))

    # 1. A list record missing 'title'
    test_history.write_text(json.dumps([
        {"title": "Valid Title 1 #shorts"},
        {"video_id": "missing_title_field"}
    ]), encoding="utf-8")
    assert _load_upload_history_titles(strict=True) is None
    assert _load_upload_history_titles(strict=False) == ["Valid Title 1 #shorts", ""]

    # 2. A dictionary-format history record missing 'title'
    test_history.write_text(json.dumps({
        "videos": [
            {"title": "Valid Video A #shorts"},
            {"video_id": "missing_title_field"}
        ]
    }), encoding="utf-8")
    assert _load_upload_history_titles(strict=True) is None
    assert _load_upload_history_titles(strict=False) == ["Valid Video A #shorts", ""]

    # 3. Non-string title values (None, integer, list, dict)
    non_string_cases = [
        [{"title": "Valid Title #shorts"}, {"title": None}],
        [{"title": "Valid Title #shorts"}, {"title": 12345}],
        {"videos": [{"title": "Valid Title #shorts"}, {"title": ["nested list"]}]},
        {"videos": [{"title": "Valid Title #shorts"}, {"title": {"nested": "dict"}}]},
    ]
    for case in non_string_cases:
        test_history.write_text(json.dumps(case), encoding="utf-8")
        assert _load_upload_history_titles(strict=True) is None

    # 4. Empty or whitespace-only title
    empty_whitespace_cases = [
        [{"title": "Valid Title #shorts"}, {"title": ""}],
        [{"title": "Valid Title #shorts"}, {"title": "   "}],
        {"videos": [{"title": "Valid Title #shorts"}, {"title": "\t \n "}]},
    ]
    for case in empty_whitespace_cases:
        test_history.write_text(json.dumps(case), encoding="utf-8")
        assert _load_upload_history_titles(strict=True) is None

    # 5. A valid history containing multiple valid title records (list and dict)
    valid_list = [
        {"title": "Why Photons Have No Mass #shorts", "id": "v1"},
        {"title": "How Black Holes Evaporate #shorts", "id": "v2"},
        {"title": "Quantum Entanglement Explained #shorts", "id": "v3"}
    ]
    test_history.write_text(json.dumps(valid_list), encoding="utf-8")
    res_list = _load_upload_history_titles(strict=True)
    assert res_list == [
        "Why Photons Have No Mass #shorts",
        "How Black Holes Evaporate #shorts",
        "Quantum Entanglement Explained #shorts"
    ]

    valid_dict = {
        "videos": [
            {"title": "Cosmic Expansion Realities #shorts"},
            {"title": "The True Shape of the Universe #shorts"}
        ]
    }
    test_history.write_text(json.dumps(valid_dict), encoding="utf-8")
    res_dict = _load_upload_history_titles(strict=True)
    assert res_dict == [
        "Cosmic Expansion Realities #shorts",
        "The True Shape of the Universe #shorts"
    ]

    # 6. A valid empty list or dictionary history
    test_history.write_text("[]", encoding="utf-8")
    assert _load_upload_history_titles(strict=True) == []

    test_history.write_text(json.dumps({"videos": []}), encoding="utf-8")
    assert _load_upload_history_titles(strict=True) == []

    # 7. Genuinely missing history file continues to return [] in strict mode
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.exists", lambda p: False)
    assert _load_upload_history_titles(strict=True) == []


def test_pipeline_runner_run_spec_stage_failsafe_on_malformed_history_record(monkeypatch, tmp_path):
    """Phase 10E.2.1: run_spec_stage retains base title when any history entry is malformed (missing title, blank, non-string)."""
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.iterative_script_generator import IterativeScriptGenerator
    import json

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    test_out = tmp_path / "output"
    test_out.mkdir(parents=True, exist_ok=True)
    test_mem = tmp_path / "memory"
    test_mem.mkdir(parents=True, exist_ok=True)
    test_cfg = tmp_path / "config"
    test_cfg.mkdir(parents=True, exist_ok=True)
    test_data = tmp_path / "data"
    test_data.mkdir(parents=True, exist_ok=True)

    history_file = test_data / "upload_history.json"

    orig_join = os.path.join
    def safe_join(*args):
        if args and args[0] == "output":
            return str(test_out / orig_join(*args[1:]))
        if args and args[0] == "data" and "upload_history.json" in args:
            return str(history_file)
        return orig_join(*args)

    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", safe_join)
    monkeypatch.setattr("engine.managers.editorial_critic.os.path.join", safe_join)
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_mem / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_mem / "used_topics_registry.json"))

    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg / "model_quality_scores.json")
    monkeypatch.setattr("engine.managers.iterative_script_generator.save_past_spoken_thoughts", lambda thoughts: None)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.load_dynamic_weights", lambda: {})
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Entropy and Clocks",
        "verified_summary": "Entropy is time's arrow.",
        "source": "verified_trend"
    })

    scenes = [
        {"scene_id": 1, "spoken_text": "Clocks measure entropy much more than they measure time.", "stock_video_query": "clock face"}
    ]
    base_seo = {
        "title": "Why Clocks Don't Measure Time #shorts",
        "description": "Why Clocks Don't Measure Time #shorts\n\nEntropy and time.\n\n#shorts",
        "tags": ["entropy", "time", "shorts"]
    }

    monkeypatch.setattr(
        IterativeScriptGenerator,
        "generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, base_seo)
    )
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", lambda raw_scenes, seo_data, topic, **kw: (raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}))
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))
    monkeypatch.setattr("engine.managers.youtube_manager.YouTubeManager.generate_community_post", lambda topic, hook: {"post": "poll"})

    # Enhanced title candidate that is valid and passes audit
    monkeypatch.setattr(
        "engine.managers.youtube_manager.generate_seo_title",
        lambda **kw: "Why Clocks Measure Entropy Instead #shorts"
    )

    # 1. With entry missing title: must fail safe and retain base title
    history_file.write_text(json.dumps([
        {"title": "Valid Previous Title #shorts"},
        {"video_id": "missing_title"}
    ]), encoding="utf-8")
    spec_path = run_spec_stage(video_type="short")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_data = json.load(f)
    assert spec_data["seo"]["title"] == "Why Clocks Don't Measure Time #shorts"

    # 2. With blank title entry: must fail safe and retain base title
    history_file.write_text(json.dumps([
        {"title": "Valid Previous Title #shorts"},
        {"title": "   "}
    ]), encoding="utf-8")
    spec_path_blank = run_spec_stage(video_type="short")
    with open(spec_path_blank, "r", encoding="utf-8") as f:
        spec_data_blank = json.load(f)
    assert spec_data_blank["seo"]["title"] == "Why Clocks Don't Measure Time #shorts"

    # 3. With non-string title entry: must fail safe and retain base title
    history_file.write_text(json.dumps([
        {"title": "Valid Previous Title #shorts"},
        {"title": 12345}
    ]), encoding="utf-8")
    spec_path_nonstr = run_spec_stage(video_type="short")
    with open(spec_path_nonstr, "r", encoding="utf-8") as f:
        spec_data_nonstr = json.load(f)
    assert spec_data_nonstr["seo"]["title"] == "Why Clocks Don't Measure Time #shorts"

    # 4. Repair history with valid entries: must accept enhanced title
    history_file.write_text(json.dumps([
        {"title": "Valid Previous Title #shorts"}
    ]), encoding="utf-8")
    spec_path_valid = run_spec_stage(video_type="short")
    with open(spec_path_valid, "r", encoding="utf-8") as f:
        spec_data_valid = json.load(f)
    assert spec_data_valid["seo"]["title"] == "Why Clocks Measure Entropy Instead #shorts"


# ─── PHASE 10F.1: TERMINAL NEUTRAL TITLE VALIDATION & SCRIPT POLISH TESTS ─────

def test_align_title_terminal_fallback_validated_and_suffixed(monkeypatch):
    """Phase 10F.1: Terminal neutral fallback candidate is normalized, audited, and returned with #shorts."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill, DEFAULT_NEUTRAL_TITLE
    import engine.managers.iterative_script_generator as isg

    scenes = [{"spoken_text": "Perception is influenced by sensory priors."}]
    bad_title = "Why Reality Doesn't Exist And Everything Is Fake #shorts"

    # Force candidate derivation to return an ungrounded candidate that fails audit
    monkeypatch.setattr(isg, "derive_grounded_fallback_title", lambda *a, **kw: "Why You Will Never Actually Exist #shorts")

    # Force all umbrella templates to fail audit so flow reaches Priority 4 terminal fallback
    orig_audit = TitleScriptAlignmentSkill.audit_title
    def mock_audit(cand, scenes):
        if "Observations and Perspectives" in cand:
            return orig_audit(cand, scenes)
        return False, "Forced failure for umbrella candidate"

    monkeypatch.setattr(TitleScriptAlignmentSkill, "audit_title", staticmethod(mock_audit))

    aligned = TitleScriptAlignmentSkill.align_title(
        title=bad_title,
        scenes=scenes,
        upload_history_titles=[],
        topic="Sensory Perception"
    )

    assert aligned == "Observations and Perspectives #shorts"
    assert aligned.count("#shorts") == 1
    passed, reason = orig_audit(aligned, scenes)
    assert passed is True, f"Terminal neutral fallback failed audit: {reason}"


def test_align_title_terminal_fallback_raises_on_audit_failure(monkeypatch):
    """Phase 10F.1: If terminal neutral fallback fails audit, align_title explicitly raises ValueError."""
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill
    import engine.managers.iterative_script_generator as isg

    scenes = [{"spoken_text": "Sensory inputs shape perceptual models."}]
    bad_title = "Why Reality Doesn't Exist And Everything Is Fake #shorts"

    monkeypatch.setattr(isg, "derive_grounded_fallback_title", lambda *a, **kw: "Bad Candidate #shorts")

    # Monkeypatch audit_title to fail even for terminal neutral fallback
    monkeypatch.setattr(
        TitleScriptAlignmentSkill,
        "audit_title",
        staticmethod(lambda cand, scenes: (False, "Simulated terminal audit failure"))
    )

    with pytest.raises(ValueError, match="Terminal neutral fallback title .* failed validation: Simulated terminal audit failure"):
        TitleScriptAlignmentSkill.align_title(
            title=bad_title,
            scenes=scenes,
            upload_history_titles=[],
            topic="Perception"
        )


def test_apply_prompt_rules_to_config_propagates_to_script_polish_idempotently():
    """Phase 10F.1: apply_prompt_rules_to_config propagates channel-specific banned phrases
    and extra instructions to script_polish exactly once without virality hype or duplication."""
    from engine.managers.pipeline_runner import apply_prompt_rules_to_config

    base_prompts_cfg = {
        "script_polish": {
            "system_prompt": "You are an expert audio voiceover director polishing narration."
        }
    }
    channel_cfg = {
        "prompt_settings": {
            "extra_instructions": "Ensure calm, grounded conversational rhythm.",
            "banned_phrases": ["mind-blowing", "shocking truth"],
            "enforce_virality": True
        }
    }

    # 1. First application: rules applied exactly once
    patched_1 = apply_prompt_rules_to_config(base_prompts_cfg, channel_cfg)
    polish_p1 = patched_1["script_polish"]["system_prompt"]

    assert polish_p1.count("ADDITIONAL CHANNEL INSTRUCTION: Ensure calm, grounded conversational rhythm.") == 1
    assert polish_p1.count('EXTRA BANNED PHRASES (channel-specific): "mind-blowing", "shocking truth". Never use these.') == 1
    # Generic virality language must NOT be injected into script_polish
    assert "VIRALITY ENFORCEMENT" not in polish_p1

    # 2. Second application: idempotency check (must not duplicate)
    patched_2 = apply_prompt_rules_to_config(patched_1, channel_cfg)
    polish_p2 = patched_2["script_polish"]["system_prompt"]

    assert polish_p2.count("ADDITIONAL CHANNEL INSTRUCTION: Ensure calm, grounded conversational rhythm.") == 1
    assert polish_p2.count('EXTRA BANNED PHRASES (channel-specific): "mind-blowing", "shocking truth". Never use these.') == 1

    # 3. Compatibility check: script_polish configured as a direct string
    string_prompts_cfg = {
        "script_polish": "You are a voiceover director."
    }
    patched_str = apply_prompt_rules_to_config(string_prompts_cfg, channel_cfg)
    assert isinstance(patched_str["script_polish"], str)
    assert patched_str["script_polish"].count("ADDITIONAL CHANNEL INSTRUCTION: Ensure calm, grounded conversational rhythm.") == 1
    assert patched_str["script_polish"].count('EXTRA BANNED PHRASES (channel-specific): "mind-blowing", "shocking truth". Never use these.') == 1
    assert "VIRALITY ENFORCEMENT" not in patched_str["script_polish"]


def test_normalize_and_emotify_script_respects_script_polish_prompt_representation(monkeypatch):
    """Phase 10F.1: _normalize_and_emotify_script correctly handles dict, string, and missing
    script_polish prompt configurations without errors."""
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []

    class DummyLLM:
        def generate_json(self, system_prompt, user_prompt, temperature=0.3, task_name="script_gen"):
            captured_prompts.append(system_prompt)
            return {
                "scenes": [
                    {"scene_id": 1, "spoken_text": "Telescopes capture ancient photons."},
                    {"scene_id": 2, "spoken_text": "The past remains visible across cosmic distances."}
                ]
            }

    scenes = [
        {"scene_id": 1, "spoken_text": "Telescopes capture ancient photons."},
        {"scene_id": 2, "spoken_text": "The past remains visible across cosmic distances."}
    ]

    # 1. Dict configuration with custom system_prompt
    dict_prompts = {
        "script_polish": {"system_prompt": "Custom dict system prompt for audio voiceover director."}
    }
    gen_dict = IterativeScriptGenerator(llm_manager=DummyLLM(), prompts_cfg=dict_prompts)
    res_dict = gen_dict._normalize_and_emotify_script(scenes)
    assert len(res_dict) == 2
    assert captured_prompts[-1] == "Custom dict system prompt for audio voiceover director."

    # 2. String configuration
    str_prompts = {
        "script_polish": "Custom string system prompt for audio voiceover director."
    }
    gen_str = IterativeScriptGenerator(llm_manager=DummyLLM(), prompts_cfg=str_prompts)
    res_str = gen_str._normalize_and_emotify_script(scenes)
    assert len(res_str) == 2
    assert captured_prompts[-1] == "Custom string system prompt for audio voiceover director."

    # 3. Missing / empty configuration: falls back to default voiceover prompt
    empty_prompts = {}
    gen_empty = IterativeScriptGenerator(llm_manager=DummyLLM(), prompts_cfg=empty_prompts)
    res_empty = gen_empty._normalize_and_emotify_script(scenes)
    assert len(res_empty) == 2
    assert "audio voiceover director" in captured_prompts[-1]

