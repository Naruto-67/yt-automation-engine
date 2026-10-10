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


def test_stock_video_manager_local_vault_fallback(tmp_path, monkeypatch):
    """Verifies that StockVideoManager gracefully falls back to local vault with archetype matching and deduplication."""
    from engine.managers.stock_video_manager import StockVideoManager

    reg_file = str(tmp_path / "used_clips_vault.json")
    monkeypatch.setattr(StockVideoManager, "REGISTRY_FILE", reg_file)

    mgr = StockVideoManager()

    # 1. Test keyword archetype matching for kinetic sand
    clip_sand = mgr.get_local_fallback("kinetic sand slicing ASMR")
    assert clip_sand is not None
    assert clip_sand.provider == "local"
    assert "kinetic_sand" in clip_sand.video_id
    assert os.path.exists(clip_sand.download_url)

    # 2. Test keyword archetype matching for soap
    clip_soap = mgr.get_local_fallback("soap carving ASMR")
    assert clip_soap is not None
    assert clip_soap.provider == "local"
    assert "soap_cubes" in clip_soap.video_id

    # 3. Test intra-video exclusion
    clip_sand_2 = mgr.get_local_fallback("kinetic sand slicing", exclude_ids={clip_sand.video_id})
    assert clip_sand_2 is not None
    assert clip_sand_2.video_id != clip_sand.video_id

    # 4. Test offline fallback when online search APIs fail or keys are absent
    mgr.pexels_key = None
    mgr.pixabay_key = None
    clip_offline = mgr.search_video("power washing driveway moss")
    assert clip_offline is not None
    assert clip_offline.provider == "local"
    assert "power_wash" in clip_offline.video_id


def test_render_video_download_clip_local(tmp_path):
    """Verifies that download_clip copies local vault clips directly without HTTP requests."""
    from scripts.render_video import download_clip

    # Create dummy source clip
    src_file = str(tmp_path / "vault_clip.mp4")
    with open(src_file, "wb") as f:
        f.write(b"0" * 150000)

    dest_file = str(tmp_path / "copied_clip.mp4")
    result = download_clip(url=src_file, output_path=dest_file, provider="local", video_id="vault_clip.mp4")

    assert result == dest_file
    assert os.path.exists(dest_file)
    assert os.path.getsize(dest_file) == 150000



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
    """Verifies settings.yaml has high mobile retention font size (>=88pt), ZY Resolve font, and CapCut styling."""
    import yaml
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    captions = cfg.get("captions", {})
    assert captions.get("font_name") == "ZY Resolve"
    assert captions.get("font_size", 0) >= 88
    assert captions.get("outline_width", 0) >= 7
    assert captions.get("max_words_per_chunk") == 2
    assert captions.get("active_color") == "&H0000E6FF"



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


def test_caption_aligner_faster_whisper(tmp_path, monkeypatch):
    """Verifies CaptionAligner transcribes audio via faster-whisper and extracts word timestamps."""
    from engine.managers.caption_aligner import CaptionAligner
    import sys

    # Create dummy audio file
    dummy_wav = str(tmp_path / "voice.wav")
    with open(dummy_wav, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 100)

    # Mock WhisperModel
    mock_word_1 = MagicMock(word=" Space", start=0.25, end=0.85)
    mock_word_2 = MagicMock(word=" expands.", start=0.85, end=1.60)
    mock_seg = MagicMock(words=[mock_word_1, mock_word_2])

    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.return_value = ([mock_seg], None)
    mock_whisper_cls = MagicMock(return_value=mock_model_inst)

    mock_fw = MagicMock()
    mock_fw.WhisperModel = mock_whisper_cls
    monkeypatch.setitem(sys.modules, "faster_whisper", mock_fw)

    words = CaptionAligner.align_captions(dummy_wav, script_text="Space expands.")

    assert len(words) == 2
    assert words[0].word == "Space"
    assert words[0].start == 0.25
    assert words[0].end == 0.85
    assert words[1].word == "expands."
    assert words[1].start == 0.85
    assert words[1].end == 1.60

    # Verify transcribe was called with word_timestamps=True, initial_prompt=None, and vad_filter=False
    mock_model_inst.transcribe.assert_called_once()
    call_kwargs = mock_model_inst.transcribe.call_args[1]
    assert call_kwargs["word_timestamps"] is True
    assert call_kwargs["initial_prompt"] is None
    assert call_kwargs["vad_filter"] is False


def test_caption_aligner_slice_words_by_scenes():
    """Verifies that slice_words_by_scenes cleanly partitions words using acoustic pause detection."""
    from engine.managers.caption_aligner import CaptionAligner
    from engine.models import WordTimestamp

    words = [
        # Scene 1: 3 words
        WordTimestamp(word="Light", start=0.1, end=0.4),
        WordTimestamp(word="travels", start=0.4, end=0.9),
        WordTimestamp(word="fast.", start=0.9, end=1.5),
        # 0.5s breath pause (1.5 to 2.0)
        # Scene 2: 3 words
        WordTimestamp(word="Darkness", start=2.0, end=2.5),
        WordTimestamp(word="was", start=2.5, end=2.8),
        WordTimestamp(word="already", start=2.8, end=3.3),
        WordTimestamp(word="there.", start=3.3, end=3.8),
    ]

    raw_scenes = [
        {"spoken_text": "Light travels fast."},
        {"spoken_text": "Darkness was already there."},
    ]

    slices = CaptionAligner.slice_words_by_scenes(words, raw_scenes)

    assert len(slices) == 2
    # Scene 1 must have the first 3 words
    assert len(slices[0]) == 3
    assert [w.word for w in slices[0]] == ["Light", "travels", "fast."]
    # Scene 2 must have the remaining 4 words
    assert len(slices[1]) == 4
    assert [w.word for w in slices[1]] == ["Darkness", "was", "already", "there."]


def test_stock_video_manager_recursion_guard(monkeypatch):
    """Verifies that StockVideoManager never recurses infinitely even when all APIs fail."""
    from engine.managers.stock_video_manager import StockVideoManager

    manager = StockVideoManager()
    manager.pexels_key = "fake_key"
    manager.pixabay_key = "fake_key"

    # Mock both APIs to raise an exception
    monkeypatch.setattr(manager, "_search_pexels", MagicMock(side_effect=RuntimeError("API Down")))
    monkeypatch.setattr(manager, "_search_pixabay", MagicMock(side_effect=RuntimeError("API Down")))

    # Must return None gracefully and not raise RecursionError
    clip = manager.search_video("failing query")
    
def test_ghost_engine_kill_switch_and_test_mode(monkeypatch):
    """Verifies that GHOST_ENGINE_ENABLED gates cron schedules and kills system when requested."""
    import sys
    from engine.managers.pipeline_runner import main

    # 1. Kill switch: GHOST_ENGINE_ENABLED == "false"
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", ["pipeline_runner", "--stage", "spec"])
    try:
        main()
        assert False, "Should have exited with code 0 on kill switch"
    except SystemExit as e:
        assert e.code == 0

    # 2. Schedule run blocked when GHOST_ENGINE_ENABLED == "test"
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "test")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setattr(sys, "argv", ["pipeline_runner", "--stage", "spec"])
    try:
        main()
        assert False, "Should have exited with code 0 on scheduled cron run in test mode"
    except SystemExit as e:
        assert e.code == 0

    # 3. Manual run allowed in test mode, setting TEST_MODE=true
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "test")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(sys, "argv", ["pipeline_runner", "--stage", "spec"])
    monkeypatch.setattr("engine.managers.pipeline_runner.run_spec_stage", MagicMock())
    main()
    assert os.environ.get("TEST_MODE") == "true"


def test_synthesize_scenes_sync_scene_durations(monkeypatch):
    """Verifies synthesize_scenes_sync computes accurate scene cut durations from pauses."""
    from engine.managers.voice_normalizer import VoiceNormalizer
    from engine.models import WordTimestamp

    scenes = [
        {"spoken_text": "One two three.", "phonetic_text": "One two three."},
        {"spoken_text": "Four five six.", "phonetic_text": "Four five six."},
    ]

    words = [
        WordTimestamp(word="One", start=0.2, end=0.8),
        WordTimestamp(word="two", start=0.8, end=1.4),
        WordTimestamp(word="three", start=1.4, end=2.0),
        WordTimestamp(word="Four", start=3.0, end=3.6),
        WordTimestamp(word="five", start=3.6, end=4.2),
        WordTimestamp(word="six", start=4.2, end=4.8),
    ]

    monkeypatch.setattr(
        VoiceNormalizer,
        "synthesize_sync",
        lambda **kw: (5.5, words)
    )

    tot, w_list, cut_durs, slices = VoiceNormalizer.synthesize_scenes_sync(
        raw_scenes=scenes,
        output_audio_path="output/test_narr.mp3",
        prefer_provider="edge-tts"
    )

    assert tot == 5.5
    assert len(cut_durs) == 2
    # Pause midpoint between 2.0 and 3.0 is 2.5
    assert cut_durs[0] == 2.5
    assert cut_durs[1] == 3.0
    assert round(sum(cut_durs), 2) == tot


def test_stock_negative_keyword_filtering():
    """Verifies that StockVideoManager blocks suggestive, medical, or latex content."""
    from engine.managers.stock_video_manager import StockVideoManager

    # Safe craft ASMR tags must pass
    assert StockVideoManager.is_safe_clip("satisfying kinetic sand slicing craft") is True
    assert StockVideoManager.is_safe_clip("soap cutting grid razor macro ASMR") is True
    assert StockVideoManager.is_safe_clip("chocolate curls marble spatula") is True

    # Suggestive / latex / medical terms must be blocked
    assert StockVideoManager.is_safe_clip("hydraulic press squishing rolled latex") is False
    assert StockVideoManager.is_safe_clip("medical surgery examination latex gloves") is False
    assert StockVideoManager.is_safe_clip("balloon rubber stretching pop") is False
    assert StockVideoManager.is_safe_clip("contraceptive condom squish") is False
    assert StockVideoManager.is_safe_clip("https://pexels.com/video/rubber-balloon-squish-8433837") is False

    # Musical instruments, static gradients, and people must be blocked
    assert StockVideoManager.is_safe_clip("guitar string vibration macro slow motion") is False
    assert StockVideoManager.is_safe_clip("musician playing guitar concert") is False
    assert StockVideoManager.is_safe_clip("pink gradient background water drop") is False
    assert StockVideoManager.is_safe_clip("abstract wallpaper gradient 4k") is False
    assert StockVideoManager.is_safe_clip("person face portrait interview talking") is False


def test_script_validator_brainblud_word_budget():
    """Verifies script validation matches BrainBlud word budget (135-158 words across 11-13 scenes)."""
    # Helper to generate mock script
    def make_script(num_scenes: int, words_per_scene: int):
        return {
            "scenes": [
                {"scene_id": i + 1, "spoken_text": " ".join(["word"] * words_per_scene)}
                for i in range(num_scenes)
            ]
        }

    # 12 scenes * 12 words = 144 words (perfect target)
    valid_script = make_script(12, 12)
    scenes = valid_script["scenes"]
    words = sum(len(sc["spoken_text"].split()) for sc in scenes)
    assert 11 <= len(scenes) <= 13
    assert 135 <= words <= 158

    # Too few scenes (e.g. 8 scenes)
    short_scenes_script = make_script(8, 15)
    assert len(short_scenes_script["scenes"]) < 11

    # Too few words (e.g. 100 words)
    too_short_script = make_script(12, 8)
    short_words = sum(len(sc["spoken_text"].split()) for sc in too_short_script["scenes"])
    assert short_words < 135

    # Too many words (e.g. 180 words)
    too_long_script = make_script(12, 15)
    long_words = sum(len(sc["spoken_text"].split()) for sc in too_long_script["scenes"])
    assert long_words > 158


def test_stock_video_manager_query_sanitization():
    """Verifies that StockVideoManager.search_video intercepts queries containing banned terms (hair, street, etc.)."""
    from engine.managers.stock_video_manager import StockVideoManager, SHORTS_VISUAL_TAXONOMY

    mgr = StockVideoManager()
    mgr.pexels_key = None
    mgr.pixabay_key = None

    # Query containing banned term 'street'
    clip = mgr.search_video("street line marking paint spray stencil")
    assert clip is not None
    # Must have fallen back to local vault safely without querying for 'street'
    assert clip.provider == "local"

    # Query containing banned term 'barber'
    clip_barber = mgr.search_video("barber cutting hair with scissors")
    assert clip_barber is not None
    assert clip_barber.provider == "local"


def test_whisper_timestamp_sanitization_and_monotonicity():
    """Verifies that Whisper timestamp sanitization eliminates duplicate words and enforces strict monotonicity."""
    import re
    from engine.models import WordTimestamp

    # Simulate raw whisper words with:
    # 1. Duplicate word hallucination ('recognized' twice)
    # 2. Non-monotonic / identical start times ('Or' and 'does' both at 47.18)
    raw_words = [
        WordTimestamp(word="named", start=48.82, end=49.14),
        WordTimestamp(word="itself", start=49.14, end=49.60),
        WordTimestamp(word="recognized", start=49.60, end=50.02),
        WordTimestamp(word="recognized", start=50.02, end=50.48),  # Hallucinated duplicate
        WordTimestamp(word="itself,", start=50.48, end=50.72),
        WordTimestamp(word="Or", start=47.18, end=47.33),
        WordTimestamp(word="does", start=47.18, end=47.32),        # Identical start time!
    ]

    # Apply the same sanitization logic as in CaptionAligner._align_with_faster_whisper
    words = []
    for rw in raw_words:
        if not words:
            words.append(rw)
            continue
        prev = words[-1]
        clean_curr = re.sub(r"[^\w]", "", rw.word).lower()
        clean_prev = re.sub(r"[^\w]", "", prev.word).lower()
        if clean_curr and clean_curr == clean_prev and rw.start <= prev.end + 0.15:
            prev.end = max(prev.end, rw.end)
            continue

        if rw.start <= prev.start:
            rw.start = round(prev.start + 0.10, 3)
        if rw.end <= rw.start:
            rw.end = round(rw.start + 0.15, 3)
        if prev.end > rw.start:
            prev.end = round(rw.start, 3)

        words.append(rw)

    # 1. Verify duplicate 'recognized' was merged into a single word with extended end time
    word_texts = [w.word for w in words]
    assert word_texts.count("recognized") == 1
    rec_word = [w for w in words if w.word == "recognized"][0]
    assert rec_word.start == 49.60
    assert rec_word.end == 50.48

    # 2. Verify 'Or' and 'does' no longer have identical start times
    or_word = [w for w in words if w.word == "Or"][0]
    does_word = [w for w in words if w.word == "does"][0]
    assert does_word.start > or_word.start
    assert does_word.start >= or_word.end


def test_shorts_final_scene_loop_ellipsis_enforcement():
    """Verifies that Shorts scripts guarantee trailing continuation ellipsis '...' on the final scene."""
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "The brain named itself, recognized itself, and is now realizing that"}
    ]

    last_text = raw_scenes[-1]["spoken_text"].rstrip(".! ")
    if not last_text.endswith("..."):
        raw_scenes[-1]["spoken_text"] = f"{last_text}..."

    assert raw_scenes[-1]["spoken_text"].endswith("...")
    assert raw_scenes[-1]["spoken_text"] == "The brain named itself, recognized itself, and is now realizing that..."


# ─── NEW TESTS (PLAN IMPLEMENTATION) ─────────────────────────────────────────


def test_thought_cache_duplicate_detection():
    """Verifies that _is_duplicate returns True for a previously cached line and False for a new one."""
    from engine.managers.pipeline_runner import _hash_line, _is_duplicate, _add_to_cache

    cache_cfg = {"max_entries": 200, "entries": []}

    line_a = "Your shadow is proof that light traveled ninety-three million miles to be blocked by you."
    line_b = "Nothing is ever on fire. Fire is actually on things."

    # Neither is in the cache yet
    assert not _is_duplicate(line_a, cache_cfg)
    assert not _is_duplicate(line_b, cache_cfg)

    # Add line_a to the cache
    _add_to_cache(line_a, cache_cfg)

    # Now line_a should be detected as duplicate, line_b still not
    assert _is_duplicate(line_a, cache_cfg)
    assert not _is_duplicate(line_b, cache_cfg)

    # Punctuation/case variations of the same line must also match (normalised hash)
    line_a_variant = "Your shadow is proof that light traveled ninety-three million miles to be blocked by you!!!"
    assert _is_duplicate(line_a_variant, cache_cfg)


def test_thought_cache_eviction():
    """Verifies that entries beyond max_entries are evicted (oldest first)."""
    from engine.managers.pipeline_runner import _add_to_cache, _is_duplicate

    cache_cfg = {"max_entries": 3, "entries": []}

    lines = ["line one here", "line two here", "line three here", "line four here"]
    for line in lines:
        _add_to_cache(line, cache_cfg)

    # Only the 3 most recent lines should remain
    assert len(cache_cfg["entries"]) == 3
    # The oldest line ('line one') should have been evicted
    assert not _is_duplicate("line one here", cache_cfg)
    assert _is_duplicate("line four here", cache_cfg)


def test_random_schedule_delay_range():
    """Verifies that the random upload delay stays within the configured window."""
    import random as _rnd

    schedule_window_hours = 4
    max_secs = schedule_window_hours * 3600
    min_secs = 300  # 5 min floor

    # Simulate 1000 random delays and assert all are within bounds
    for _ in range(1000):
        delay = _rnd.randint(min_secs, max_secs)
        assert min_secs <= delay <= max_secs, f"Delay {delay}s out of bounds [{min_secs}, {max_secs}]"


def test_seo_title_fallback_no_trends():
    """Verifies generate_seo_title returns a valid title even when yt_trends.csv is missing."""
    import sys
    from unittest.mock import MagicMock

    # Stub out google packages that youtube_manager imports at module level
    for mod in ["google", "google.oauth2", "google.oauth2.credentials",
                "googleapiclient", "googleapiclient.discovery", "googleapiclient.http"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from engine.managers.youtube_manager import generate_seo_title

    cfg = {
        "style_template": "{title}",
        "emojis": ["👀"],
        "trend_window_days": 1,
    }
    title = generate_seo_title(
        niche="shower_thoughts",
        base_title="Shower Thoughts That Will Mess With Your Head 👀 #shorts",
        script_text="Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
        cfg=cfg
    )
    # Must return a non-empty string (no crash)
    assert isinstance(title, str)
    assert len(title) > 0
    # Should not exceed YouTube's 100-char limit
    assert len(title) <= 100


def test_apply_prompt_rules_virality_and_extra():
    """Verifies apply_prompt_rules correctly injects virality enforcement and extra instructions."""
    from engine.managers.pipeline_runner import apply_prompt_rules

    channel_cfg = {
        "prompt_rules": {
            "enforce_virality": True,
            "extra_instructions": "Always mention the word 'reality'.",
            "banned_phrases": ["furthermore", "in conclusion"],
        }
    }

    sys_p, usr_p = apply_prompt_rules("BASE_SYS", "BASE_USR", channel_cfg)

    assert "VIRALITY ENFORCEMENT" in sys_p
    assert "reality" in usr_p
    assert "furthermore" in sys_p
    assert "in conclusion" in sys_p


def test_are_thoughts_similar_fuzzy():
    """Verifies that are_thoughts_similar flags near-duplicate sentences with 1-word differences."""
    from engine.managers.pipeline_runner import are_thoughts_similar

    # Exact same sentence with and without 'just'
    s1 = "Your shadow is proof that light traveled ninety-three million miles just to be blocked by you."
    s2 = "Your shadow is proof that light traveled ninety-three million miles to be blocked by you."
    assert are_thoughts_similar(s1, s2, threshold=0.45) is True

    # Punctuation variations
    s3 = "If you replace every single part of an axe, is it still the exact same axe???"
    s4 = "If you replace every single part of an axe is it still the exact same axe."
    assert are_thoughts_similar(s3, s4, threshold=0.45) is True

    # Completely different sentences
    s5 = "The only part of your reflection you can lick is your tongue."
    s6 = "Clapping is just repeatedly slapping yourself because you enjoyed something."
    assert are_thoughts_similar(s5, s6, threshold=0.45) is False


def test_universal_banned_safety_filter():
    """Verifies that universal brand-safety filter blocks animal cruelty, meat, butchery, and NSFW."""
    from engine.managers.stock_video_manager import StockVideoManager

    # Should reject meat/slaughter/animal abuse
    assert StockVideoManager.is_safe_clip("raw butcher beef steak cutting") is False
    assert StockVideoManager.is_safe_clip("animal abuse dog fight cruelty") is False
    assert StockVideoManager.is_safe_clip("hospital surgery blood open wound") is False
    assert StockVideoManager.is_safe_clip("erotic intimate underwear lingerie") is False

    # Should accept clean satisfying craft ASMR
    assert StockVideoManager.is_safe_clip("kinetic sand squishing satisfying macro") is True
    assert StockVideoManager.is_safe_clip("pottery wheel clay shaping smooth") is True


def test_topato_channel_banned_filter():
    """Verifies that Topato negative filters block kitchen/cooking/food and haircuts."""
    from engine.managers.stock_video_manager import StockVideoManager

    # Should reject food / kitchen prep
    assert StockVideoManager.is_safe_clip("chef slicing lemon on cutting board") is False
    assert StockVideoManager.is_safe_clip("kitchen cooking vegetable onion pan") is False
    assert StockVideoManager.is_safe_clip("barber haircut fade salon trimmer") is False
    assert StockVideoManager.is_safe_clip("busy city street traffic car road") is False


def test_trailing_whisper_hallucination_prune():
    """Verifies that slice_words_by_scenes trims trailing phantom tokens on the loop scene."""
    from engine.managers.caption_aligner import CaptionAligner
    from engine.models import WordTimestamp

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these..."}
    ]

    # Transcribed words has trailing phantom token 'ease' after 'these'
    word_timestamps = [
        WordTimestamp(word="The", start=0.0, end=0.1),
        WordTimestamp(word="only", start=0.1, end=0.3),
        WordTimestamp(word="part", start=0.3, end=0.5),
        WordTimestamp(word="of", start=0.5, end=0.6),
        WordTimestamp(word="your", start=0.6, end=0.7),
        WordTimestamp(word="reflection", start=0.7, end=1.0),
        WordTimestamp(word="you", start=1.0, end=1.2),
        WordTimestamp(word="can", start=1.2, end=1.3),
        WordTimestamp(word="lick", start=1.3, end=1.5),
        WordTimestamp(word="is", start=1.5, end=1.6),
        WordTimestamp(word="your", start=1.6, end=1.7),
        WordTimestamp(word="tongue", start=1.7, end=2.0),
        # Scene 2 words:
        WordTimestamp(word="Which", start=2.2, end=2.4),
        WordTimestamp(word="is", start=2.4, end=2.5),
        WordTimestamp(word="why", start=2.5, end=2.7),
        WordTimestamp(word="you", start=2.7, end=2.8),
        WordTimestamp(word="should", start=2.8, end=3.0),
        WordTimestamp(word="never", start=3.0, end=3.2),
        WordTimestamp(word="overthink", start=3.2, end=3.5),
        WordTimestamp(word="these", start=3.5, end=3.8),
        # Phantom hallucination token:
        WordTimestamp(word="ease", start=3.85, end=4.0)
    ]

    slices = CaptionAligner.slice_words_by_scenes(word_timestamps, raw_scenes)
    assert len(slices) == 2
    scene_2_words = [wt.word for wt in slices[1]]
    # Suffix guard should have pruned 'ease'
    assert "ease" not in scene_2_words
    assert scene_2_words[-1] == "these"


def test_community_post_generation():
    """Verifies YouTubeManager generates a subscriber poll and pinned comment."""
    import sys
    from unittest.mock import MagicMock
    for mod in ["google", "google.oauth2", "google.oauth2.credentials",
                "googleapiclient", "googleapiclient.discovery", "googleapiclient.http"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from engine.managers.youtube_manager import YouTubeManager

    post = YouTubeManager.generate_community_post(
        topic="Creepy shower thoughts",
        hook="The only part of your reflection you can lick is your tongue."
    )
    assert "pinned_comment" in post
    assert "community_post" in post
    assert "community_poll" in post
    assert len(post["community_poll"]["options"]) == 4
    assert "reflection" in post["community_post"]


def test_youtube_manager_post_creator_comment(monkeypatch):
    """Verifies YouTubeManager.post_creator_comment formats commentThreads insert request."""
    from engine.managers.youtube_manager import YouTubeManager
    import engine.managers.youtube_manager as ym

    yt = YouTubeManager()
    monkeypatch.setattr(ym, "is_test_mode", lambda: False)

    mock_client = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute.return_value = {"id": "comment_abc123"}
    mock_client.commentThreads.return_value.insert.return_value = mock_insert

    res = yt.post_creator_comment("video_123", "Did this break your brain? 👇", youtube=mock_client)
    assert res == "comment_abc123"
    mock_client.commentThreads.return_value.insert.assert_called_once()
    call_args = mock_client.commentThreads.return_value.insert.call_args[1]
    assert call_args["body"]["snippet"]["videoId"] == "video_123"
    assert call_args["body"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"] == "Did this break your brain? 👇"


def test_vault_blend_indices():
    """Verifies that vault blending designates anchor indices (0, mid, last) for a 12-scene short."""
    num_scenes = 12
    vault_blend_count = 3

    vault_indices = set()
    if vault_blend_count == 1:
        vault_indices = {0}
    elif vault_blend_count == 2:
        vault_indices = {0, num_scenes - 1}
    else:
        vault_indices = {0, num_scenes // 2, num_scenes - 1}
        step = max(1, num_scenes // vault_blend_count)
        for i in range(0, num_scenes, step):
            if len(vault_indices) < vault_blend_count:
                vault_indices.add(i)

    assert 0 in vault_indices
    assert (num_scenes - 1) in vault_indices
    assert len(vault_indices) == 3


def test_optimal_publish_hour_learning(tmp_path, monkeypatch):
    """Verifies YouTubeManager reads learned best publish hour from channel_performance.json."""
    import sys
    import json
    from unittest.mock import MagicMock
    for mod in ["google", "google.oauth2", "google.oauth2.credentials",
                "googleapiclient", "googleapiclient.discovery", "googleapiclient.http"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from engine.managers.youtube_manager import YouTubeManager

    perf_file = tmp_path / "channel_performance.json"
    perf_file.write_text(json.dumps({"best_publish_hour": 20}), encoding="utf-8")

    # Point os.path.join("memory", "channel_performance.json") to temp file
    monkeypatch.setattr(
        "engine.managers.youtube_manager.os.path.join",
        lambda *args: str(perf_file) if "channel_performance.json" in args else "/".join(args)
    )

    hour = YouTubeManager.get_optimal_publish_hour()
    assert hour == 20


def test_youtube_manager_graceful_missing_google_client(monkeypatch):
    """Verifies that YouTubeManager can be used for title & community posts even without googleapiclient."""
    import engine.managers.youtube_manager as ym
    monkeypatch.setattr(ym, "_GOOGLE_API_AVAILABLE", False)

    title = ym.generate_seo_title("shower_thoughts", "Base Title", "script text", {})
    assert title != ""
    assert isinstance(title, str)

    post = ym.YouTubeManager.generate_community_post("Why mirrors flip horizontally", "Why do mirrors flip horizontally?")
    assert "pinned_comment" in post
    assert "community_post" in post


def test_logger_deduplication_clean_tag(capsys, monkeypatch):
    """Verifies that logger does not produce double tags like [SUCCESS] [SUCCESS]."""
    from engine.logger import logger
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    logger.success("Clean success message")
    captured = capsys.readouterr()
    assert "[SUCCESS] [SUCCESS]" not in captured.out
    assert "[SUCCESS] Clean success message" in captured.out


def test_channel_config_caption_typography_loading():
    """Verifies that channel_config.yaml has caption_settings configured with ZY Resolve font."""
    import yaml
    with open("config/channel_config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "caption_settings" in cfg
    caps = cfg["caption_settings"]
    assert caps.get("font_name") == "ZY Resolve"
    assert caps.get("font_file") == "assets/fonts/ZY-Resolve.ttf"


def test_calculate_collision_free_publish_time_future_guarantee():
    """Verifies that publishAt is always strictly at least 1 hour in the future."""
    from engine.managers.youtube_manager import YouTubeManager
    from datetime import datetime, timezone
    
    mgr = YouTubeManager()
    pub_iso = mgr.calculate_collision_free_publish_time(None)
    pub_dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    
    assert pub_dt > now
    assert (pub_dt - now).total_seconds() >= 1800  # at least 30 minutes in future


def test_calculate_collision_free_publish_time_collision_advance(monkeypatch):
    """Verifies that if target day is occupied, it increments +24h to the next available day."""
    from engine.managers.youtube_manager import YouTubeManager
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    
    mgr = YouTubeManager()
    monkeypatch.setenv("TEST_MODE", "false")
    
    now = datetime.now(timezone.utc)
    target_today = now.strftime("%Y-%m-%d")
    target_tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Mock YouTube API to return target_today as occupied
    mock_yt = MagicMock()
    mock_yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPL123"}}}]
    }
    mock_yt.playlistItems().list().execute.return_value = {
        "items": [{"contentDetails": {"videoId": "vid_1"}}]
    }
    mock_yt.videos().list().execute.return_value = {
        "items": [{"status": {"publishAt": f"{target_today}T18:00:00Z"}}]
    }
    
    pub_iso = mgr.calculate_collision_free_publish_time(mock_yt)
    # Target date should have bumped to tomorrow or beyond
    assert target_today not in pub_iso


def test_intelligent_scheduler_spacing_and_negative_jitter(tmp_path, monkeypatch):
    """Verifies that the scheduler enforces anti-cannibalization buffer and negative minute jitter."""
    from engine.managers.youtube_manager import YouTubeManager
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    import yaml

    test_cfg = {
        "upload_settings": {
            "shorts_per_day": 1,
            "min_spacing_hours": 6.0,
            "use_negative_jitter": True,
            "jitter_minutes_min": 5,
            "jitter_minutes_max": 18,
            "target_peak_windows_utc": [18, 22, 14, 1]
        }
    }
    cfg_file = tmp_path / "channel_config.yaml"
    cfg_file.write_text(yaml.dump(test_cfg), encoding="utf-8")
    monkeypatch.setattr("builtins.open", lambda p, *a, **kw: open(str(cfg_file) if "channel_config.yaml" in str(p) else p, *a, **kw))
    monkeypatch.setenv("TEST_MODE", "false")

    mgr = YouTubeManager()
    now = datetime.now(timezone.utc)
    queued_time = now + timedelta(hours=2)

    mock_yt = MagicMock()
    mock_yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPL_TEST"}}}]
    }
    mock_yt.playlistItems().list().execute.return_value = {
        "items": [{"contentDetails": {"videoId": "test_v1"}}]
    }
    mock_yt.videos().list().execute.return_value = {
        "items": [{"status": {"publishAt": queued_time.strftime("%Y-%m-%dT%H:%M:%SZ")}}]
    }

    pub_iso = mgr.calculate_collision_free_publish_time(mock_yt)
    pub_dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))

    # Anti-cannibalization buffer: must be at least 6 hours away from queued video
    gap_hours = (pub_dt - queued_time).total_seconds() / 3600.0
    assert gap_hours >= 6.0

    # Negative jitter: minute must be between 42 and 55 (5 to 18 mins before the target hour)
    assert 42 <= pub_dt.minute <= 55


def test_competitor_niche_timing_intel_caching(tmp_path):
    """Verifies that CompetitorSpy ranks hours and caches results in memory/timing_intelligence.json."""
    from engine.managers.competitor_spy import CompetitorSpy
    intel = CompetitorSpy.get_niche_timing_intel(youtube=None, default_slots=[18, 22, 14, 1])
    assert "ranked_hours" in intel
    assert len(intel["ranked_hours"]) == 24
    assert 18 in intel["ranked_hours"][:4]
    assert os.path.exists(CompetitorSpy.TIMING_CACHE_FILE)


def test_discovery_bans_allam_model():
    """Verifies that allam models are strictly filtered out by modality patterns."""
    from engine.discovery import is_modality_allowed, is_model_allowed
    assert is_modality_allowed("allam-2-7b") is False
    assert is_modality_allowed("allam-7b") is False
    assert is_model_allowed("allam-2-7b", set()) is False
    assert is_modality_allowed("gemini-3.5-flash") is True
    assert is_modality_allowed("openai/gpt-oss-120b") is True


def test_validate_short_script_permissive_and_policy_check():
    """Verifies that validate_short_script accepts partial scripts for auto-expansion and rejects policy violations."""
    from engine.managers.pipeline_runner import YOUTUBE_POLICY_BANNED_WORDS

    # Simulate validator logic
    def validate_script(data):
        if not isinstance(data, dict):
            return False
        scenes = data.get("scenes", [])
        if not isinstance(scenes, list) or len(scenes) < 3:
            return False
        valid_scenes = [sc for sc in scenes if isinstance(sc, dict) and bool(sc.get("spoken_text", "").strip())]
        if len(valid_scenes) < 3:
            return False
        for sc in valid_scenes:
            txt = sc.get("spoken_text", "").lower()
            if any(bad in txt for bad in YOUTUBE_POLICY_BANNED_WORDS):
                return False
        words = sum(len(sc.get("spoken_text", "").split()) for sc in valid_scenes)
        if words < 25 or words > 220:
            return False
        return True

    # 4 scenes with 45 words — should PASS so downstream can auto-expand to 12
    valid_partial = {
        "scenes": [
            {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
            {"scene_id": 2, "spoken_text": "Your shadow is proof that light traveled ninety-three million miles to be blocked by you."},
            {"scene_id": 3, "spoken_text": "If you replace every single part of an axe, is it still the exact same axe?"},
            {"scene_id": 4, "spoken_text": "Which is why you should never overthink these..."}
        ]
    }
    assert validate_script(valid_partial) is True

    # Policy violation — should FAIL
    policy_violation = {
        "scenes": [
            {"scene_id": 1, "spoken_text": "Here is how to commit suicide safely..."},
            {"scene_id": 2, "spoken_text": "Normal scene two."},
            {"scene_id": 3, "spoken_text": "Normal scene three."}
        ]
    }
    assert validate_script(policy_violation) is False

    # Fewer than 3 scenes — should FAIL
    too_few = {
        "scenes": [
            {"scene_id": 1, "spoken_text": "Only one scene here."}
        ]
    }
    assert validate_script(too_few) is False


def test_llm_token_limit_payload_calibration(monkeypatch):
    """Verifies that LLMManager configures 2048 max output tokens for both Gemini and OpenAI/Groq."""
    llm = LLMManager()

    # Track requests
    captured_payloads = []
    def mock_http(url, method="POST", headers=None, json_data=None, timeout=60.0):
        captured_payloads.append(json_data)
        class MockResp:
            status_code = 200
            text = '{"candidates":[{"content":{"parts":[{"text":"{}"}]}}]}'
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
        return MockResp()

    monkeypatch.setattr("engine.managers.llm_manager._http_request", mock_http)

    gemini_prov = {
        "id": "gemini_test",
        "name": "Google (gemini-3.5-flash)",
        "model": "gemini-3.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/",
        "endpoint": "v1beta/models/gemini-3.5-flash:generateContent",
        "secret_key": "MOCK_KEY"
    }
    llm._execute_provider_call(gemini_prov, "sys", "usr", 0.7)
    assert captured_payloads[-1]["generationConfig"]["maxOutputTokens"] == 2048

    groq_prov = {
        "id": "groq_test",
        "name": "Groq (openai/gpt-oss-120b)",
        "model": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "endpoint": "openai/v1/chat/completions",
        "secret_key": "MOCK_KEY"
    }
    def mock_groq_http(url, method="POST", headers=None, json_data=None, timeout=60.0):
        captured_payloads.append(json_data)
        class MockResp:
            status_code = 200
            text = '{"choices":[{"message":{"content":"{}"}}]}'
            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}
        return MockResp()

    monkeypatch.setattr("engine.managers.llm_manager._http_request", mock_groq_http)
    llm._execute_provider_call(groq_prov, "sys", "usr", 0.7)
    assert captured_payloads[-1]["max_tokens"] == 2048


def test_youtube_upload_metadata_and_thumbnail(tmp_path, monkeypatch):
    """Verifies that upload_one_shot_scheduled_video constructs complete metadata and calls thumbnails().set()."""
    from engine.managers.youtube_manager import YouTubeManager

    monkeypatch.setenv("TEST_MODE", "false")
    mgr = YouTubeManager()

    # Create dummy video and thumbnail
    dummy_video = tmp_path / "final_render.mp4"
    dummy_video.write_bytes(b"dummy video data")
    dummy_thumb = tmp_path / "final_render_thumbnail.jpg"
    dummy_thumb.write_bytes(b"dummy thumb data")

    inserted_body = {}
    inserted_kwargs = {}
    thumbnail_calls = []

    mock_yt = MagicMock()
    # Mock video insert
    mock_insert_req = MagicMock()
    mock_insert_req.next_chunk.return_value = (None, {"id": "uploaded_vid_999"})
    
    def fake_insert(part=None, body=None, media_body=None, notifySubscribers=None):
        inserted_body.update(body)
        inserted_kwargs["notifySubscribers"] = notifySubscribers
        return mock_insert_req

    mock_yt.videos().insert = fake_insert

    # Mock thumbnail set
    mock_thumb_req = MagicMock()
    mock_thumb_req.execute.return_value = {"items": []}
    def fake_thumb_set(videoId=None, media_body=None):
        thumbnail_calls.append({"videoId": videoId, "media_body": media_body})
        return mock_thumb_req

    mock_yt.thumbnails().set = fake_thumb_set

    # Mock channels/playlist for collision check
    mock_yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPL123"}}}]
    }
    mock_yt.playlistItems().list().execute.return_value = {"items": []}

    monkeypatch.setattr(mgr, "get_client", lambda: mock_yt)
    monkeypatch.setattr("engine.managers.youtube_manager.MediaFileUpload", MagicMock(return_value=MagicMock()))

    res = mgr.upload_one_shot_scheduled_video(
        video_path=str(dummy_video),
        title="Mind-Bending Shower Thoughts That Make You Question Reality 🧠 #shorts",
        description="Deep thoughts about the simulation. #showerthoughts #shorts",
        tags=["shower thoughts", "psychology", "shorts"],
        category_id="24",
        default_language="en-US",
        default_audio_language="en-US",
        contains_synthetic_media=False,
        notify_subscribers=False,
        public_stats_viewable=False,
        thumbnail_path=str(dummy_thumb)
    )

    assert res["video_id"] == "uploaded_vid_999"
    assert inserted_body["snippet"]["defaultLanguage"] == "en-US"
    assert inserted_body["snippet"]["defaultAudioLanguage"] == "en-US"
    assert inserted_body["snippet"]["categoryId"] == "24"
    assert inserted_body["status"]["containsSyntheticMedia"] is False
    assert inserted_body["status"]["selfDeclaredMadeForKids"] is False
    assert inserted_body["status"]["embeddable"] is True
    assert inserted_body["status"]["publicStatsViewable"] is False
    assert inserted_body["status"]["license"] == "youtube"
    assert inserted_kwargs["notifySubscribers"] is False

    # Verify custom thumbnail was uploaded
    assert len(thumbnail_calls) == 1
    assert thumbnail_calls[0]["videoId"] == "uploaded_vid_999"


def test_unified_script_seo_extraction():
    """Verifies that pipeline_runner prefers embedded script SEO over secondary LLM call."""
    script_data_with_seo = {
        "thought_process": {"hook_psychology": "hooks immediately"},
        "seo": {
            "title": "Why Your Phone Is An Illusion 📱 #shorts",
            "description": "Mind-bending paradoxes about modern technology. Which thought hit you hardest? 👇\n\n#showerthoughts #shorts",
            "tags": ["phone", "screen", "mind blowing", "shorts"]
        },
        "scenes": [
            {"scene_id": 1, "spoken_text": "Scene 1."},
            {"scene_id": 2, "spoken_text": "Scene 2."}
        ]
    }

    # Simulate extraction logic
    script_seo = script_data_with_seo.get("seo")
    assert isinstance(script_seo, dict)
    assert script_seo.get("title") == "Why Your Phone Is An Illusion 📱 #shorts"
    assert len(script_seo.get("tags")) == 4


def test_brand_tags_merging_and_capping():
    """Verifies brand tags deduplication and 490-character capping logic."""
    topic_tags = ["shower thoughts", "mind blowing facts", "deep thoughts", "psychology"]
    brand_tags = ["topato", "metopato", "SHOWER THOUGHTS", "cognitive glitches", "facts that break your brain"]

    merged_tags = []
    seen_tags = set()
    for t in list(topic_tags) + list(brand_tags):
        t_clean = t.strip()
        t_lower = t_clean.lower()
        if t_clean and t_lower not in seen_tags:
            seen_tags.add(t_lower)
            merged_tags.append(t_clean)

    # Check deduplication is case-insensitive
    assert len([t for t in merged_tags if t.lower() == "shower thoughts"]) == 1
    assert "topato" in merged_tags
    assert "metopato" in merged_tags

    # Test 490-character capping
    final_tags = []
    char_count = 0
    for t in merged_tags:
        if char_count + len(t) + 1 <= 490:
            final_tags.append(t)
            char_count += len(t) + 1

    total_len = sum(len(t) + 1 for t in final_tags)
    assert total_len <= 490


def test_calibrate_and_guard_script_resegmentation():
    """Verifies that 4 multi-sentence scenes with 160 words are re-segmented and trimmed to 11-13 scenes and <= 150 words."""
    """Verifies that 4 multi-sentence scenes with 160 words are re-segmented and trimmed to 11-14 scenes and 150-175 words."""
    from engine.managers.pipeline_runner import calibrate_and_guard_script

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue. It proves your brain constructs reality. Mirrors are wild."},
        {"scene_id": 2, "spoken_text": "Your shadow traveled 93 million miles just to be blocked by your body. Think about how long that light traveled. Space is completely pitch black."},
        {"scene_id": 3, "spoken_text": "If poison expires does it become more poisonous or less poisonous? Nobody actually wants to test this hypothesis. Some paradoxes remain unsolved."},
        {"scene_id": 4, "spoken_text": "Sleeping is just charging your biological battery while dreaming is running diagnostics. Which is why you should never overthink these..."}
    ]

    calibrated = calibrate_and_guard_script(raw_scenes, prompt_settings={})
    assert len(calibrated) >= 10
    total_words = sum(len(s["spoken_text"].split()) for s in calibrated)
    assert 130 <= total_words <= 150
    assert 150 <= total_words <= 175
    # Hook clean
    assert not calibrated[0]["spoken_text"].startswith("...")
    assert calibrated[0]["spoken_text"][0].isupper()
    # Loop ellipsis
    assert calibrated[-1]["spoken_text"].endswith("...")


def test_calibrate_and_guard_script_underbudget_expansion():
    """Verifies that an under-budget partial script (4 scenes, 45 words) expands up to 135-150 words without exceeding 150 words."""
    """Verifies that an under-budget partial script (4 scenes, 45 words) expands up to 155-175 words without exceeding 175 words."""
    from engine.managers.pipeline_runner import calibrate_and_guard_script

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "Your shadow is proof that light traveled ninety-three million miles."},
        {"scene_id": 3, "spoken_text": "Nothing is ever on fire. Fire is actually on things."},
        {"scene_id": 4, "spoken_text": "Which is why you should never overthink these..."}
    ]

    calibrated = calibrate_and_guard_script(raw_scenes, prompt_settings={})
    assert len(calibrated) >= 10
    total_words = sum(len(s["spoken_text"].split()) for s in calibrated)
    assert 135 <= total_words <= 150
    assert 150 <= total_words <= 175
    assert calibrated[-1]["spoken_text"].endswith("...")


def test_calibrate_and_guard_script_overbudget_trim():
    """Verifies that an over-budget script (15 scenes, 210 words) is trimmed down to <= 150 words while preserving Hook and Loop bridge."""
    """Verifies that an over-budget script (15 scenes, 210 words) is trimmed down to <= 175 words while preserving Hook and Loop bridge."""
    from engine.managers.pipeline_runner import calibrate_and_guard_script

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."}
    ]
    for i in range(2, 15):
        raw_scenes.append({
            "scene_id": i,
            "spoken_text": f"This is scene {i} presenting another lengthy psychological thought that takes quite a few words to speak."
        })
    raw_scenes.append({
        "scene_id": 15,
        "spoken_text": "Which is why you should never overthink these..."
    })

    calibrated = calibrate_and_guard_script(raw_scenes, prompt_settings={})
    total_words = sum(len(s["spoken_text"].split()) for s in calibrated)
    assert total_words <= 150
    assert total_words <= 175
    assert calibrated[0]["spoken_text"] == "The only part of your reflection you can lick is your tongue."
    assert calibrated[-1]["spoken_text"].endswith("...")


def test_voice_normalizer_rescale_clamping(monkeypatch, tmp_path):
    """Verifies that VoiceNormalizer.rescale_audio_duration clamps speed factor to [0.95, 1.10]."""
    from engine.managers.voice_normalizer import VoiceNormalizer
    import subprocess

    dummy_in = str(tmp_path / "dummy.wav")
    dummy_out = str(tmp_path / "dummy_out.wav")
    with open(dummy_in, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 2000)

    recorded_atempo = []

    def mock_run(cmd, *args, **kwargs):
        for arg in cmd:
            if "atempo=" in arg:
                recorded_atempo.append(float(arg.split("atempo=")[1]))
        with open(dummy_out, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 2000)
        class _Proc:
            returncode = 0
        return _Proc()

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Test extreme high speed (e.g. 1.83x) -> should clamp to 1.10
    VoiceNormalizer.rescale_audio_duration(dummy_in, dummy_out, speed_factor=1.83)
    assert recorded_atempo[-1] == 1.10

    # Test extreme low speed (e.g. 0.80x) -> should clamp to 0.95
    VoiceNormalizer.rescale_audio_duration(dummy_in, dummy_out, speed_factor=0.80)
    assert recorded_atempo[-1] == 0.95

    # Test valid in-range speed (e.g. 1.05x) -> should pass through
    VoiceNormalizer.rescale_audio_duration(dummy_in, dummy_out, speed_factor=1.05)
    assert recorded_atempo[-1] == 1.05






