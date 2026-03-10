# tests/test_guardian.py
import pytest
from unittest.mock import patch
from engine.guardian import GhostGuardian

# Mock the quota manager state to test the Guardian's mathematical forecast
@pytest.fixture
def mock_quota_state():
    return {
        "youtube_points": 5000,   # 9200 limit - 5000 used = 4200 remaining
        "gemini_calls": 10,       # 38 limit - 10 used = 28 remaining
        "cf_images": 20           # 90 limit - 20 used = 70 remaining
    }

@patch('scripts.quota_manager.quota_manager._get_active_state')
def test_guardian_forecast_logic(mock_get_state, mock_quota_state):
    """
    Test that the Guardian correctly calculates the maximum number of videos
    the engine can produce based on the most constrained API limit.
    """
    mock_get_state.return_value = mock_quota_state
    
    guardian = GhostGuardian()
    
    # Override costs for predictable math
    guardian.COST_PER_VIDEO = {
        "youtube_points": 1600,
        "gemini_calls": 3,
        "image_calls": 7
    }
    
    forecast = guardian.get_run_forecast()
    
    # 4200 YT points remaining // 1600 per video = 2.62 (Floor = 2)
    # The guardian should identify YouTube as the bottleneck and return 2.
    assert forecast == 2

@patch('scripts.quota_manager.quota_manager._get_active_state')
def test_guardian_safe_mode_trigger(mock_get_state):
    """
    Test that Safe Mode correctly triggers when Cloudflare API usage
    exceeds the 85% threshold.
    """
    # Simulate 86 / 90 Cloudflare images used (95.5% usage)
    mock_get_state.return_value = {
        "youtube_points": 0,
        "gemini_calls": 0,
        "cf_images": 86 
    }
    
    guardian = GhostGuardian()
    
    # Should trigger safe mode for "GLOBAL"
    guardian.pre_flight_check()
    
    assert guardian.channel_health.get("GLOBAL", {}).get("safe_mode") is True
