# tests/test_quota_manager.py
import os
import pytest
from unittest.mock import patch, MagicMock
from scripts.quota_manager import MasterQuotaManager

@pytest.fixture
def mock_settings():
    return {
        "api_limits": {
            "gemini": 38,
            "cloudflare": 90,
            "huggingface": 45,
            "youtube": 9200
        }
    }

@pytest.fixture
def mock_db_state():
    return {
        "date": "2026-03-11",
        "channel_id": "GLOBAL",
        "youtube_points": 5000,
        "gemini_calls": 10,
        "cf_images": 20,
        "hf_images": 5
    }

@patch('scripts.quota_manager.config_manager.get_settings')
@patch('scripts.quota_manager.db.get_quota_state')
def test_quota_manager_initialization(mock_get_quota, mock_get_settings, mock_settings, mock_db_state):
    mock_get_settings.return_value = mock_settings
    mock_get_quota.return_value = mock_db_state
    
    qm = MasterQuotaManager()
    
    assert qm.LIMITS["gemini"] == 38
    assert qm.LIMITS["youtube"] == 9200

@patch('scripts.quota_manager.MasterQuotaManager._get_active_state')
def test_is_provider_exhausted(mock_active_state):
    qm = MasterQuotaManager()
    
    mock_active_state.return_value = {"gemini_calls": 38, "cf_images": 50, "hf_images": 10}
    assert qm.is_provider_exhausted("gemini") is True
    assert qm.is_provider_exhausted("cloudflare") is False

    mock_active_state.return_value = {"gemini_calls": 10, "cf_images": 50, "hf_images": 50}
    assert qm.is_provider_exhausted("huggingface") is True

@patch('scripts.quota_manager.TEST_MODE', False)
@patch('scripts.quota_manager.MasterQuotaManager._get_active_state')
def test_can_afford_youtube_transaction(mock_active_state):
    qm = MasterQuotaManager()
    
    mock_active_state.return_value = {"youtube_points": 8000}
    assert qm.can_afford_youtube(1000) is True
    assert qm.can_afford_youtube(1500) is False
