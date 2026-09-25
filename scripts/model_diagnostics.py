# scripts/model_diagnostics.py — Multi-Provider Model Diagnostics & Health Audit
"""
Comprehensive multi-provider diagnostic test harness for Ghost Engine.
Evaluates Google GenAI, Groq Cloud, GitHub Models, and OpenRouter across:
- Task 0: Minimal Ping & Response Header Sniffing (Validates auth and sniffs rate limits)
- Task 1: Creative Script Generation (Evaluates 4 scenes, word counts, sentence closure, hook, circular loop)
- Task 2: Structured SEO JSON Generation (Evaluates schema parsing, curiosity gap, title CTR length)
- Real-time wire-level Thinking & Reasoning Detection (zero hardcoding)
- Latency & Token Generation Throughput (tok/s) Telemetry
- Dynamic Registry Calibration (Empirical Quality Rating 0.0–10.0 scale)
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
import random
import traceback
try:
    import requests
except ImportError:
    requests = None
from typing import Dict, Any, List, Optional
from engine.model_entity import DynamicQuotaTracker
from engine.thinking_detector import ThinkingDetector
from engine.quality_evaluator import QualityEvaluator
from engine.llm_router import UniversalGreedyJSONParser


def _calc_diagnostic_backoff(attempt: int, is_thinking: bool = False) -> float:
    base = 10.0 if is_thinking else 6.0
    return ((attempt + 1) * base) + random.uniform(1.0, 3.0)


DIVIDER_HEAVY = "=" * 94
DIVIDER_LIGHT = "-" * 94


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
        entity = tracker.get_entity(entity_id)
        is_known_thinking = getattr(entity, "supports_thinking", False) if entity else False
        quota_exhausted_for_model = False

        print(f"\n   ┌── Model: [{entity_id}]")

        # ── 1. Minimal Ping & Wire Check ──────────────────────────────────────
        ping_ok = False
        t0 = time.time()
        lat_ping = 0.0
        thinking_meta = {"is_thinking": False, "method": "none", "thought_tokens": 0, "thought_snippet": ""}

        for attempt in range(3):
            try:
                cfg = types.GenerateContentConfig(
                    max_output_tokens=15,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                )
                resp = client.models.generate_content(model=model_name, contents="ping", config=cfg)
                lat_ping = round(time.time() - t0, 2)
                txt = (resp.text or "").strip()

                # Dynamic Thinking Detection on Ping
                t_detect = ThinkingDetector.detect_google_response(resp)
                if t_detect["is_thinking"]:
                    thinking_meta = t_detect
                    is_known_thinking = True

                think_str = f" | 🧠 Thinking Detected ({t_detect['thought_tokens']} tok)" if t_detect["is_thinking"] else ""
                print(f"   ├── Task 0 (Minimal Ping)  : ✅ PASS ({lat_ping}s) -> '{txt}'{think_str}")

                tracker.record_call_success(
                    entity_id, "ping", lat_ping, quality_rating=9.5,
                    supports_thinking=t_detect["is_thinking"],
                    thinking_type=t_detect["method"],
                    thinking_tokens=t_detect["thought_tokens"]
                )
                ping_ok = True
                break
            except Exception as e:
                err_str = str(e)
                if any(x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                    lat_ping = round(time.time() - t0, 2)
                    print(f"   ├── Task 0 (Minimal Ping)  : 🛑 QUOTA EXHAUSTED ({lat_ping}s) -> Daily Limit Reached (429)")
                    tracker.record_call_error(entity_id, 429, err_str)
                    quota_exhausted_for_model = True
                    break
                if any(x in err_str.lower() for x in ["503", "504", "unavailable", "high demand", "deadline_exceeded", "timeout"]) and attempt < 2:
                    wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                    print(f"   │   ⏳ Task 0 hit capacity surge. Retrying in {wait_s:.1f}s...")
                    time.sleep(wait_s)
                    continue
                lat_ping = round(time.time() - t0, 2)
                print(f"   ├── Task 0 (Minimal Ping)  : ❌ FAIL ({lat_ping}s) -> {e}")
                break

        # ── 2. Scriptwriting Quality Audit ────────────────────────────────────
        script_ok = False
        t1 = time.time()
        lat_script = 0.0
        script_audit = {"score": 0.0, "word_count": 0, "scene_count": 0, "feedback": []}
        script_throughput = 0.0

        if quota_exhausted_for_model:
            print(f"   │   🛑 Quota exhausted for [{entity_id}]. Skipping remaining tasks to protect quota.")
        else:
            time.sleep(2.0)
            for attempt in range(3):
                try:
                    cfg = types.GenerateContentConfig(
                        system_instruction="You are a professional YouTube Shorts scriptwriter. Output exactly 4 scenes between 85-125 words total as JSON with a 'scenes' array.",
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )

                    # Socket-Preserving Streaming for Thinking Models
                    raw_script = ""
                    if is_known_thinking:
                        try:
                            stream = client.models.generate_content_stream(
                                model=model_name,
                                contents="Write a 4-scene video script about Turritopsis dohrnii immortal jellyfish.",
                                config=cfg
                            )
                            chunks = []
                            for ch in stream:
                                if ch.text:
                                    chunks.append(ch.text)
                            raw_script = "".join(chunks).strip()
                        except Exception as s_err:
                            raw_script = ""

                    if not raw_script:
                        resp = client.models.generate_content(
                            model=model_name,
                            contents="Write a 4-scene video script about Turritopsis dohrnii immortal jellyfish.",
                            config=cfg
                        )
                        raw_script = (resp.text or "").strip()
                        # Re-detect thinking on full generation
                        t_detect = ThinkingDetector.detect_google_response(resp)
                        if t_detect["is_thinking"]:
                            thinking_meta = t_detect
                            is_known_thinking = True

                    lat_script = round(time.time() - t1, 2)
                    est_tokens = max(1, len(raw_script) // 4)
                    script_throughput = round(est_tokens / max(lat_script, 0.1), 1)

                    # Resilient Parsing (Level 1-3 -> Level 4 Fallback)
                    parsed_script = UniversalGreedyJSONParser.extract_or_synthesize(raw_script, expected_type="script", fallback_topic="Turritopsis dohrnii")

                    # Multi-Gate Quality Scoring
                    script_audit = QualityEvaluator.audit_script(parsed_script, raw_text=raw_script)
                    score = script_audit["score"]

                    fb_summary = " | ".join(script_audit["feedback"][:3])
                    print(f"   ├── Task 1 (Scriptwriting) : ✅ PASS ({lat_script}s) | Score: {score}/10 | {script_audit['word_count']} words | {script_audit['scene_count']} scenes | ~{script_throughput} tok/s")
                    print(f"   │   📊 Gate Audit: {fb_summary}")
                    if thinking_meta["is_thinking"]:
                        print(f"   │   🧠 Thinking Telemetry: {thinking_meta['method']} (~{thinking_meta['thought_tokens']} tokens) | Snippet: \"{thinking_meta['thought_snippet'][:80]}...\"")

                    tracker.record_call_success(
                        entity_id, "scriptwriting", lat_script, quality_rating=score,
                        supports_thinking=thinking_meta["is_thinking"],
                        thinking_type=thinking_meta["method"],
                        thinking_tokens=thinking_meta["thought_tokens"]
                    )
                    script_ok = True
                    break
                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                        lat_script = round(time.time() - t1, 2)
                        print(f"   ├── Task 1 (Scriptwriting) : 🛑 QUOTA EXHAUSTED ({lat_script}s) -> Daily Limit Reached (429)")
                        tracker.record_call_error(entity_id, 429, err_str)
                        quota_exhausted_for_model = True
                        break
                    if any(x in err_str.lower() for x in ["503", "504", "unavailable", "high demand", "deadline_exceeded", "timeout"]) and attempt < 2:
                        wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                        print(f"   │   ⏳ Task 1 hit capacity surge. Retrying in {wait_s:.1f}s...")
                        time.sleep(wait_s)
                        continue
                    lat_script = round(time.time() - t1, 2)
                    print(f"   ├── Task 1 (Scriptwriting) : ❌ FAIL ({lat_script}s) -> {e}")
                    break

        # ── 3. SEO JSON & CTR Packaging Quality Audit ─────────────────────────
        seo_ok = False
        t2 = time.time()
        lat_seo = 0.0
        seo_audit = {"score": 0.0, "title": "", "tag_count": 0, "feedback": []}
        seo_throughput = 0.0

        if not quota_exhausted_for_model:
            time.sleep(2.0)
            for attempt in range(3):
                try:
                    cfg = types.GenerateContentConfig(
                        system_instruction="Return ONLY valid JSON matching: {\"title\": \"...\", \"description\": \"...\", \"tags\": [\"...\"]}",
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )
                    resp = client.models.generate_content(
                        model=model_name,
                        contents="Generate viral YouTube SEO metadata for Turritopsis dohrnii immortal jellyfish.",
                        config=cfg
                    )
                    lat_seo = round(time.time() - t2, 2)
                    raw_seo = (resp.text or "").strip()
                    est_tokens = max(1, len(raw_seo) // 4)
                    seo_throughput = round(est_tokens / max(lat_seo, 0.1), 1)

                    # Resilient Parsing & Audit
                    parsed_seo = UniversalGreedyJSONParser.extract_or_synthesize(raw_seo, expected_type="seo", fallback_topic="Turritopsis dohrnii")
                    seo_audit = QualityEvaluator.audit_seo(parsed_seo, raw_text=raw_seo)
                    score = seo_audit["score"]

                    fb_summary = " | ".join(seo_audit["feedback"][:3])
                    print(f"   └── Task 2 (SEO Metadata)  : ✅ PASS ({lat_seo}s) | Score: {score}/10 | Title: \"{seo_audit.get('title', '')[:35]}...\" | {seo_audit.get('tag_count', 0)} tags | ~{seo_throughput} tok/s")
                    print(f"       📊 Gate Audit: {fb_summary}")

                    tracker.record_call_success(entity_id, "seo_json", lat_seo, quality_rating=score)
                    seo_ok = True
                    break
                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                        lat_seo = round(time.time() - t2, 2)
                        print(f"   └── Task 2 (SEO Metadata)  : 🛑 QUOTA EXHAUSTED ({lat_seo}s) -> Daily Limit Reached (429)")
                        tracker.record_call_error(entity_id, 429, err_str)
                        quota_exhausted_for_model = True
                        break
                    if any(x in err_str.lower() for x in ["503", "504", "unavailable", "high demand", "deadline_exceeded", "timeout"]) and attempt < 2:
                        wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                        print(f"   │   ⏳ Task 2 hit capacity surge. Retrying in {wait_s:.1f}s...")
                        time.sleep(wait_s)
                        continue
                    lat_seo = round(time.time() - t2, 2)
                    print(f"   └── Task 2 (SEO Metadata)  : ❌ FAIL ({lat_seo}s) -> {e}")
                    break

        results.append({
            "entity_id": entity_id,
            "provider": "google",
            "ping": ping_ok,
            "script": script_ok,
            "script_score": script_audit["score"],
            "seo": seo_ok,
            "seo_score": seo_audit["score"],
            "latency": lat_script or lat_ping,
            "throughput": script_throughput or seo_throughput,
            "thinking": thinking_meta["is_thinking"],
            "thinking_type": thinking_meta["method"],
            "thinking_tokens": thinking_meta["thought_tokens"],
            "quota_exhausted": quota_exhausted_for_model
        })
        time.sleep(3.0)

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
        "Content-Type": "application/json",
        "User-Agent": "Ghost-Engine/2.0"
    }
    if extra_headers:
        headers.update(extra_headers)

    provider_daily_limit_hit = False

    for model_name in models_to_test:
        if provider_daily_limit_hit:
            print(f"\n   ⏭️ Skipping remaining [{provider_name}] models due to daily provider quota ceiling.")
            break

        entity_id = f"{provider_name}:{model_name}"
        entity = tracker.get_entity(entity_id)
        is_known_thinking = getattr(entity, "supports_thinking", False) if entity else False
        quota_exhausted_for_model = False

        print(f"\n   ┌── Model: [{entity_id}]")

        # ── 1. Minimal Ping & Rate Limit Header Sniffing ──────────────────────
        ping_ok = False
        t0 = time.time()
        lat_ping = 0.0
        thinking_meta = {"is_thinking": False, "method": "none", "thought_tokens": 0, "thought_snippet": ""}

        for attempt in range(3):
            try:
                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json={"model": model_name, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10},
                    timeout=(10.0, 25.0)
                )
                lat_ping = round(time.time() - t0, 2)
                if resp.status_code == 200:
                    c_type = resp.headers.get("content-type", "").lower()
                    body_text = (resp.text or "").strip()
                    if "application/json" not in c_type or not (body_text.startswith("{") or body_text.startswith("[")):
                        print(f"   ├── Task 0 (Minimal Ping)  : ❌ FAIL ({lat_ping}s) -> HTTP 200 Non-JSON: '{body_text[:60]}'")
                        break
                    try:
                        resp_json = resp.json()
                    except Exception as j_err:
                        print(f"   ├── Task 0 (Minimal Ping)  : ❌ FAIL ({lat_ping}s) -> JSON decode error: {j_err}")
                        break

                    t_detect = ThinkingDetector.detect_openai_response(resp_json)
                    if t_detect["is_thinking"]:
                        thinking_meta = t_detect
                        is_known_thinking = True

                    think_str = f" | 🧠 Thinking Detected ({t_detect['thought_tokens']} tok)" if t_detect["is_thinking"] else ""
                    print(f"   ├── Task 0 (Minimal Ping)  : ✅ PASS ({lat_ping}s){think_str}")

                    sniffed_rpm = resp.headers.get("x-ratelimit-limit-requests") or resp.headers.get("x-ratelimit-limit") or "N/A"
                    sniffed_rem = resp.headers.get("x-ratelimit-remaining-requests") or resp.headers.get("x-ratelimit-remaining") or "N/A"
                    print(f"   │   📡 Sniffed Headers -> RPM Limit: {sniffed_rpm} | Remaining: {sniffed_rem}")

                    tracker.sniff_headers(entity_id, resp.headers)
                    tracker.record_call_success(
                        entity_id, "ping", lat_ping, quality_rating=9.5,
                        supports_thinking=t_detect["is_thinking"],
                        thinking_type=t_detect["method"],
                        thinking_tokens=t_detect["thought_tokens"]
                    )
                    ping_ok = True
                    break
                elif resp.status_code in (502, 503, 504) and attempt < 2:
                    wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                    print(f"   │   ⏳ Task 0 hit HTTP {resp.status_code}. Retrying in {wait_s:.1f}s...")
                    time.sleep(wait_s)
                    continue
                elif resp.status_code == 429:
                    err_snippet = resp.text[:200]
                    if any(x in err_snippet.lower() for x in ["free-models-per-day", "daily"]):
                        print(f"   ├── Task 0 (Minimal Ping)  : 🛑 DAILY LIMIT ({lat_ping}s) -> HTTP 429: {err_snippet}")
                        print(f"   🛑 [CIRCUIT BREAKER] {provider_name.title()} daily free-tier limit reached ('free-models-per-day'). Skipping remaining models.")
                        provider_daily_limit_hit = True
                        quota_exhausted_for_model = True
                        break
                    else:
                        print(f"   ├── Task 0 (Minimal Ping)  : 🛑 QUOTA EXHAUSTED ({lat_ping}s) -> HTTP 429: {err_snippet[:100]}")
                        tracker.record_call_error(entity_id, 429, resp.text)
                        quota_exhausted_for_model = True
                        break
                else:
                    print(f"   ├── Task 0 (Minimal Ping)  : ❌ FAIL ({lat_ping}s) -> HTTP {resp.status_code}: {resp.text[:120]}")
                    break
            except Exception as e:
                err_str = str(e)
                if any(x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                    lat_ping = round(time.time() - t0, 2)
                    print(f"   ├── Task 0 (Minimal Ping)  : 🛑 QUOTA EXHAUSTED ({lat_ping}s) -> Daily Limit Reached (429)")
                    tracker.record_call_error(entity_id, 429, err_str)
                    quota_exhausted_for_model = True
                    break
                if any(x in err_str.lower() for x in ["502", "503", "504", "timeout", "unavailable"]) and attempt < 2:
                    wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                    print(f"   │   ⏳ Task 0 transient network issue. Retrying in {wait_s:.1f}s...")
                    time.sleep(wait_s)
                    continue
                lat_ping = round(time.time() - t0, 2)
                print(f"   ├── Task 0 (Minimal Ping)  : ❌ FAIL ({lat_ping}s) -> {e}")
                break

        # ── 2. Scriptwriting Quality Audit ────────────────────────────────────
        script_ok = False
        t1 = time.time()
        lat_script = 0.0
        script_audit = {"score": 0.0, "word_count": 0, "scene_count": 0, "feedback": []}
        script_throughput = 0.0

        if quota_exhausted_for_model or provider_daily_limit_hit:
            print(f"   │   🛑 Quota exhausted for [{entity_id}]. Skipping remaining tasks.")
        else:
            time.sleep(1.5)
            for attempt in range(3):
                try:
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": "You are a professional YouTube Shorts scriptwriter. Output exactly 4 scenes between 85-125 words total as JSON with a 'scenes' array."},
                            {"role": "user", "content": "Write a 4-scene video script about Turritopsis dohrnii immortal jellyfish."}
                        ],
                        "temperature": 0.7
                    }
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=(10.0, 120.0))
                    lat_script = round(time.time() - t1, 2)
                    if resp.status_code == 200:
                        c_type = resp.headers.get("content-type", "").lower()
                        body_text = (resp.text or "").strip()
                        if "application/json" not in c_type or not (body_text.startswith("{") or body_text.startswith("[")):
                            print(f"   ├── Task 1 (Scriptwriting) : ❌ FAIL ({lat_script}s) -> HTTP 200 Non-JSON: '{body_text[:60]}'")
                            break
                        try:
                            resp_json = resp.json()
                        except Exception as j_err:
                            print(f"   ├── Task 1 (Scriptwriting) : ❌ FAIL ({lat_script}s) -> JSON decode error: {j_err}")
                            break

                        content = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                        est_tokens = max(1, len(content) // 4)
                        script_throughput = round(est_tokens / max(lat_script, 0.1), 1)

                        # Dynamic wire-level thinking check
                        t_detect = ThinkingDetector.detect_openai_response(resp_json, content)
                        if t_detect["is_thinking"]:
                            thinking_meta = t_detect
                            is_known_thinking = True

                        parsed_script = UniversalGreedyJSONParser.extract_or_synthesize(content, expected_type="script", fallback_topic="Turritopsis dohrnii")
                        script_audit = QualityEvaluator.audit_script(parsed_script, raw_text=content)
                        score = script_audit["score"]

                        fb_summary = " | ".join(script_audit["feedback"][:3])
                        print(f"   ├── Task 1 (Scriptwriting) : ✅ PASS ({lat_script}s) | Score: {score}/10 | {script_audit['word_count']} words | {script_audit['scene_count']} scenes | ~{script_throughput} tok/s")
                        print(f"   │   📊 Gate Audit: {fb_summary}")
                        if thinking_meta["is_thinking"]:
                            print(f"   │   🧠 Thinking Telemetry: {thinking_meta['method']} (~{thinking_meta['thought_tokens']} tokens) | Snippet: \"{thinking_meta['thought_snippet'][:80]}...\"")

                        tracker.sniff_headers(entity_id, resp.headers)
                        tracker.record_call_success(
                            entity_id, "scriptwriting", lat_script, quality_rating=score,
                            supports_thinking=thinking_meta["is_thinking"],
                            thinking_type=thinking_meta["method"],
                            thinking_tokens=thinking_meta["thought_tokens"]
                        )
                        script_ok = True
                        break
                    elif resp.status_code in (502, 503, 504) and attempt < 2:
                        wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                        print(f"   │   ⏳ Task 1 hit HTTP {resp.status_code}. Retrying in {wait_s:.1f}s...")
                        time.sleep(wait_s)
                        continue
                    elif resp.status_code == 429:
                        err_snippet = resp.text[:200]
                        if any(x in err_snippet.lower() for x in ["free-models-per-day", "daily"]):
                            print(f"   ├── Task 1 (Scriptwriting) : 🛑 DAILY LIMIT ({lat_script}s) -> HTTP 429: {err_snippet}")
                            print(f"   🛑 [CIRCUIT BREAKER] {provider_name.title()} daily free-tier limit reached ('free-models-per-day'). Skipping remaining models.")
                            provider_daily_limit_hit = True
                            quota_exhausted_for_model = True
                            break
                        else:
                            print(f"   ├── Task 1 (Scriptwriting) : 🛑 QUOTA EXHAUSTED ({lat_script}s) -> HTTP 429: {err_snippet[:100]}")
                            tracker.record_call_error(entity_id, 429, resp.text)
                            quota_exhausted_for_model = True
                            break
                    else:
                        print(f"   ├── Task 1 (Scriptwriting) : ❌ FAIL ({lat_script}s) -> HTTP {resp.status_code}")
                        break
                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                        lat_script = round(time.time() - t1, 2)
                        print(f"   ├── Task 1 (Scriptwriting) : 🛑 QUOTA EXHAUSTED ({lat_script}s) -> Daily Limit Reached (429)")
                        tracker.record_call_error(entity_id, 429, err_str)
                        quota_exhausted_for_model = True
                        break
                    if any(x in err_str.lower() for x in ["502", "503", "504", "timeout", "unavailable"]) and attempt < 2:
                        wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                        print(f"   │   ⏳ Task 1 transient network issue. Retrying in {wait_s:.1f}s...")
                        time.sleep(wait_s)
                        continue
                    lat_script = round(time.time() - t1, 2)
                    print(f"   ├── Task 1 (Scriptwriting) : ❌ FAIL ({lat_script}s) -> {e}")
                    break

        # ── 3. Structured SEO JSON Quality Audit ──────────────────────────────
        seo_ok = False
        t2 = time.time()
        lat_seo = 0.0
        seo_audit = {"score": 0.0, "title": "", "tag_count": 0, "feedback": []}
        seo_throughput = 0.0

        if not quota_exhausted_for_model and not provider_daily_limit_hit:
            time.sleep(1.5)
            for attempt in range(3):
                try:
                    payload = {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": "Return ONLY valid JSON matching: {\"title\": \"...\", \"description\": \"...\", \"tags\": [\"...\"]}"},
                            {"role": "user", "content": "Generate viral YouTube SEO metadata for Turritopsis dohrnii immortal jellyfish."}
                        ],
                        "temperature": 0.2
                    }
                    resp = requests.post(endpoint, headers=headers, json=payload, timeout=(10.0, 120.0))
                    lat_seo = round(time.time() - t2, 2)
                    if resp.status_code == 200:
                        c_type = resp.headers.get("content-type", "").lower()
                        body_text = (resp.text or "").strip()
                        if "application/json" not in c_type or not (body_text.startswith("{") or body_text.startswith("[")):
                            print(f"   └── Task 2 (SEO Metadata)  : ❌ FAIL ({lat_seo}s) -> HTTP 200 Non-JSON: '{body_text[:60]}'")
                            break
                        try:
                            resp_json = resp.json()
                        except Exception as j_err:
                            print(f"   └── Task 2 (SEO Metadata)  : ❌ FAIL ({lat_seo}s) -> JSON decode error: {j_err}")
                            break

                        content = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                        est_tokens = max(1, len(content) // 4)
                        seo_throughput = round(est_tokens / max(lat_seo, 0.1), 1)

                        parsed_seo = UniversalGreedyJSONParser.extract_or_synthesize(content, expected_type="seo", fallback_topic="Turritopsis dohrnii")
                        seo_audit = QualityEvaluator.audit_seo(parsed_seo, raw_text=content)
                        score = seo_audit["score"]

                        fb_summary = " | ".join(seo_audit["feedback"][:3])
                        print(f"   └── Task 2 (SEO Metadata)  : ✅ PASS ({lat_seo}s) | Score: {score}/10 | Title: \"{seo_audit.get('title', '')[:35]}...\" | {seo_audit.get('tag_count', 0)} tags | ~{seo_throughput} tok/s")
                        print(f"       📊 Gate Audit: {fb_summary}")

                        tracker.sniff_headers(entity_id, resp.headers)
                        tracker.record_call_success(entity_id, "seo_json", lat_seo, quality_rating=score)
                        seo_ok = True
                        break
                    elif resp.status_code in (502, 503, 504) and attempt < 2:
                        wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                        print(f"   │   ⏳ Task 2 hit HTTP {resp.status_code}. Retrying in {wait_s:.1f}s...")
                        time.sleep(wait_s)
                        continue
                    elif resp.status_code == 429:
                        err_snippet = resp.text[:200]
                        if any(x in err_snippet.lower() for x in ["free-models-per-day", "daily"]):
                            print(f"   └── Task 2 (SEO Metadata)  : 🛑 DAILY LIMIT ({lat_seo}s) -> HTTP 429: {err_snippet}")
                            print(f"   🛑 [CIRCUIT BREAKER] {provider_name.title()} daily free-tier limit reached ('free-models-per-day'). Skipping remaining models.")
                            provider_daily_limit_hit = True
                            quota_exhausted_for_model = True
                            break
                        else:
                            print(f"   └── Task 2 (SEO Metadata)  : 🛑 QUOTA EXHAUSTED ({lat_seo}s) -> HTTP 429: {err_snippet[:100]}")
                            tracker.record_call_error(entity_id, 429, resp.text)
                            quota_exhausted_for_model = True
                            break
                    else:
                        print(f"   └── Task 2 (SEO Metadata)  : ❌ FAIL ({lat_seo}s) -> HTTP {resp.status_code}")
                        break
                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str.lower() for x in ["429", "resource_exhausted", "quota"]):
                        lat_seo = round(time.time() - t2, 2)
                        print(f"   └── Task 2 (SEO Metadata)  : 🛑 QUOTA EXHAUSTED ({lat_seo}s) -> Daily Limit Reached (429)")
                        tracker.record_call_error(entity_id, 429, err_str)
                        quota_exhausted_for_model = True
                        break
                    if any(x in err_str.lower() for x in ["502", "503", "504", "timeout", "unavailable"]) and attempt < 2:
                        wait_s = _calc_diagnostic_backoff(attempt, is_thinking=is_known_thinking)
                        print(f"   │   ⏳ Task 2 transient network issue. Retrying in {wait_s:.1f}s...")
                        time.sleep(wait_s)
                        continue
                    lat_seo = round(time.time() - t2, 2)
                    print(f"   └── Task 2 (SEO Metadata)  : ❌ FAIL ({lat_seo}s) -> {e}")
                    break

        results.append({
            "entity_id": entity_id,
            "provider": provider_name,
            "ping": ping_ok,
            "script": script_ok,
            "script_score": script_audit["score"],
            "seo": seo_ok,
            "seo_score": seo_audit["score"],
            "latency": lat_script or lat_ping,
            "throughput": script_throughput or seo_throughput,
            "thinking": thinking_meta["is_thinking"],
            "thinking_type": thinking_meta["method"],
            "thinking_tokens": thinking_meta["thought_tokens"],
            "quota_exhausted": quota_exhausted_for_model
        })
        time.sleep(2.0)

    return results


def main():
    suite_start = time.time()
    print(DIVIDER_HEAVY)
    print("🚀 GHOST ENGINE — MULTI-PROVIDER MODEL DIAGNOSTICS & EMPIRICAL HEALTH BENCHMARK")
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
        print("\n   ℹ️ GitHub Models: No active models discovered. Skipping.")

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

    # ── Final Comparative Benchmark Matrix ────────────────────────────────────
    suite_elapsed = round(time.time() - suite_start, 2)
    print_header(f"Final Comparative Summary Matrix (Total Suite Duration: {suite_elapsed}s)")
    print(f"{'Namespaced Model URI':<42} | {'Ping':<6} | {'Script Score':<12} | {'SEO Score':<10} | {'Latency':<8} | {'Speed':<9} | {'Thinking'}")
    print(f"{'-'*42}-+-{'-'*6}-+-{'-'*12}-+-{'-'*10}-+-{'-'*8}-+-{'-'*9}-+-{'-'*12}")

    for r in all_results:
        p = "PASS" if r["ping"] else "FAIL"
        s = f"{r['script_score']:.1f}/10" if r["script"] else "FAIL"
        j = f"{r['seo_score']:.1f}/10" if r["seo"] else "FAIL"
        lat_str = f"{r['latency']:.2f}s"
        spd_str = f"{r.get('throughput', 0.0):.0f} tok/s"
        think_str = f"YES ({r.get('thinking_type', 'active')})" if r.get("thinking") else "NO"
        print(f"{r['entity_id']:<42} | {p:<6} | {s:<12} | {j:<10} | {lat_str:<8} | {spd_str:<9} | {think_str}")

    print(f"\n{DIVIDER_HEAVY}")
    print(f"✅ Diagnostic Suite Completed in {suite_elapsed}s across {len(all_results)} evaluated models.")
    print(DIVIDER_HEAVY)

    # Sync dynamic registry to disk with freshly calibrated empirical quality scores
    from engine.dynamic_discovery import calibrate_registry_from_benchmark
    sync_res = calibrate_registry_from_benchmark(all_results)
    print(f"🔄 [REGISTRY CALIBRATION] Synchronized {sync_res.get('total_calibrated', 0)} evaluated models ({sync_res.get('total_entities', 0)} total) to memory/dynamic_models_registry.json")


if __name__ == "__main__":
    main()
