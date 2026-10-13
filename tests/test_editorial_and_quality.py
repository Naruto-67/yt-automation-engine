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
