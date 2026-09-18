# scripts/diagnose_gemini.py — Ghost Engine V7.3
"""
Dedicated Gemini API Diagnostics & Model Catalog Inspector.

Purpose:
1. Audits live Google Gemini API catalog using official google-genai SDK.
2. Identifies exact available models, supported methods, and rate limits.
3. Tests candidate models across the 3 core tasks used by Ghost Engine:
   - Task 1: Creative Script Generation (with system prompt)
   - Task 2: Fact Grounding (with Google Search tool)
   - Task 3: Structured SEO JSON Metadata Extraction
4. Discloses 100% of error details, HTTP status codes, gRPC errors, and latency.
5. Prints a consolidated diagnostic comparison matrix.
"""
import os
import sys
import time
import json
import traceback
from typing import Dict, List, Any, Optional

# Safe UTF-8 console output for all environments
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DIVIDER_HEAVY = "═" * 72
DIVIDER_LIGHT = "─" * 72


def print_header(title: str):
    print(f"\n{DIVIDER_HEAVY}")
    print(f"🔍 {title.upper()}")
    print(f"{DIVIDER_HEAVY}\n")


def audit_catalog(client) -> List[str]:
    """Lists all available models and returns candidate text model IDs."""
    print_header("1. Live Gemini Model Catalog Audit")
    candidate_models = []

    try:
        print("[CATALOG] Querying client.models.list()...")
        t0 = time.time()
        models = list(client.models.list())
        latency = (time.time() - t0) * 1000.0
        print(f"[CATALOG] Retrieved {len(models)} models in {latency:.1f}ms.\n")

        print(f"{'Model ID':<35} | {'Display Name':<25} | {'Methods'}")
        print(f"{'-'*35}-+-{'-'*25}-+-{'-'*25}")

        for m in models:
            m_id = getattr(m, "name", "unknown").replace("models/", "")
            display_name = getattr(m, "display_name", "") or ""
            methods = getattr(m, "supported_generation_methods", []) or []
            methods_str = ", ".join(methods) if isinstance(methods, list) else str(methods)

            # Highlight Flash and text-generation models
            is_candidate = "generateContent" in methods_str or "generate_content" in methods_str or not methods
            if is_candidate and "flash" in m_id.lower():
                candidate_models.append(m_id)
                prefix = "👉"
            else:
                prefix = "  "

            print(f"{prefix} {m_id:<33} | {display_name[:25]:<25} | {methods_str[:30]}")

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
    """Executes a single test task against a model and logs full diagnostic data."""
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

    print(f"\n   ┌── Task: [{task_name}] on model [{model_id}]")
    t0 = time.time()

    try:
        cfg_kwargs: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": 1500,
            "http_options": {"timeout": int(timeout_s * 1000)}
        }
        if system_prompt:
            cfg_kwargs["system_instruction"] = system_prompt
        if tools:
            cfg_kwargs["tools"] = tools

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
        # Log HTTP error code or response details if available
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

    client = genai.Client(api_key=api_key, http_options={"timeout": 30000})

    # Step 1: Query catalog
    discovered_flash = audit_catalog(client)

    # Step 2: Compile curated candidate roster
    # Standard production roster + any discovered flash models
    roster_priority = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ]
    # Add any discovered models not already in roster
    for m in discovered_flash:
        if m not in roster_priority:
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

        # ── Test 1: Script Generation ──
        res_script = test_model_task(
            client=client,
            model_id=model_id,
            task_name="Script Gen",
            prompt=script_prompt,
            system_prompt=script_system,
            temperature=0.8,
            timeout_s=12.0
        )
        model_results["script"] = res_script

        # ── Test 2: Fact Grounding (with Search Tool) ──
        # Test standard generate_content with google_search tool
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
            timeout_s=10.0
        )
        model_results["seo"] = res_seo

        matrix[model_id] = model_results
        time.sleep(1.0)  # Gentle inter-model delay to avoid burst throttling

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

    print(f"\n{DIVIDER_HEAVY}")
    print("🏁 DIAGNOSTICS COMPLETE. Copy this log to analyze API behavior.")
    print(f"{DIVIDER_HEAVY}\n")


if __name__ == "__main__":
    run_diagnostics()

