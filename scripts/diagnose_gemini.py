# scripts/diagnose_gemini.py — Dedicated Lightweight Gemini Diagnostics Suite
"""
Focused upstream diagnostic test harness for Google GenAI API.
Verifies live model catalog, tests core tasks (Scriptwriting, Search Grounding, SEO JSON),
logs uncensored HTTP/gRPC codes and latency, enforces thinking_level='low' for 3.x models,
and applies Google's Chat pattern (Fix 1) to eliminate Automatic Function Calling warnings.
"""

import os
import sys
import time
import json
import traceback
from typing import Dict, Any, List, Optional

DIVIDER_HEAVY = "=" * 80
DIVIDER_LIGHT = "-" * 80


def print_header(title: str):
    print(f"\n{DIVIDER_HEAVY}")
    print(f"🔬 {title.upper()}")
    print(DIVIDER_HEAVY)


def audit_catalog(client) -> List[str]:
    """Queries client.models.list() and identifies all available text/flash models."""
    print_header("1. Upstream Model Catalog Discovery")
    candidate_models: List[str] = []

    try:
        models = list(client.models.list())
        print(f"Found {len(models)} total models in upstream catalog.\n")

        # Exclude non-text modalities
        EXCLUDED_SUBSTRINGS = [
            "image", "picture", "tts", "audio", "live", "embed",
            "robotics", "video", "veo", "whisper", "transcribe",
            "guard", "safeguard"
        ]

        print(f"{'Model Name':<38} | {'Display Name':<30}")
        print(f"{'-'*38}-+-{'-'*30}")

        for m in models:
            name = getattr(m, "name", "unknown").replace("models/", "")
            display = getattr(m, "display_name", "") or ""

            # Check for modality exclusion
            if any(k in name.lower() for k in EXCLUDED_SUBSTRINGS):
                continue

            print(f"{name:<38} | {display:<30}")
            candidate_models.append(name)

    except Exception as e:
        print(f"❌ [CATALOG ERROR] Failed to list models: {type(e).__name__}: {e}")
        traceback.print_exc()

    return candidate_models


def test_model_task(
    client,
    model_id: str,
    task_name: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
    temperature: float = 0.7,
    timeout_s: float = 15.0
) -> Dict[str, Any]:
    """Executes a single test task against a model with thinking config and Fix 1 Chat pattern."""
    from google.genai import types

    result = {
        "task": task_name,
        "model": model_id,
        "status": "FAIL",
        "latency_ms": 0.0,
        "output_chars": 0,
        "word_count": 0,
        "error_type": None,
        "error_msg": None,
        "sample": ""
    }

    print(f"\n   ┌── Task: [{task_name}] on model [{model_id}] (Timeout: {timeout_s:.1f}s)")
    t0 = time.time()

    try:
        timeout_ms = int(timeout_s * 1000)
        cfg_kwargs: Dict[str, Any] = {
            "http_options": {"timeout": timeout_ms}
        }

        # 3.x parameter handling: strip deprecated temperature, inject thinking_level="low"
        is_3x = any(v in model_id for v in ["3.8", "3.7", "3.6", "3.5", "3-"])
        if is_3x:
            # "minimal" is not supported on 3.8/3.7 Flash; must use "low"
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        else:
            cfg_kwargs["temperature"] = temperature

        if system_prompt:
            cfg_kwargs["system_instruction"] = system_prompt

        if tools:
            cfg_kwargs["tools"] = tools
            config = types.GenerateContentConfig(**cfg_kwargs)

            # Fix 1: Use client.chats.create + chat.send_message to eliminate AFC warning
            chat = client.chats.create(
                model=model_id,
                config=config
            )
            response = chat.send_message(prompt)
        else:
            config = types.GenerateContentConfig(**cfg_kwargs)
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=config
            )

        latency = (time.time() - t0) * 1000.0
        result["latency_ms"] = latency

        text = response.text if response and response.text else ""
        if text:
            result["status"] = "PASS"
            result["output_chars"] = len(text)
            result["word_count"] = len(text.split())
            result["sample"] = text[:180].replace("\n", " ")
            print(f"   │ ✅ PASS in {latency:.1f}ms | Words: {result['word_count']} | Chars: {len(text)}")
            print(f"   │ Sample: \"{result['sample']}...\"")
        else:
            result["status"] = "EMPTY"
            result["error_msg"] = "Response object returned empty text"
            print(f"   │ ⚠️ EMPTY response in {latency:.1f}ms")

    except Exception as e:
        latency = (time.time() - t0) * 1000.0
        result["latency_ms"] = latency
        result["error_type"] = type(e).__name__
        result["error_msg"] = str(e)
        print(f"   │ ❌ ERROR in {latency:.1f}ms: [{result['error_type']}] {result['error_msg']}")
        if hasattr(e, "code"):
            print(f"   │    HTTP/gRPC Code: {getattr(e, 'code')}")
        if hasattr(e, "response"):
            resp = getattr(e, "response")
            print(f"   │    Response Headers: {getattr(resp, 'headers', {})}")
            print(f"   │    Response Body: {getattr(resp, 'text', '')[:300]}")
    finally:
        print(f"   └── Done")

    return result


def run_diagnostics():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("❌ [FATAL] GEMINI_API_KEY environment variable is missing or empty.")
        sys.exit(1)

    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 10 else "***"
    print(f"🔑 Initializing Gemini Client with key: {masked_key}")

    try:
        from google import genai
        from google.genai import types
    except ImportError as ie:
        print(f"❌ [FATAL] google-genai SDK not installed: {ie}")
        print("Run: pip install google-genai")
        sys.exit(1)

    client = genai.Client(api_key=api_key, http_options={"timeout": 35000})

    # Step 1: Query catalog
    discovered_flash = audit_catalog(client)

    # Step 2: Compile curated candidate roster
    # Priority order: modern active workhorses first, then canaries, then legacy
    roster_priority = [
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
    ]

    DEPRECATED = {
        "gemini-2.0-flash", "gemini-2.0-flash-lite",
        "gemini-1.5-flash", "gemini-1.5-flash-8b",
        "gemini-1.5-pro", "gemini-2.0-pro"
    }

    # Add any newly discovered models not already in roster or deprecated
    for m in discovered_flash:
        if m not in roster_priority and m not in DEPRECATED:
            roster_priority.append(m)

    print_header("2. Evaluating Candidate Models Across Core Tasks")
    print(f"Evaluation Target Roster: {roster_priority}\n")

    # Task definitions matching Ghost Engine production
    script_prompt = "A young blacksmith's apprentice secretly crafts a mechanical bird to save a trapped mountain climber, defying guild rules."
    script_system = (
        "You are an expert YouTube Shorts storyteller. Write a vivid, moral 4-scene narrative.\n"
        "Output strictly valid JSON with keys: scenes (list of objects with scene_num and text)."
    )

    fact_prompt = "Identify 3 verified empirical anchors (biological taxonomy, mechanisms) for the immortal jellyfish Turritopsis dohrnii."
    
    seo_prompt = "Generate an optimized YouTube Shorts title, 2-sentence description, and 8 comma-separated tags for: Turritopsis dohrnii immortal jellyfish."
    seo_system = "Output strictly valid JSON with keys: title, description, tags."

    matrix: Dict[str, Dict[str, Any]] = {}

    for model_id in roster_priority:
        print(f"\n{DIVIDER_LIGHT}")
        print(f"🧪 TESTING MODEL: {model_id}")
        print(DIVIDER_LIGHT)

        model_results = {}

        # 3.8 and 3.7 require 25s timeout to account for dynamic reasoning tokens
        is_deep_thinking = any(k in model_id for k in ["3.8", "3.7"])
        script_timeout = 25.0 if is_deep_thinking else 15.0
        seo_timeout = 20.0 if is_deep_thinking else 10.0

        # ── Test 1: Script Generation ──
        res_script = test_model_task(
            client=client,
            model_id=model_id,
            task_name="Script Gen",
            prompt=script_prompt,
            system_prompt=script_system,
            temperature=0.8,
            timeout_s=script_timeout
        )
        model_results["script"] = res_script

        # ── Test 2: Fact Grounding (Fix 1: Chat pattern with Search Tool) ──
        search_tool = [types.Tool(google_search=types.GoogleSearch())]
        res_fact = test_model_task(
            client=client,
            model_id=model_id,
            task_name="Fact Grounding (Search)",
            prompt=fact_prompt,
            tools=search_tool,
            temperature=0.2,
            timeout_s=15.0
        )
        model_results["fact"] = res_fact

        # ── Test 3: Structured SEO JSON ──
        res_seo = test_model_task(
            client=client,
            model_id=model_id,
            task_name="SEO JSON",
            prompt=seo_prompt,
            system_prompt=seo_system,
            temperature=0.2,
            timeout_s=seo_timeout
        )
        model_results["seo"] = res_seo

        matrix[model_id] = model_results
        time.sleep(1.0)  # Inter-model throttle

    # Step 3: Print Consolidated Summary Matrix
    print_header("3. Diagnostic Summary Matrix")
    print(f"{'Model ID':<28} | {'Script Gen':<14} | {'Fact Ground':<14} | {'SEO JSON':<14} | {'Overall'}")
    print(f"{'-'*28}-+-{'-'*14}-+-{'-'*14}-+-{'-'*14}-+-{'-'*10}")

    for model_id, results in matrix.items():
        s_stat = results["script"]["status"]
        s_time = f"{results['script']['latency_ms']/1000.0:.1f}s"
        s_str = f"{s_stat} ({s_time})"

        f_stat = results["fact"]["status"]
        f_time = f"{results['fact']['latency_ms']/1000.0:.1f}s"
        f_str = f"{f_stat} ({f_time})"

        seo_stat = results["seo"]["status"]
        seo_time = f"{results['seo']['latency_ms']/1000.0:.1f}s"
        seo_str = f"{seo_stat} ({seo_time})"

        all_pass = all(r["status"] == "PASS" for r in results.values())
        overall = "✅ ROBUST" if all_pass else ("⚠️ PARTIAL" if any(r["status"] == "PASS" for r in results.values()) else "❌ DEAD")

        print(f"{model_id:<28} | {s_str:<14} | {f_str:<14} | {seo_str:<14} | {overall}")

    # Optional sync to dynamic models registry
    if "--sync-registry" in sys.argv or os.environ.get("UPDATE_REGISTRY") == "true":
        print("\n📝 Synchronizing healthy models with memory/dynamic_models_registry.json...")
        try:
            from engine.dynamic_discovery import sync_registry
            sync_res = sync_registry()
            print(f"✅ Registry updated: {sync_res}")
        except Exception as e:
            print(f"⚠️ Failed to sync registry: {e}")

    print(f"\n{DIVIDER_HEAVY}")
    print("🏁 DIAGNOSTICS COMPLETE. Copy this log to analyze API behavior.")
    print(f"{DIVIDER_HEAVY}\n")


if __name__ == "__main__":
    run_diagnostics()
