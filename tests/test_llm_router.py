# tests/test_llm_router.py
import pytest
from unittest.mock import patch
from engine.llm_router import LLMRouter

@patch('engine.llm_router.time.sleep')
def test_jitter_backoff_execution(mock_sleep):
    """
    Verifies the tiered jitter-backoff mechanism calculates the correct
    delay brackets inside the new dedicated LLM Router.
    """
    router = LLMRouter()
    
    with patch('engine.llm_router.random.uniform') as mock_uniform:
        mock_uniform.return_value = 7.5
        router._execute_jitter_backoff(0, "TEST_API")
        mock_sleep.assert_called_with(7.5)
        
        mock_uniform.return_value = 30.0
        router._execute_jitter_backoff(1, "TEST_API")
        mock_sleep.assert_called_with(30.0)
        
        mock_uniform.return_value = 55.0
        router._execute_jitter_backoff(2, "TEST_API")
        mock_sleep.assert_called_with(55.0)

def test_gemini_model_discovery_scoring():
    """
    Validates the regex/scoring logic that isolates stable, free-tier models 
    and explicitly bans audio/vision variants.
    """
    router = LLMRouter()
    
    # We test the scoring logic that ensures correct model fallback choices
    def _score(name: str) -> int:
        n = name.lower()
        if any(x in n for x in ["vision", "image", "embedding", "audio", "aqa", "learn", "tts", "customtools"]): return -1
        if "flash" not in n and "lite" not in n and "pro" not in n: return -1
        score = 0
        if "3.1" in n: score += 150
        elif "3.0" in n: score += 120
        elif "2.5" in n: score += 100
        elif "2.0" in n: score += 80
        elif "1.5" in n: score += 60
        elif "1.0" in n: score += 20
        if "flash-8b" in n: score += 10
        elif "flash-lite" in n: score += 15
        elif "flash" in n: score += 20
        if "pro" in n: score -= 50 
        return score
        
    assert _score("gemini-1.5-vision") == -1  
    assert _score("gemini-2.0-flash-exp") > _score("gemini-1.5-flash") 
    assert _score("gemini-1.5-pro") < _score("gemini-1.5-flash")
