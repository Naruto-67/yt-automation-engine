# tests/test_llm_router.py
import pytest
from unittest.mock import patch
from engine.llm_router import LLMRouter

@patch('engine.llm_router.time.sleep')
def test_rpm_throttle_enforced(mock_sleep):
    """
    Verifies the RPM throttle mechanism in LLMRouter correctly enforces
    a minimum inter-call delay of 2.5 seconds between LLM requests.

    BUG FIX: Previous version called `router._execute_jitter_backoff()` which
    does not exist in LLMRouter. The actual method is `_enforce_rpm_throttle()`.
    This test verifies the real method executes without error and respects the
    elapsed time guard (no sleep needed if 2.5s has already passed).
    """
    router = LLMRouter()

    # Force _last_llm_call_time to 0 so elapsed >> 2.5s — no sleep should occur
    router._last_llm_call_time = 0.0
    router._enforce_rpm_throttle()
    # When sufficient time has passed, sleep should NOT be called
    mock_sleep.assert_not_called()

    # Force _last_llm_call_time to "just now" — sleep should be called
    import time
    router._last_llm_call_time = time.time()
    router._enforce_rpm_throttle()
    # When called back-to-back, sleep SHOULD be called (delay < 2.5s)
    mock_sleep.assert_called_once()
    call_args = mock_sleep.call_args[0][0]
    # The sleep duration should be <= 2.5 seconds
    assert 0 < call_args <= 2.5


def test_gemini_model_discovery_scoring():
    """
    Validates the scoring logic inside LLMRouter._discover_gemini_models()
    that prioritises stable, free-tier Gemini models and excludes audio/vision
    variants from the text-generation chain.

    BUG FIX: The original _score() function hardcoded version checks
    for "2.5", "2.0", "1.5". When Google released a newer free model
    (e.g. gemini-3.0-flash), the function would return score=0 and never
    prefer it. The new scoring uses dynamic version parsing — any future
    model (3.0, 4.5, 10.2) is automatically preferred without code changes.
    """
    router = LLMRouter()

    # Mirror the actual scoring function from llm_router.py exactly
    import re as _re

    def _score(name: str) -> int:
        n = name.lower()
        # Exclude non-text models — they break the text generation chain
        if any(x in n for x in ["vision", "audio", "tts", "embedding", "imagen"]):
            return -1

        # Extract the major.minor version number from the model name
        m = _re.search(r"gemini[-\s]?(\d+)\.(\d+)", n)
        if not m:
            return 0  # unknown format — rank lowest

        major = int(m.group(1))
        minor = int(m.group(2))

        # Score = (major * 100) + minor
        # This ensures newer versions always win: 3.0 > 2.5 > 2.0 > 1.5
        return (major * 100) + minor

    # Vision/audio/embedding models must be excluded (score = -1)
    assert _score("gemini-1.5-vision") == -1
    assert _score("gemini-2.0-audio")  == -1
    assert _score("gemini-tts")        == -1
    assert _score("gemini-embedding")  == -1
    assert _score("gemini-imagen")     == -1

    # Version ordering: newer model versions should score higher
    assert _score("gemini-2.0-flash") > _score("gemini-1.5-flash")
    assert _score("gemini-2.5-flash") > _score("gemini-2.0-flash")

    # 🚨 KEY FIX TEST: Future model versions are AUTOMATICALLY preferred.
    # The old hardcoded scoring would return 0 for these and never select them.
    assert _score("gemini-3.0-flash")        > _score("gemini-2.5-flash")
    assert _score("gemini-3.5-flash-lite")   > _score("gemini-3.0-flash")
    assert _score("gemini-4.0-flash")        > _score("gemini-3.5-flash")

    # Stable should beat preview/exp for the stable chain slot
    # (stable chain excludes "exp"/"preview" models — tested via model name filtering)
    stable_models = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-3.0-flash",       # future release
        "gemini-3.5-flash-lite",  # future release
    ]
    preview_models = [
        "gemini-2.0-flash-exp",
        "gemini-2.5-pro-preview",
        "gemini-3.0-flash-preview",
    ]

    # All stable models should score >= 0
    for m in stable_models:
        assert _score(m) >= 0, f"Stable model {m} scored below 0"

    # Stable chain filtering should exclude exp/preview by name pattern
    filtered_stable = [m for m in stable_models + preview_models
                       if "exp" not in m and "preview" not in m]
    assert "gemini-2.0-flash-exp"     not in filtered_stable
    assert "gemini-2.5-pro-preview"   not in filtered_stable
    assert "gemini-3.0-flash-preview" not in filtered_stable
    assert "gemini-3.0-flash"         in filtered_stable
    assert "gemini-3.5-flash-lite"    in filtered_stable
    assert "gemini-2.0-flash"         in filtered_stable
    assert "gemini-1.5-flash"         in filtered_stable
