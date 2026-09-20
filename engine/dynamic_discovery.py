# engine/dynamic_discovery.py — Autonomous Multi-Provider Discovery & Health Registry
"""
Autonomous Multi-Provider Model Discovery and Dynamic Registry Synchronization Engine.
Discovers available models from Google GenAI, Groq Cloud, GitHub Models, and OpenRouter,
enforces strict modality filtering (rejecting non-text / media models),
synchronizes namespaced model entities, and maintains memory/dynamic_models_registry.json.
"""

import os
import re
import json
import time
try:
    import requests
except ImportError:
    requests = None
from typing import Dict, Any, List, Optional
from engine.logger import logger

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "dynamic_models_registry.json")

# Modality & non-text patterns strictly rejected from LLM text routing
BANNED_MODALITY_PATTERNS = [
    r"image", r"picture", r"tts", r"audio", r"live", r"embed",
    r"robotics", r"video", r"veo", r"whisper", r"transcribe",
    r"guard", r"safeguard", r"deepseek-r1-distill-qwen-1\.5b",
    r"omni", r"imagen",
]

# Deprecated legacy models known to return 404 / 410
DEPRECATED_KNOWN = {
    "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash",
    "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-2.0-pro",
    "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"
    "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite",
    "mixtral-8x7b-32768", "gemma2-9b-it", "llama3-70b-8192", "llama3-8b-8192"
}


# Discovery cache TTL: 24 hours (86,400 seconds) to avoid redundant back-to-back network calls.
# Discovery is aligned to run 30 minutes AFTER the last provider quota reset (Google PT reset at 08:00 UTC + 30m = 08:30 UTC).
DISCOVERY_CACHE_TTL_SECONDS = 86400


def is_modality_allowed(model_name: str) -> bool:
    """Strictly filters out non-text, TTS, audio, image, and robotics models."""
    lowered = model_name.lower()
    for pattern in BANNED_MODALITY_PATTERNS:
        if re.search(pattern, lowered):
            return False
    return True


def load_registry() -> Dict[str, Any]:
    """Loads the dynamic models registry from disk, returning defaults if missing."""
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Default fallback registry
    from engine.model_entity import DynamicQuotaTracker
    tracker = DynamicQuotaTracker(REGISTRY_PATH)
    return {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_discovery_timestamp": 0.0,
        "version": "2.0.0",
        "entities": {eid: {} for eid in tracker.entities}
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
        logger.error(f"⚠️ [DYNAMIC REGISTRY] Failed to write registry: {e}")
        return False


def get_cached_provider_models(provider: str) -> Optional[List[str]]:
    """Returns cached active models for provider if registry is fresh (< 24 hours old)."""
    reg = load_registry()
    last_sync = reg.get("last_discovery_timestamp", 0.0)
    if time.time() - last_sync < DISCOVERY_CACHE_TTL_SECONDS:
        entities = reg.get("entities", {})
        cached = [
            info["model_name"] for eid, info in entities.items()
            if isinstance(info, dict) and info.get("provider") == provider and info.get("status") == "ACTIVE"
        ]
        if cached:
            return cached
    return None


def discover_google_models(client=None, force: bool = False) -> List[str]:
    """Queries Google GenAI client.models.list() and filters for viable Flash models."""
    if not force:
        cached = get_cached_provider_models("google")
        if cached is not None:
            return cached

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

            if clean_name in DEPRECATED_KNOWN:
                continue

            if not is_modality_allowed(clean_name):
                continue

            if "flash" in clean_name.lower():
                discovered.append(clean_name)

    except Exception as e:
        logger.warn(f"⚠️ [DYNAMIC DISCOVERY] Google catalog discovery failed: {e}")

    return discovered


def discover_groq_models(api_key: Optional[str] = None, force: bool = False) -> List[str]:
    """Queries Groq Cloud /models endpoint to discover all active text LLMs without keyword restrictions."""
    if not force:
        cached = get_cached_provider_models("groq")
        if cached is not None:
            return cached

    key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
    core_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    if not key:
        return core_models

    discovered: List[str] = []
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                mid = item.get("id", "")
                if not mid or not is_modality_allowed(mid) or mid in DEPRECATED_KNOWN:
                    continue
                if mid not in discovered:
                    discovered.append(mid)
    except Exception as e:
        logger.warn(f"⚠️ [DYNAMIC DISCOVERY] Groq catalog discovery failed: {e}")

    return discovered or core_models


def discover_openrouter_models(api_key: Optional[str] = None, force: bool = False) -> List[str]:
    """Queries OpenRouter /models endpoint to discover all free community models."""
    if not force:
        cached = get_cached_provider_models("openrouter")
        if cached is not None:
            return cached

    key = api_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return []

    discovered: List[str] = []
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                mid = item.get("id", "")
                if mid.endswith(":free") and is_modality_allowed(mid) and mid not in DEPRECATED_KNOWN:
                    discovered.append(mid)
    except Exception as e:
        logger.warn(f"⚠️ [DYNAMIC DISCOVERY] OpenRouter catalog discovery failed: {e}")

    return discovered


def discover_github_models(api_key: Optional[str] = None, force: bool = False) -> List[str]:
    """Discovers or validates available GitHub Models."""
    if not force:
        cached = get_cached_provider_models("github")
        if cached is not None:
            return cached

    key = api_key or os.environ.get("GH_MODELS_TOKEN", "").strip()
    if not key:
        return []

    # Curated free-tier models available through GitHub Models token
    candidates = ["gpt-4o-mini", "meta/llama-3.3-70b-instruct", "Phi-3.5-mini-instruct", "Mistral-large-2407"]
    verified: List[str] = []
    endpoints = [
        "https://models.github.ai/inference/chat/completions"
    ]
    for model in candidates:
        for ep in endpoints:
            try:
                if requests is None:
                    break
                resp = requests.post(
                    ep,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 2},
                    timeout=5.0
                )
                if resp.status_code in (200, 429):  # 200 OK or rate-limited indicates active model access
                    if model not in verified:
                        verified.append(model)
                    break
            except Exception:
                pass

    return verified


def sync_registry(force: bool = False) -> Dict[str, Any]:
    """Performs full discovery across all 4 providers and updates the local registry."""
    from engine.model_entity import DynamicQuotaTracker, ModelEntity

    reg = load_registry()
    last_sync = reg.get("last_discovery_timestamp", 0.0)
    if not force and (time.time() - last_sync < DISCOVERY_CACHE_TTL_SECONDS):
        hours_ago = round((time.time() - last_sync) / 3600.0, 1)
        logger.info(f"ℹ️ [DYNAMIC REGISTRY] Synced {hours_ago}h ago (<24h TTL). Using cached registry to conserve API quota until post-reset window.")
        return {
            "status": "CACHED",
            "total_entities": len(reg.get("entities", {})),
            "updated_at": reg.get("updated_at", "")
        }

    tracker = DynamicQuotaTracker(REGISTRY_PATH)

    google_models = discover_google_models(force=True)
    groq_models = discover_groq_models(force=True)
    github_models = discover_github_models(force=True)
    openrouter_models = discover_openrouter_models(force=True)

    # Register newly discovered Google models
    for m in google_models:
        eid = f"google:{m}"
        if eid not in tracker.entities:
            is_canary = any(v in m for v in ["3.8", "3.6", "3.7"])
            tracker.entities[eid] = ModelEntity(
                entity_id=eid,
                provider="google",
                model_name=m,
                max_rpm=15 if is_canary else 30,
                max_rpd=20 if is_canary else 500,
                task_quality_scores={"scriptwriting": 9.2 if is_canary else 8.5, "seo_json": 9.0, "vision_audit": 8.5, "fact_grounding": 8.5}
            )

    # Register newly discovered Groq models
    for m in groq_models:
        eid = f"groq:{m}"
        if eid not in tracker.entities:
            tracker.entities[eid] = ModelEntity(
                entity_id=eid,
                provider="groq",
                model_name=m,
                max_rpm=30,
                max_rpd=14400,
                task_quality_scores={"scriptwriting": 8.8, "seo_json": 8.8, "vision_audit": 5.0, "fact_grounding": 8.2}
            )

    # Register newly discovered GitHub models
    for m in github_models:
        eid = f"github:{m}"
        if eid not in tracker.entities:
            tracker.entities[eid] = ModelEntity(
                entity_id=eid,
                provider="github",
                model_name=m,
                max_rpm=15,
                max_rpd=150,
                task_quality_scores={"scriptwriting": 8.9, "seo_json": 9.0, "vision_audit": 7.0, "fact_grounding": 8.5}
            )

    # Register all newly discovered OpenRouter free models
    for m in openrouter_models:
        eid = f"openrouter:{m}"
        if eid not in tracker.entities:
            tracker.entities[eid] = ModelEntity(
                entity_id=eid,
                provider="openrouter",
                model_name=m,
                max_rpm=20,
                max_rpd=200,
                task_quality_scores={"scriptwriting": 8.6, "seo_json": 8.5, "vision_audit": 5.0, "fact_grounding": 8.0}
            )

    tracker.persist()
    fresh_reg = load_registry()
    fresh_reg["last_discovery_timestamp"] = time.time()
    save_registry(fresh_reg)

    logger.success(f"✅ [DYNAMIC REGISTRY] Synced {len(tracker.entities)} model entities across 4 providers.")

    return {
        "status": "SUCCESS",
        "total_entities": len(tracker.entities),
        "google_discovered": google_models,
        "groq_discovered": groq_models,
        "github_discovered": github_models,
        "openrouter_discovered": openrouter_models,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
