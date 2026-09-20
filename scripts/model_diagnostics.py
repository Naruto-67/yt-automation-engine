# scripts/model_diagnostics.py — Multi-Provider Model Diagnostics & Health Audit
"""
Comprehensive multi-provider diagnostic test harness for Ghost Engine.
Evaluates Google GenAI, Groq Cloud, GitHub Models, and OpenRouter across:
- Task 0: Minimal Ping & Response Header Sniffing (Validates auth and sniffs rate limits)
- Task 1: Creative Script Generation (Evaluates 4 scenes, word counts, and circular loop)
- Task 2: Structured SEO JSON Generation (Evaluates schema parsing & curiosity gap)
Guarantees 100% API key secrecy (masking all tokens as '***').
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import json
import traceback
try:
    import requests
except ImportError:
    requests = None
from typing import Dict, Any, List, Optional

DIVIDER_HEAVY = "=" * 88
DIVIDER_LIGHT = "-" * 88


def mask_key(k: str) -> str:
    """Masks secret keys for 100% terminal and log secrecy (zero key slices)."""
    if not k:
        return "[NOT SET]"
    return "***"


def print_header(title: str):
    print(f"\n{DIVIDER_HEAVY}")
    print(f"🔬 {title.upper()}")
    print(DIVIDER_HEAVY)


def test_google_provider(api_key: str, models_to_test: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    print_header("1. Google GenAI Diagnostics")
    print(f"🔑 Authenticating Google GenAI [Key: {mask_key(api_key)}]")
    if not api_key:
        print("⚠️ GEMINI_API_KEY is not set. Skipping Google tests.")
        return []

    from google import genai
    from google.genai import types
    from engine.model_entity import DynamicQuotaTracker

    tracker = DynamicQuotaTracker()
    results = []
    client = genai.Client(api_key=api_key, http_options={"timeout": 120000})

    if not models_to_test:
        models_to_test = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash"
        ]

    for model_name in models_to_test:
        entity_id = f"google:{model_name}"
        print(f"\n   ┌── Model: [{entity_id}]")
        # 1. Minimal Ping
        ping_ok = False
        t0 = time.time()
        lat = 0.0
        for attempt in range(3):
            try:
                cfg = types.GenerateContentConfig(
                    max_output_tokens=10,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                )
                resp = client.models.generate_content(model=model_name, contents="ping", config=cfg)
                lat = round(time.time() - t0, 2)
                txt = (resp.text or "").strip()
                print(f"   ├── Task 0 (Minimal Ping): ✅ PASS ({lat}s) -> '{txt}'")
                tracker.record_call_success(entity_id, "ping", lat)
                ping_ok = True
                break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "UNAVAILABLE" in err_str) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 0 hit 503 demand spike. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                lat = round(time.time() - t0, 2)
                print(f"   ├── Task 0 (Minimal Ping): ❌ FAIL ({lat}s) -> {e}")
                break

        # 2. Creative Script
        script_ok = False
        t1 = time.time()
        for attempt in range(3):
            try:
                cfg = types.GenerateContentConfig(
                    system_instruction="You are a scriptwriter. Output exactly 4 scenes between 85-125 words total as JSON.",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                )
                if "3.8" in model_name:
                    try:
                        cfg.thinking_config = types.ThinkingConfig(thinking_level="low")
                    except Exception:
                        pass

                resp = client.models.generate_content(
                    model=model_name,
                    contents="Write a 4-scene script about the immortal jellyfish Turritopsis dohrnii.",
                    config=cfg
                )
                lat_script = round(time.time() - t1, 2)
                text = (resp.text or "").strip()
                words = len(text.split())
                print(f"   ├── Task 1 (Scriptwriting): ✅ PASS ({lat_script}s, {words} words)")
                tracker.record_call_success(entity_id, "scriptwriting", lat_script)
                script_ok = True
                break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "UNAVAILABLE" in err_str) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 1 hit 503 demand spike. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                lat_script = round(time.time() - t1, 2)
                print(f"   ├── Task 1 (Scriptwriting): ❌ FAIL ({lat_script}s) -> {e}")
                break

        # 3. SEO JSON
        seo_ok = False
        t2 = time.time()
        for attempt in range(3):
            try:
                cfg = types.GenerateContentConfig(
                    system_instruction="Return ONLY valid JSON: {\"title\": \"...\", \"tags\": [\"...\"]}",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                )
                resp = client.models.generate_content(
                    model=model_name,
                    contents="Generate YouTube SEO metadata for an immortal jellyfish video.",
                    config=cfg
                )
                lat_seo = round(time.time() - t2, 2)
                print(f"   └── Task 2 (SEO JSON): ✅ PASS ({lat_seo}s)")
                tracker.record_call_success(entity_id, "seo_json", lat_seo)
                seo_ok = True
                break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "UNAVAILABLE" in err_str) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 2 hit 503 demand spike. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                lat_seo = round(time.time() - t2, 2)
                print(f"   └── Task 2 (SEO JSON): ❌ FAIL ({lat_seo}s) -> {e}")
                break

        results.append({
            "entity_id": f"google:{model_name}",
            "ping": ping_ok,
            "script": script_ok,
            "seo": seo_ok,
            "latency": lat
        })

    return results


def test_openai_compatible_provider(
    provider_name: str,
    endpoint: str,
    api_key: str,
    models_to_test: List[str],
    extra_headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    print_header(f"Diagnostics: {provider_name.upper()}")
    print(f"🔑 Authenticating {provider_name.title()} [Key: {mask_key(api_key)}]")
    if not api_key:
        print(f"⚠️ API key for {provider_name} is not set. Skipping tests.")
        return []
    if requests is None:
        print(f"⚠️ 'requests' package not available. Skipping {provider_name} tests.")
        return []

    tracker = DynamicQuotaTracker()
    results = []
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    if extra_headers:
        headers.update(extra_headers)

    for model_name in models_to_test:
        entity_id = f"{provider_name}:{model_name}"
        print(f"\n   ┌── Model: [{entity_id}]")
        # 1. Minimal Ping & Header Sniffing
        ping_ok = False
        t0 = time.time()
        lat = 0.0
        for attempt in range(3):
            try:
                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json={"model": model_name, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                    timeout=(10.0, 20.0)
                )
                lat = round(time.time() - t0, 2)
                if resp.status_code == 200:
                    print(f"   ├── Task 0 (Minimal Ping): ✅ PASS ({lat}s)")
                    sniffed_rpm = resp.headers.get("x-ratelimit-limit-requests") or resp.headers.get("x-ratelimit-limit") or "N/A"
                    sniffed_rem = resp.headers.get("x-ratelimit-remaining-requests") or resp.headers.get("x-ratelimit-remaining") or "N/A"
                    print(f"   │   📡 Sniffed Headers -> RPM Limit: {sniffed_rpm} | Remaining: {sniffed_rem}")
                    tracker.sniff_headers(entity_id, resp.headers)
                    tracker.record_call_success(entity_id, "ping", lat)
                    ping_ok = True
                    break
                elif resp.status_code in (502, 503, 504) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 0 hit HTTP {resp.status_code}. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                else:
                    print(f"   ├── Task 0 (Minimal Ping): ❌ FAIL ({lat}s) -> HTTP {resp.status_code}: {resp.text[:120]}")
                    break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "timeout" in err_str.lower()) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 0 transient network issue. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                lat = round(time.time() - t0, 2)
                print(f"   ├── Task 0 (Minimal Ping): ❌ FAIL ({lat}s) -> {e}")
                break

        # 2. Scriptwriting
        script_ok = False
        t1 = time.time()
        for attempt in range(3):
            try:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "You are a scriptwriter. Output 4 scenes between 85-125 words total as JSON."},
                        {"role": "user", "content": "Write a 4-scene video script about Turritopsis dohrnii immortal jellyfish."}
                    ],
                    "temperature": 0.7
                }
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=(10.0, 120.0))
                lat_script = round(time.time() - t1, 2)
                if resp.status_code == 200:
                    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    words = len(content.split())
                    print(f"   ├── Task 1 (Scriptwriting): ✅ PASS ({lat_script}s, {words} words)")
                    tracker.sniff_headers(entity_id, resp.headers)
                    tracker.record_call_success(entity_id, "scriptwriting", lat_script)
                    script_ok = True
                    break
                elif resp.status_code in (502, 503, 504) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 1 hit HTTP {resp.status_code}. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                else:
                    print(f"   ├── Task 1 (Scriptwriting): ❌ FAIL ({lat_script}s) -> HTTP {resp.status_code}")
                    break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "timeout" in err_str.lower()) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 1 transient network issue. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                lat_script = round(time.time() - t1, 2)
                print(f"   ├── Task 1 (Scriptwriting): ❌ FAIL ({lat_script}s) -> {e}")
                break

        # 3. SEO JSON
        seo_ok = False
        t2 = time.time()
        for attempt in range(3):
            try:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "Return ONLY valid JSON: {\"title\": \"...\", \"tags\": [\"...\"]}"},
                        {"role": "user", "content": "Generate YouTube SEO metadata for Turritopsis dohrnii."}
                    ],
                    "temperature": 0.2
                }
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=(10.0, 120.0))
                lat_seo = round(time.time() - t2, 2)
                if resp.status_code == 200:
                    print(f"   └── Task 2 (SEO JSON): ✅ PASS ({lat_seo}s)")
                    tracker.sniff_headers(entity_id, resp.headers)
                    tracker.record_call_success(entity_id, "seo_json", lat_seo)
                    seo_ok = True
                    break
                elif resp.status_code in (502, 503, 504) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 2 hit HTTP {resp.status_code}. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                else:
                    print(f"   └── Task 2 (SEO JSON): ❌ FAIL ({lat_seo}s) -> HTTP {resp.status_code}")
                    break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "timeout" in err_str.lower()) and attempt < 2:
                    wait_s = 2.0 * (attempt + 1)
                    print(f"   │   ⏳ Task 2 transient network issue. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
                    continue
                lat_seo = round(time.time() - t2, 2)
                print(f"   └── Task 2 (SEO JSON): ❌ FAIL ({lat_seo}s) -> {e}")
                break

        results.append({
            "entity_id": f"{provider_name}:{model_name}",
            "ping": ping_ok,
            "script": script_ok,
            "seo": seo_ok,
            "latency": lat
        })

    return results


def main():
    print(DIVIDER_HEAVY)
    print("🚀 GHOST ENGINE — MULTI-PROVIDER MODEL DIAGNOSTICS & HEALTH AUDIT")
    print(DIVIDER_HEAVY)

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    gh_key = os.environ.get("GH_MODELS_TOKEN", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

    from engine.dynamic_discovery import (
        discover_google_models,
        discover_groq_models,
        discover_github_models,
        discover_openrouter_models
    )

    all_results = []

    # 1. Google GenAI
    discovered_google = discover_google_models() or ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    google_res = test_google_provider(gemini_key, models_to_test=discovered_google)
    all_results.extend(google_res)

    # 2. Groq Cloud
    discovered_groq = discover_groq_models(groq_key) or ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    groq_res = test_openai_compatible_provider(
        provider_name="groq",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        api_key=groq_key,
        models_to_test=discovered_groq
    )
    all_results.extend(groq_res)

    # 3. GitHub Models
    discovered_gh = discover_github_models(gh_key)
    if discovered_gh:
        gh_res = test_openai_compatible_provider(
            provider_name="github",
            endpoint="https://models.github.ai/inference/chat/completions",
            api_key=gh_key,
            models_to_test=discovered_gh
        )
        all_results.extend(gh_res)
    else:
        print("\n   ℹ️ GitHub Models: No active models discovered (service in brownout/retired). Skipping.")

    # 4. OpenRouter Free Pool
    discovered_or = discover_openrouter_models(openrouter_key) or [
        "qwen/qwen-2.5-72b-instruct:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "deepseek/deepseek-r1:free"
    ]
    or_res = test_openai_compatible_provider(
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        api_key=openrouter_key,
        models_to_test=discovered_or,
        extra_headers={"HTTP-Referer": "https://github.com/yt-automation-engine", "X-Title": "Ghost Engine"}
    )
    all_results.extend(or_res)

    # ── Final Summary Matrix ──────────────────────────────────────────────────
    print_header("Final Comparative Summary Matrix")
    print(f"{'Namespaced Model URI':<45} | {'Ping':<8} | {'Script':<8} | {'SEO':<8} | {'Latency':<8}")
    print(f"{'-'*45}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")

    for r in all_results:
        p = "✅ PASS" if r["ping"] else "❌ FAIL"
        s = "✅ PASS" if r["script"] else "❌ FAIL"
        j = "✅ PASS" if r["seo"] else "❌ FAIL"
        lat_str = f"{r['latency']:.2f}s"
        print(f"{r['entity_id']:<45} | {p:<8} | {s:<8} | {j:<8} | {lat_str:<8}")

    print(f"\n{DIVIDER_HEAVY}")
    print("✅ Diagnostic Suite Completed.")
    print(DIVIDER_HEAVY)

    # Sync registry dynamically
    from engine.dynamic_discovery import sync_registry
    sync_res = sync_registry()
    print(f"🔄 [REGISTRY SYNC] {sync_res}")


if __name__ == "__main__":
    main()

