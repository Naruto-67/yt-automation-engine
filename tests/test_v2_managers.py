# tests/test_v2_managers.py — Unit Tests for Engine v2.0 Modular Managers
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from engine.managers.health_manager import HealthManager
from engine.managers.voice_normalizer import VoiceNormalizer
from engine.managers.error_manager import ErrorManager, ErrorSeverity
from engine.managers.competitor_spy import CompetitorSpy
from engine.managers.topic_inspector import TopicInspector
from engine.managers.llm_manager import LLMManager


# ─── 1. HEALTH MANAGER TESTS ─────────────────────────────────────────────────

def test_health_manager_preflight_success(monkeypatch):
    """Verifies preflight checks pass when all required secrets are provided."""
    test_env = {
        "YOUTUBE_CLIENT_ID": "mock_yt_id",
        "YOUTUBE_CLIENT_SECRET": "mock_yt_secret",
        "YOUTUBE_REFRESH_TOKEN": "mock_yt_token",
        "DISCORD_WEBHOOK": "https://discord.com/api/webhooks/mock",
        "PEXELS_API_KEY": "mock_pexels",
        "PIXABAY_API_KEY": "mock_pixabay",
        "GROQ_API_KEY": "mock_groq",
    }
    for k, v in test_env.items():
        monkeypatch.setenv(k, v)

    ok, issues = HealthManager.run_preflight_checks()
    assert ok is True
    assert len(issues) == 0


def test_health_manager_preflight_missing_var(monkeypatch):
    """Verifies preflight checks fail gracefully if required vars are absent."""
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    ok, issues = HealthManager.run_preflight_checks()
    assert ok is False
    assert any("YOUTUBE_CLIENT_ID" in issue for issue in issues)


def test_health_manager_dynamic_weights_learning(tmp_path, monkeypatch):
    """Verifies that the self-learning loop adapts pacing and format weighting."""
    test_weights_file = str(tmp_path / "dynamic_weights.json")
    monkeypatch.setattr("engine.managers.health_manager.os.path.join", lambda *args: test_weights_file)

    initial_weights = HealthManager.load_dynamic_weights()
    assert "sub_formats" in initial_weights
    assert initial_weights["sub_formats"]["core_brainblud"] == 0.80

    # Simulate analytics where listicle outperforms core format by 15%
    analytics = {
        "listicle_avg_percentage_viewed": 0.85,
        "core_avg_percentage_viewed": 0.70,
        "retention_drop_timestamp": 12,  # Early drop triggers cut tightening
    }
    updated = HealthManager.update_self_learning_loop(analytics)
    assert updated["sub_formats"]["listicle"] > 0.20
    assert updated["pacing"]["cut_interval_seconds"] < 3.5


# ─── 2. VOICE NORMALIZER TESTS ───────────────────────────────────────────────

def test_voice_normalizer_symbol_and_abbreviation_expansion():
    """Verifies phonetic conversion of symbols, percentages, and currencies."""
    raw_text = "Scientists found 100% of the $500 reward was given to Dr. Smith vs Mr. Jones."
    normalized = VoiceNormalizer.normalize_text(raw_text)

    # % -> percent
    assert "percent" in normalized.lower()
    # $ -> dollars
    assert "dollars" in normalized.lower()
    # vs -> versus
    assert "versus" in normalized.lower()
    # Dr. -> Doctor
    assert "doctor" in normalized.lower()


def test_voice_normalizer_clean_spoken_flow():
    """Verifies unwanted markdown and extra whitespaces are stripped."""
    raw = "  **Attention!** Here is #1: *The Secret*.  "
    normalized = VoiceNormalizer.normalize_text(raw)
    assert "**" not in normalized
    assert "*" not in normalized
    assert "number 1" in normalized.lower()


def test_voice_normalizer_kokoro_voice_detection_and_fallback_mapping():
    """Verifies Kokoro language detection, voice identification, and Edge-TTS mapping."""
    assert VoiceNormalizer.detect_lang_code("af_heart") == "a"
    assert VoiceNormalizer.detect_lang_code("bf_emma") == "b"
    assert VoiceNormalizer.detect_lang_code("hf_alpha") == "h"
    assert VoiceNormalizer.detect_lang_code("ff_siwis") == "f"
    assert VoiceNormalizer.detect_lang_code("af_heart+af_bella") == "a"
    assert VoiceNormalizer.detect_lang_code("unknown") == "a"

    assert VoiceNormalizer.is_kokoro_voice("af_heart") is True
    assert VoiceNormalizer.is_kokoro_voice("af_bella") is True
    assert VoiceNormalizer.is_kokoro_voice("am_fenrir") is True
    assert VoiceNormalizer.is_kokoro_voice("en-US-ChristopherNeural") is False

    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["af_heart"] == "en-US-JennyNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["am_michael"] == "en-US-ChristopherNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["hf_alpha"] == "hi-IN-SwaraNeural"


def test_voice_normalizer_enforce_male_voice():
    """Verifies that female voice requests are strictly remapped to male voices."""
    assert VoiceNormalizer.enforce_male_voice("af_heart") == "am_michael"
    assert VoiceNormalizer.enforce_male_voice("af_bella") == "am_fenrir"
    assert VoiceNormalizer.enforce_male_voice("bf_emma") == "bm_george"
    assert VoiceNormalizer.enforce_male_voice("en-US-JennyNeural") == "en-US-ChristopherNeural"
    assert VoiceNormalizer.enforce_male_voice("en-US-AvaNeural") == "en-US-GuyNeural"
    assert VoiceNormalizer.enforce_male_voice("am_michael") == "am_michael"
    assert VoiceNormalizer.enforce_male_voice("en-US-ChristopherNeural") == "en-US-ChristopherNeural"


# ─── 3. ERROR MANAGER TESTS ──────────────────────────────────────────────────

def test_error_manager_triage_categories():
    """Verifies correct triage taxonomy for auth, quota, and transient network errors."""
    auth_err = Exception("Google Auth Error: 401 Unauthorized invalid_grant")
    quota_err = Exception("YouTube Data API: 403 quotaExceeded limit reached")
    rate_err = Exception("Groq API: 429 RateLimitError - tokens per minute")
    net_err = Exception("ConnectionResetError: Remote end closed connection without response")

    assert ErrorManager.triage_error(auth_err) == ErrorSeverity.FATAL_AUTH
    assert ErrorManager.triage_error(quota_err) == ErrorSeverity.FATAL_QUOTA
    assert ErrorManager.triage_error(rate_err) == ErrorSeverity.TRANSIENT_RETRY
    assert ErrorManager.triage_error(net_err) == ErrorSeverity.TRANSIENT_RETRY


def test_error_manager_exponential_backoff_calculation():
    """Verifies exponential backoff wait times increase predictably."""
    d0 = ErrorManager.compute_backoff_seconds(attempt=1, base_seconds=2)
    d1 = ErrorManager.compute_backoff_seconds(attempt=2, base_seconds=2)
    d2 = ErrorManager.compute_backoff_seconds(attempt=3, base_seconds=2)

    assert 2.0 <= d0 <= 3.5
    assert 4.0 <= d1 <= 6.0
    assert 8.0 <= d2 <= 11.0


# ─── 4. COMPETITOR SPY TESTS ─────────────────────────────────────────────────

def test_competitor_spy_viral_factor_calculation():
    """Verifies viral factor algorithm: (views / age_hours) / baseline_vph."""
    # 10,000 views in 10 hours = 1,000 VPH. If baseline is 200 VPH, viral factor = 5.0x
    factor = CompetitorSpy.calculate_viral_factor(views=10000, age_hours=10.0, baseline_vph=200.0)
    assert pytest.approx(factor, 0.1) == 5.0

    # Safe zero division handling
    safe_factor = CompetitorSpy.calculate_viral_factor(views=500, age_hours=0.0, baseline_vph=0.0)
    assert safe_factor >= 0.0


# ─── 5. TOPIC INSPECTOR TESTS ────────────────────────────────────────────────

def test_topic_inspector_factuality_filter():
    """Verifies hallucination/pseudoscience gate filters invalid claims."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "is_factual": True,
        "confidence": 0.95,
        "primary_source": "Nature Biology, 2023",
        "red_flags": []
    }
    inspector = TopicInspector(llm_manager=mock_llm)
    result = inspector.verify_factuality("Turritopsis dohrnii reverses its life cycle.")

    assert result["is_factual"] is True
    assert result["confidence"] == 0.95
    assert "Nature Biology" in result["primary_source"]


# ─── 6. LLM MANAGER RESILIENCY TESTS ─────────────────────────────────────────

def test_llm_manager_json_repair_and_extraction():
    """Verifies that LLMManager parses embedded JSON objects inside raw text."""
    raw_response = """
    Here is the requested script:
    ```json
    {
      "scenes": [
        {"spoken_text": "Did you know trees can communicate?", "stock_video_query": "forest time lapse"}
      ],
      "thought_process": "Hook selected for high curiosity."
    }
    ```
    """
    parsed = LLMManager.extract_json_payload(raw_response)
    assert isinstance(parsed, dict)
    assert "scenes" in parsed
    assert len(parsed["scenes"]) == 1
    assert parsed["scenes"][0]["stock_video_query"] == "forest time lapse"


def test_llm_manager_404_auto_banning_and_cascade(monkeypatch):
    """Verifies that when a primary model returns 404, it is auto-banned and cascades to secondary provider."""
    monkeypatch.setenv("GROQ_API_KEY", "mock_groq_key")
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")

    banned_mock = set()
    monkeypatch.setattr("engine.managers.llm_manager._load_banned_models", lambda: set(banned_mock))
    monkeypatch.setattr("engine.managers.llm_manager.add_banned_model", lambda m: banned_mock.add(m))

    manager = LLMManager()

    call_counts = {"primary": 0, "secondary": 0}

    def mock_execute(provider, system_prompt, user_prompt, temperature):
        prov_id = provider["id"]
        if "gemini" in prov_id:
            call_counts["primary"] += 1
            raise RuntimeError("Error code: 404 - {'error': {'message': 'The model gemini-3-flash-preview does not exist or you do not have access to it.', 'code': 'model_not_found'}}")
        elif "groq" in prov_id:
            call_counts["secondary"] += 1
            return json.dumps({
                "scenes": [{"spoken_text": "Brain blud dynamic cascade success", "stock_video_query": "neuroscience"}]
            })
        raise RuntimeError("Unexpected provider")

    monkeypatch.setattr(manager, "_execute_provider_call", mock_execute)

    result = manager.generate_json(system_prompt="Test sys", user_prompt="Test user")

    # Assert primary was called and failed with 404
    assert call_counts["primary"] >= 1
    # Assert cascade happened to secondary
    assert call_counts["secondary"] >= 1
    assert "scenes" in result
    assert result["scenes"][0]["stock_video_query"] == "neuroscience"

    # Verify that the 404 model was benched into banned models
    assert "gemini-3-flash-preview" in banned_mock


def test_discovery_banned_models_filtering():
    """Verifies that banned models and banned modalities are strictly rejected."""
    from engine.discovery import is_model_allowed, is_modality_allowed

    # Banned modalities
    assert is_modality_allowed("whisper-large-v3") is False
    assert is_modality_allowed("google/veo-2") is False
    assert is_modality_allowed("tts-voice-actor") is False

    # Banned models
    banned = {"gemini-2.0-flash", "llama-3.1-70b-versatile"}
    assert is_model_allowed("gemini-2.0-flash", banned) is False
    assert is_model_allowed("llama-3.1-70b-versatile", banned) is False
    assert is_model_allowed("gemini-3-flash-preview", banned) is True


