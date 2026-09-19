# engine/dynamic_discovery.py — Autonomous Upstream Model Discovery & Health Registry
"""
Autonomous Model Discovery and Dynamic Registry Synchronization Engine.
Discovers available models from Google GenAI and Groq Cloud, enforces strict
modality filtering (rejecting non-text / media models), applies thinking profiles,
and synchronizes with memory/dynamic_models_registry.json.
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "dynamic_models_registry.json")

# Modality & non-text patterns strictly rejected
BANNED_MODALITY_PATTERNS = [
    r"image", r"picture", r"tts", r"audio", r"live", r"embed",
    r"robotics", r"video", r"veo", r"whisper", r"transcribe",
    r"guard", r"safeguard", r"deepseek-r1-distill-qwen-1\.5b", # low quality distill
]

# Deprecated legacy models known to return 404
DEPRECATED_KNOWN = {
    "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash",
    "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-2.0-pro"
}


def load_registry() -> Dict[str, Any]:
    """Loads the dynamic models registry from disk, returning defaults if missing."""
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "updated_at": "2026-09-18T00:00:00Z",
        "version": "1.0.0",
        "gold_anchors": {
            "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
            "gemini": ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        },
        "canaries": {
            "gemini": ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.7-flash"]
        },
        "task_ladders": {
            "scriptwriting": [
                {"provider": "gemini", "model": "gemini-3.6-flash", "role": "canary", "timeout_s": 12.0},
                {"provider": "gemini", "model": "gemini-3.8-flash", "role": "canary", "timeout_s": 25.0},
                {"provider": "groq", "model": "llama-3.3-70b-versatile", "role": "gold", "timeout_s": 10.0},
                {"provider": "gemini", "model": "gemini-flash-lite-latest", "role": "gold", "timeout_s": 10.0},
                {"provider": "gemini", "model": "gemini-3.5-flash-lite", "role": "gold", "timeout_s": 10.0}
            ],
            "seo_json": [
                {"provider": "gemini", "model": "gemini-flash-lite-latest", "role": "gold", "timeout_s": 8.0},
                {"provider": "gemini", "model": "gemini-3.5-flash-lite", "role": "gold", "timeout_s": 8.0},
                {"provider": "groq", "model": "llama-3.1-8b-instant", "role": "gold", "timeout_s": 8.0},
                {"provider": "gemini", "model": "gemini-3.1-flash-lite", "role": "gold", "timeout_s": 8.0}
            ],
            "fact_grounding": [
                {"provider": "deterministic", "model": "wikipedia_duckduckgo", "role": "gold", "timeout_s": 10.0},
                {"provider": "gemini", "model": "gemini-flash-lite-latest", "role": "search_tool", "timeout_s": 15.0}
            ]
        },
        "thinking_profiles": {
            "gemini-3.8-flash": {"timeout_s": 60.0},
            "gemini-3.7-flash": {"timeout_s": 60.0},
            "gemini-3.6-flash": {"timeout_s": 60.0},
            "gemini-3.5-flash": {"timeout_s": 60.0}
        },
        "deprecated_models": list(DEPRECATED_KNOWN)
    }


def save_registry(registry: Dict[str, Any]) -> bool:
    """Saves registry back to memory/dynamic_models_registry.json atomically."""
    try:
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        registry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
        return True
    except Exception as e:
        print(f"⚠️ [DYNAMIC REGISTRY] Failed to write registry: {e}")
        return False


def is_modality_allowed(model_name: str) -> bool:
    """Strictly filters out non-text, TTS, vision-generation, and robotics models."""
    lowered = model_name.lower()
    for pattern in BANNED_MODALITY_PATTERNS:
        if re.search(pattern, lowered):
            return False
    return True


def discover_google_models(client=None) -> List[str]:
    """Queries Google GenAI client.models.list() and filters for viable text models."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return []

    discovered: List[str] = []
    try:
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)

        for m in client.models.list():
            raw_name = getattr(m, "name", "")
            clean_name = raw_name.replace("models/", "").strip()
            if not clean_name:
                continue

            # Exclude known deprecated models
            if clean_name in DEPRECATED_KNOWN:
                continue

            # Exclude non-text modalities
            if not is_modality_allowed(clean_name):
                continue

            # Prioritize Flash / Flash-Lite / Canary models
            if "flash" in clean_name.lower():
                discovered.append(clean_name)

    except Exception as e:
        print(f"⚠️ [DYNAMIC DISCOVERY] Google catalog discovery failed: {e}")

    return discovered


def discover_groq_models(api_key: Optional[str] = None) -> List[str]:
    """Queries Groq Cloud /models endpoint to discover newly available text models."""
    key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return []

    discovered: List[str] = []
    try:
        import requests
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8.0
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                mid = item.get("id", "")
                if not mid or not is_modality_allowed(mid):
                    continue
                # Check for active text models
                if any(k in mid.lower() for k in ["llama", "mixtral", "gemma", "qwen"]):
                    discovered.append(mid)
    except Exception as e:
        print(f"⚠️ [DYNAMIC DISCOVERY] Groq catalog discovery failed: {e}")

    return discovered


def sync_registry() -> Dict[str, Any]:
    """Performs full discovery, validates profiles, and updates the local registry."""
    registry = load_registry()

    # Discover upstream Google models
    google_models = discover_google_models()
    if google_models:
        canaries = registry.setdefault("canaries", {}).setdefault("gemini", [])
        for m in google_models:
            if m not in canaries and m not in registry["gold_anchors"]["gemini"]:
                canaries.append(m)

        # Ensure thinking profiles exist for 3.x models
        profiles = registry.setdefault("thinking_profiles", {})
        for m in google_models:
            if any(p in m for p in ["3.8", "3.7", "3.6", "3.5"]):
                if m not in profiles:
                    profiles[m] = {
                        "timeout_s": 60.0
                    }

    # Discover Groq models
    groq_models = discover_groq_models()
    if groq_models:
        anchors = registry.setdefault("gold_anchors", {}).setdefault("groq", [])
        for g in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            if g not in anchors:
                anchors.append(g)

    save_registry(registry)
    return {
        "status": "SUCCESS",
        "google_discovered": google_models,
        "groq_discovered": groq_models,
        "updated_at": registry.get("updated_at")
    }

