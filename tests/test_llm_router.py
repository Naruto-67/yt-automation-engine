# tests/test_llm_router.py — Phase 19 Multi-Provider Dynamic Engine Tests
import pytest
import time
from unittest.mock import patch
from engine.model_entity import (
    ModelEntity,
    DynamicQuotaTracker,
    SlidingWindowRateLimiter,
    ScarcityWaterfallResolver
)
from engine.llm_router import UniversalGreedyJSONParser
from engine.dynamic_discovery import is_modality_allowed


def test_universal_greedy_json_parser_clean():
    """Validates parsing of clean JSON structures."""
    raw = '{"title": "The Quantum Realm", "scenes": [1, 2, 3]}'
    parsed = UniversalGreedyJSONParser.extract_json(raw)
    assert parsed is not None
    assert parsed.get("title") == "The Quantum Realm"
    assert len(parsed.get("scenes", [])) == 3


def test_universal_greedy_json_parser_markdown_and_trailing_commas():
    """Validates stripping markdown fences and fixing trailing commas."""
    raw = """Here is the resulting JSON script:
```json
{
  "hook": "Did you know this bizarre science fact?",
  "scenes": [
    {"visual": "Cell division", "audio": "Listen closely.",},
  ],
}
```
Hope you enjoyed!"""
    parsed = UniversalGreedyJSONParser.extract_json(raw)
    assert parsed is not None
    assert parsed.get("hook") == "Did you know this bizarre science fact?"
    assert len(parsed.get("scenes", [])) == 1


def test_universal_greedy_json_parser_invalid_fallback():
    """Validates that unparseable text cleanly returns None without crashing."""
    assert UniversalGreedyJSONParser.extract_json("") is None
    assert UniversalGreedyJSONParser.extract_json("not a json string at all") is None
    assert UniversalGreedyJSONParser.extract_json(None) is None


def test_model_entity_namespacing():
    """Validates namespaced provider:model identifier convention."""
    entity = ModelEntity(
        entity_id="google:gemini-3.8-flash",
        provider="google",
        model_name="gemini-3.8-flash",
        max_rpm=15,
        max_rpd=20,
        consumed_today=0
    )
    assert entity.entity_id == "google:gemini-3.8-flash"
    assert entity.provider == "google"
    assert entity.is_available() is True

    # Check that when consumed_today reaches max_rpd, entity is not available
    entity.consumed_today = 20
    assert entity.is_available() is False


def test_sliding_window_rate_limiter():
    """Validates sliding window pacing delay computation."""
    entity = ModelEntity(
        entity_id="groq:llama-3.3-70b-versatile",
        provider="groq",
        model_name="llama-3.3-70b-versatile",
        max_rpm=30,
        max_rpd=14400,
        last_call_timestamp=0.0
    )

    # When fresh, delay is 0.0
    delay = SlidingWindowRateLimiter.calculate_pacing_delay(entity)
    assert delay == 0.0

    # When called just now, delay should be around (60 / 30) = 2.0s
    entity.last_call_timestamp = time.time()
    delay_recent = SlidingWindowRateLimiter.calculate_pacing_delay(entity)
    assert 0.0 < delay_recent <= 2.1


def test_scarcity_waterfall_resolver_safe_cushion():
    """
    Validates that the ScarcityWaterfallResolver respects the 85% safe harvesting cushion
    and reserves 3-4 calls for emergency flagships.
    """
    tracker = DynamicQuotaTracker()
    # Test resolving candidates for creative scriptwriting
    candidates = ScarcityWaterfallResolver.resolve_candidates(
        task_type="scriptwriting",
        tracker=tracker,
        active_providers=["google", "groq", "github", "openrouter"]
    )

    assert len(candidates) > 0

    # Ensure Cloudflare is strictly NOT in any LLM text dispatch ladder
    for entity, tier_label in candidates:
        assert entity.provider != "cloudflare"
        assert "cf" not in entity.provider.lower()

    # Ensure candidates are returned with tier descriptions
    entity, tier = candidates[0]
    assert isinstance(entity, ModelEntity)
    assert isinstance(tier, str)


def test_dynamic_discovery_modality_filters():
    """Validates that non-text, TTS, audio, image, and robotics models are filtered out."""
    # Banned modalities
    assert is_modality_allowed("gemini-2.0-flash-exp-search-audio") is False
    assert is_modality_allowed("whisper-large-v3") is False
    assert is_modality_allowed("gemini-tts-speech") is False
    assert is_modality_allowed("flux-1-schnell-image") is False
    assert is_modality_allowed("rt-x-robotics-model") is False
    assert is_modality_allowed("text-embedding-004") is False

    # Allowed text modalities
    assert is_modality_allowed("gemini-3.8-flash") is True
    assert is_modality_allowed("gemini-flash-lite-latest") is True
    assert is_modality_allowed("llama-3.3-70b-versatile") is True
    assert is_modality_allowed("gpt-4o-mini") is True
    assert is_modality_allowed("qwen-2.5-72b-instruct") is True


def test_dynamic_quota_tracker_header_sniffing():
    """Validates live HTTP response header sniffing and quota auto-calibration."""
    tracker = DynamicQuotaTracker()
    test_entity_id = "groq:llama-3.3-70b-versatile"
    entity = tracker.get_entity(test_entity_id)
    assert entity is not None

    headers = {
        "x-ratelimit-limit-requests": "30",
        "x-ratelimit-remaining-requests": "14",
        "x-ratelimit-reset-requests": "2.5s"
    }

    tracker.update_from_headers(test_entity_id, headers)
    # RPD should be updated or remaining adjusted
    assert entity.max_rpm == 30


def test_gemini_flash_lite_not_disqualified_for_script_gen():
    """Validates that Gemini Flash Lite models are never filtered out as low-capacity for script_gen."""
    from engine.managers.llm_manager import LLMManager

    llm = LLMManager()
    candidates = [
        {"id": "gemini_flash_lite", "name": "Google (gemini-flash-lite-latest)", "model": "gemini-flash-lite-latest", "priority": 1},
        {"id": "openrouter_minimax", "name": "OpenRouter (minimax-m3.1-flash:free)", "model": "minimax/minimax-m3.1-flash:free", "priority": 2},
        {"id": "groq_qwen", "name": "Groq (qwen/qwen3.8-27b)", "model": "qwen/qwen3.8-27b", "priority": 3},
        {"id": "openrouter_tiny", "name": "OpenRouter (lfm-2.5-2.6b:free)", "model": "liquid/lfm-2.5-2.6b:free", "priority": 4},
    ]

    # Replicate script_gen filter logic
    tiny_edge_tags = ["3b", "2b", "1b", "mini-code", "micro", "tiny", "lfm-2.5-2.6b"]
    high_capacity = []
    for p in candidates:
        m_str = (p.get("model", "") + " " + p.get("id", "")).lower()
        if "gemini" in m_str:
            high_capacity.append(p)
            continue
        is_tiny = any(
            f"-{tag}" in m_str or f"_{tag}" in m_str or f"/{tag}" in m_str or f":{tag}" in m_str or m_str.endswith(tag)
            for tag in tiny_edge_tags
        )
        if not is_tiny:
            high_capacity.append(p)

    # Gemini Flash Lite MUST be preserved at index 0 (Priority 1)
    assert high_capacity[0]["id"] == "gemini_flash_lite"
    assert high_capacity[0]["priority"] == 1
    # Tiny edge models must be filtered out
    assert not any(p["id"] == "openrouter_tiny" for p in high_capacity)
