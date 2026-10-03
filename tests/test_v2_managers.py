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
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["am_michael"] == "en-US-GuyNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["am_adam"] == "en-US-GuyNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["hf_alpha"] == "hi-IN-MadhurNeural"


def test_voice_normalizer_enforce_male_voice():
    """Verifies that female voice requests are strictly remapped to male voices."""
    assert VoiceNormalizer.enforce_male_voice("af_heart") == "am_adam"
    assert VoiceNormalizer.enforce_male_voice("af_bella") == "am_fenrir"
    assert VoiceNormalizer.enforce_male_voice("bf_emma") == "bm_george"
    assert VoiceNormalizer.enforce_male_voice("en-US-JennyNeural") == "en-US-GuyNeural"
    assert VoiceNormalizer.enforce_male_voice("en-US-AvaNeural") == "en-US-GuyNeural"
    assert VoiceNormalizer.enforce_male_voice("am_adam") == "am_adam"
    assert VoiceNormalizer.enforce_male_voice("en-US-GuyNeural") == "en-US-GuyNeural"


def test_music_manager_procedural_lofi_synthesis(tmp_path):
    """Verifies that MusicManager can synthesize high-fidelity procedural Lo-Fi tracks."""
    from engine.managers.music_manager import MusicManager
    out_file = str(tmp_path / "test_lofi.wav")
    path = MusicManager.synthesize_procedural_lofi(output_path=out_file, duration=2.0, mood="lofi_chill")
    assert path is not None
    assert os.path.exists(path)
    assert os.path.getsize(path) > 10000


def test_stock_video_manager_deduplication(tmp_path, monkeypatch):
    """Verifies that StockVideoManager avoids duplicate clips within a video and across past runs."""
    from engine.managers.stock_video_manager import StockVideoManager, SHORTS_ASMR_TAXONOMY
    
    # Use temporary registry file
    reg_file = str(tmp_path / "used_clips.json")
    monkeypatch.setattr(StockVideoManager, "REGISTRY_FILE", reg_file)

    mgr = StockVideoManager()
    
    # 1. Verify taxonomy is loaded with rich ASMR categories
    assert len(SHORTS_ASMR_TAXONOMY) >= 10
    assert any("soap" in q for q in SHORTS_ASMR_TAXONOMY)
    assert any("carpet" in q for q in SHORTS_ASMR_TAXONOMY)

    # 2. Record clip usage and verify cooldown check
    mgr.record_clip_usage("test_vid_123", "pexels", "soap carving")
    assert mgr.is_clip_recent("test_vid_123", cooldown_days=30) is True
    assert mgr.is_clip_recent("test_vid_999", cooldown_days=30) is False



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


def test_pipeline_runner_run_spec_stage(monkeypatch, tmp_path):
    """Verifies run_spec_stage runs end-to-end for short and long formats without NameError or crash."""
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    # Mock health checks and sync
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    # Mock LLM generation
    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why You See Everything Everywhere",
        "scenes": [
            {"scene_id": 1, "spoken_text": "This is why you suddenly notice things everywhere.", "stock_video_query": "subway train motion"},
            {"scene_id": 2, "spoken_text": "Your brain filters out background data.", "stock_video_query": "crowd walking"},
        ]
    }
    mock_seo_response = {
        "title": "Frequency Illusion #shorts",
        "description": "Why you see things everywhere. #shorts",
        "tags": ["psychology", "facts", "shorts"]
    }

    def mock_generate_json(self, sys_p, usr_p, temperature=0.7, *args, **kwargs):
        if "SEO Director" in sys_p:
            return mock_seo_response
        return mock_script_response

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_generate_json)
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))

    # Test short stage
    run_spec_stage(video_type="short")
    assert os.path.exists("output/spec.json")

    with open("output/spec.json", "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())
    assert spec.video_type == "short"
    assert len(spec.scenes) == 2

    # Test long stage
    run_spec_stage(video_type="long")
    assert os.path.exists("output/spec.json")

    with open("output/spec.json", "r", encoding="utf-8") as f:
        spec_long = SpecOutput.model_validate_json(f.read())
    assert spec_long.video_type == "long"
    assert spec_long.sub_format == "documentary_essay"


def test_voice_normalizer_strip_leading_dots():
    """Verifies that leading ellipses, dots, and hyphens are cleanly stripped to prevent audio pauses."""
    raw = "...and these shower thoughts will break your reality."
    normalized = VoiceNormalizer.normalize_text(raw)
    assert normalized.startswith("And")
    assert "..." not in normalized


def test_caption_aligner_vad_fallback(tmp_path):
    """Verifies CaptionAligner pure-Python acoustic VAD aligns words across audio soundwaves."""
    import wave
    import struct
    from engine.managers.caption_aligner import CaptionAligner

    test_wav = str(tmp_path / "test_voice.wav")
    sr = 16000
    # Create 2 seconds of dummy audio: 0.2s silence + 1.0s speech tone + 0.8s silence
    n_samples = int(sr * 2.0)
    samples = []
    for i in range(n_samples):
        t = i / sr
        if 0.2 <= t <= 1.2:
            import math
            s = int(10000 * math.sin(2 * math.pi * 440 * t))
        else:
            s = 0
        samples.append(s)

    with wave.open(test_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    script_text = "Your shadow is proof"
    words = CaptionAligner.align_captions(test_wav, script_text=script_text)

    assert len(words) == 4
    # The first word must start after the initial 0.2s silence
    assert words[0].start >= 0.15
    assert words[-1].end <= 1.5
    assert words[0].word == "Your"
    assert words[-1].word == "proof"


def test_topic_inspector_deduplication_anti_repetition(tmp_path, monkeypatch):
    """Verifies that TopicInspector prevents using duplicate or recently used topics."""
    reg_file = str(tmp_path / "test_used_topics.json")
    monkeypatch.setattr(TopicInspector, "REGISTRY_FILE", reg_file)

    # Initially empty
    assert TopicInspector.is_topic_recent("The Ship of Theseus Paradox") is False

    # Record usage
    TopicInspector.record_topic_usage("The Ship of Theseus Paradox and Identity", niche="shower_thoughts")

    # Exact or near-exact match must be blocked
    assert TopicInspector.is_topic_recent("The Ship of Theseus Paradox and Identity") is True

    # Conceptually similar / high keyword overlap must be blocked
    assert TopicInspector.is_topic_recent("The Ship of Theseus Paradox") is True

    # Completely different topic must pass
    assert TopicInspector.is_topic_recent("Why matter never truly touches other matter") is False


def test_caption_styling_settings():
    """Verifies settings.yaml has upgraded 108pt font size and 7px outline for high mobile retention."""
    import yaml
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    captions = cfg.get("captions", {})
    assert captions.get("font_size") == 108
    assert captions.get("outline_width") == 7
    assert captions.get("max_words_per_chunk") == 2
    assert captions.get("active_color") == "&H0000FFFF"


def test_stock_video_manager_registry_cooldown(tmp_path, monkeypatch):
    """Verifies that StockVideoManager records clip usage and enforces 30-day cooldown."""
    from engine.managers.stock_video_manager import StockVideoManager
    reg_file = str(tmp_path / "test_used_clips.json")
    monkeypatch.setattr(StockVideoManager, "REGISTRY_FILE", reg_file)

    # Initially empty
    assert StockVideoManager.is_clip_recent("vid_101") is False

    # Record clip
    StockVideoManager.record_clip_usage("vid_101", "pexels", "kinetic sand")

    # Clip is now recent
    assert StockVideoManager.is_clip_recent("vid_101") is True
    assert StockVideoManager.is_clip_recent("vid_999") is False


def test_scene_cut_boundaries_alignment(monkeypatch):
    """Verifies that scene cut boundaries align at sentence pause midpoints and sum to total_duration."""
    from engine.models import WordTimestamp
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    # Mock health checks and sync
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Mirror Self-Recognition Test",
        "verified_summary": "Animals recognizing themselves in mirrors",
        "source": "verified_trend"
    })

    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why Animals Don't Understand Mirrors",
        "scenes": [
            {"scene_id": 1, "spoken_text": "Look into a mirror and you see yourself.", "stock_video_query": "mirror reflection"},
            {"scene_id": 2, "spoken_text": "Most animals see a complete stranger.", "stock_video_query": "cat looking at mirror"},
        ]
    }
    mock_seo_response = {
        "title": "Mirrors #shorts",
        "description": "Mirrors and animals #shorts",
        "tags": ["psychology", "facts", "shorts"]
    }

    words = [
        WordTimestamp(word="Look", start=0.2, end=0.6),
        WordTimestamp(word="into", start=0.6, end=0.9),
        WordTimestamp(word="a", start=0.9, end=1.1),
        WordTimestamp(word="mirror", start=1.1, end=1.8),
        WordTimestamp(word="and", start=1.8, end=2.0),
        WordTimestamp(word="you", start=2.0, end=2.3),
        WordTimestamp(word="see", start=2.3, end=2.7),
        WordTimestamp(word="yourself.", start=2.7, end=3.4),  # Scene 1 ends at 3.4
        # Pause from 3.4 to 4.0
        WordTimestamp(word="Most", start=4.0, end=4.4),      # Scene 2 starts at 4.0
        WordTimestamp(word="animals", start=4.4, end=4.9),
        WordTimestamp(word="see", start=4.9, end=5.2),
        WordTimestamp(word="a", start=5.2, end=5.4),
        WordTimestamp(word="complete", start=5.4, end=5.9),
        WordTimestamp(word="stranger.", start=5.9, end=6.6),
    ]

    total_dur = 7.2

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json",
                        lambda self, sys_p, usr_p, *a, **k: mock_seo_response if "SEO Director" in sys_p else mock_script_response)
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync",
                        lambda **kw: (total_dur, words))

    run_spec_stage(video_type="short")

    with open("output/spec.json", "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    assert len(spec.scenes) == 2
    # Pause midpoint between 3.4 and 4.0 is 3.7
    # Scene 1 duration should be 3.7 - 0.0 = 3.7
    assert spec.scenes[0].duration_seconds == 3.7
    # Scene 2 duration should be 7.2 - 3.7 = 3.5
    assert spec.scenes[1].duration_seconds == 3.5
    # Total sum of durations must equal total_dur
    assert round(sum(s.duration_seconds for s in spec.scenes), 2) == total_dur






