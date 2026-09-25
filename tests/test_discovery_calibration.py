# tests/test_discovery_calibration.py — Tests for Modality Filtering, Alias Deduplication & Benchmark Calibration
import os
import sys
import json
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from engine.dynamic_discovery import (
    is_modality_allowed,
    deduplicate_google_aliases,
    calibrate_registry_from_benchmark,
    BANNED_MODALITY_PATTERNS
)
from engine.model_entity import DynamicQuotaTracker, ModelEntity


def test_banned_modality_patterns():
    """Verifies that non-text, audio, speech, TTS, and restricted agent models are strictly rejected."""
    # Banned modalities
    assert not is_modality_allowed("canopylabs/orpheus-v1-english")
    assert not is_modality_allowed("canopylabs/orpheus-arabic-saudi")
    assert not is_modality_allowed("openai/whisper-large-v3")
    assert not is_modality_allowed("meta/voice-synthesizer-1b")
    assert not is_modality_allowed("sound-generation-v2")
    assert not is_modality_allowed("thinkingmachines/inkling:free")
    assert not is_modality_allowed("thinkingmachines/inkling-small:free")
    assert not is_modality_allowed("google/veo-2-video-gen")
    assert not is_modality_allowed("stability/imagen-3-generate")

    # Allowed text LLM modalities
    assert is_modality_allowed("gemini-3.8-flash")
    assert is_modality_allowed("gemini-flash-lite-latest")
    assert is_modality_allowed("llama-3.3-70b-versatile")
    assert is_modality_allowed("openai/gpt-oss-120b")
    assert is_modality_allowed("qwen/qwen-2.5-72b-instruct:free")
    assert is_modality_allowed("dots-studio/dots-3-note-preview:free")


def test_google_alias_deduplication():
    """Verifies that generic '-latest' and duplicate '-preview' aliases are pruned to conserve 20 RPD free tier quotas."""
    candidates = [
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite-preview",
        "gemini-flash-lite-latest"
    ]
    deduped = deduplicate_google_aliases(candidates)

    # gemini-flash-latest should be dropped in favor of canonical gemini-3.8-flash
    assert "gemini-flash-latest" not in deduped
    assert "gemini-3.8-flash" in deduped
    assert "gemini-3.6-flash" in deduped

    # gemini-3.1-flash-lite-preview dropped because canonical gemini-3.1-flash-lite exists
    assert "gemini-3.1-flash-lite-preview" not in deduped
    assert "gemini-3.1-flash-lite" in deduped

    # Standalone workhorse latest kept
    assert "gemini-flash-lite-latest" in deduped


def test_benchmark_calibration_and_persistence(tmp_path):
    """Verifies that benchmark results accurately calibrate entity scores, throughput, and thinking metadata in registry."""
    reg_file = str(tmp_path / "test_models_registry.json")

    # Initialize empty registry
    with open(reg_file, "w", encoding="utf-8") as f:
        json.dump({"updated_at": "2026-01-01T00:00:00Z", "entities": {}}, f)

    # Monkeypatch REGISTRY_PATH for isolated test
    import engine.dynamic_discovery as dd
    orig_path = dd.REGISTRY_PATH
    dd.REGISTRY_PATH = reg_file

    try:
        mock_benchmark_results = [
            {
                "entity_id": "google:gemini-flash-lite-latest",
                "provider": "google",
                "ping": True,
                "script": True,
                "script_score": 8.75,
                "seo": True,
                "seo_score": 9.8,
                "latency": 1.45,
                "throughput": 185.0,
                "thinking": False,
                "thinking_type": "none",
                "thinking_tokens": 0
            },
            {
                "entity_id": "groq:openai/gpt-oss-120b",
                "provider": "groq",
                "ping": True,
                "script": True,
                "script_score": 9.1,
                "seo": True,
                "seo_score": 9.4,
                "latency": 3.2,
                "throughput": 420.0,
                "thinking": True,
                "thinking_type": "reasoning_content",
                "thinking_tokens": 705
            },
            {
                "entity_id": "google:gemini-3.8-flash",
                "provider": "google",
                "ping": False,
                "script": False,
                "script_score": 0.0,
                "seo": False,
                "seo_score": 0.0,
                "latency": 0.15,
                "throughput": 0.0,
                "thinking": False,
                "thinking_type": "none",
                "thinking_tokens": 0,
                "quota_exhausted": True
            }
        ]

        summary = calibrate_registry_from_benchmark(mock_benchmark_results)
        assert summary["status"] == "SUCCESS"
        assert summary["total_calibrated"] == 3

        # Read back persisted tracker from disk
        tracker = DynamicQuotaTracker(reg_file)

        # Check gemini-flash-lite-latest calibration
        e_lite = tracker.get_entity("google:gemini-flash-lite-latest")
        assert e_lite is not None
        assert e_lite.task_quality_scores["scriptwriting"] == 8.75
        assert e_lite.task_quality_scores["seo_json"] == 9.8
        assert e_lite.average_latency == 1.45
        assert e_lite.average_throughput == 185.0
        assert e_lite.status == "ACTIVE"

        # Check groq:openai/gpt-oss-120b calibration (with reasoning tokens)
        e_groq = tracker.get_entity("groq:openai/gpt-oss-120b")
        assert e_groq is not None
        assert e_groq.supports_thinking is True
        assert e_groq.thinking_type == "reasoning_content"
        assert e_groq.average_thinking_tokens == 705
        assert e_groq.average_throughput == 420.0

        # Check gemini-3.8-flash quota exhaustion
        e_flagship = tracker.get_entity("google:gemini-3.8-flash")
        assert e_flagship is not None
        assert e_flagship.status == "QUOTA_EXHAUSTED"

    finally:
        dd.REGISTRY_PATH = orig_path


if __name__ == "__main__":
    pytest.main(["-v", __file__])
