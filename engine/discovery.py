"""
engine/discovery.py — Dynamic Model Discovery & Empirical Health-Check Engine
Derived from PikaFlow pipeline architecture.

Discovers active LLM models across Google GenAI, Groq Cloud, OpenRouter, and OpenAI.
Sends health-check probes, benchmarks latency, automatically bans deprecated/404 models,
interleaves provider families, and maintains config/llm_providers.json & config/banned_models.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from engine.logger import logger

_CFG_DIR = Path(__file__).parent.parent / "config"

# Modality & non-text patterns strictly rejected from LLM text routing
BANNED_MODALITY_PATTERNS = [
    r"image", r"picture", r"tts", r"audio", r"live", r"embed",
    r"robotics", r"video", r"veo", r"whisper", r"transcribe",
    r"guard", r"safeguard", r"deepseek-r1-distill-qwen-1\.5b",
    r"omni", r"imagen",
    r"orpheus", r"canopylabs", r"speech", r"voice", r"sound", r"realtime",
    r"inkling", r"lyria", r"banana", r"deep-research", r"antigravity",
    r"computer-use", r"customtools", r"content-safety",
    r"allam",
]

# Initial legacy seeds
DEPRECATED_KNOWN = {
    "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro",
    "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.0-pro",
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "mixtral-8x7b-32768", "gemma2-9b-it", "llama3-70b-8192", "llama3-8b-8192",
    "llama-3.1-70b-versatile", "mistralai/mistral-7b-instruct:free"
}


def _http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: float = 12.0
):
    """Resilient HTTP request supporting both requests library and standard library urllib."""
    headers = headers or {}
    try:
        import requests
        if method.upper() == "GET":
            return requests.get(url, headers=headers, timeout=timeout)
        else:
            return requests.post(url, headers=headers, json=json_data, timeout=timeout)
    except ImportError:
        import urllib.request
        import urllib.error
        data_bytes = json.dumps(json_data).encode("utf-8") if json_data is not None else None
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.getcode()
                body = resp.read().decode("utf-8")
                class _Response:
                    def __init__(self, sc: int, text: str):
                        self.status_code = sc
                        self.text = text
                    def json(self):
                        return json.loads(self.text)
                return _Response(status_code, body)
        except urllib.error.HTTPError as he:
            body = he.read().decode("utf-8")
            class _ErrorResponse:
                def __init__(self, sc: int, text: str):
                    self.status_code = sc
                    self.text = text
                def json(self):
                    return json.loads(self.text) if self.text else {}
            return _ErrorResponse(he.code, body)
        except Exception as e:
            class _FailResponse:
                def __init__(self, err: str):
                    self.status_code = 0
                    self.text = err
                def json(self):
                    return {}
            return _FailResponse(str(e))


def _load_providers() -> List[Dict[str, Any]]:
    path = _CFG_DIR / "llm_providers.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("providers", [])
    except Exception:
        return []


def _save_providers(providers: List[Dict[str, Any]]) -> None:
    path = _CFG_DIR / "llm_providers.json"
    os.makedirs(_CFG_DIR, exist_ok=True)
    payload = {
        "providers": providers,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "1.0"
        }
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_performance() -> Dict[str, Any]:
    path = _CFG_DIR / "llm_performance.json"
    if not path.exists():
        return {"providers": {}, "_meta": {"last_updated": None, "schema_version": "1.0"}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"providers": {}, "_meta": {"last_updated": None, "schema_version": "1.0"}}


def _save_performance(perf: Dict[str, Any]) -> None:
    path = _CFG_DIR / "llm_performance.json"
    os.makedirs(_CFG_DIR, exist_ok=True)
    perf["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(perf, indent=2), encoding="utf-8")


def _load_banned_models() -> Set[str]:
    path = _CFG_DIR / "banned_models.json"
    banned = set(DEPRECATED_KNOWN)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            banned.update(data.get("banned_models", []))
        except Exception:
            pass
    return banned


def add_banned_model(model_name: str) -> None:
    """Permanently bans a model in config/banned_models.json and flags it in providers."""
    if not model_name or not isinstance(model_name, str):
        return
    path = _CFG_DIR / "banned_models.json"
    current_banned = list(DEPRECATED_KNOWN)
    if path.exists():
        try:
            current_banned = json.loads(path.read_text(encoding="utf-8")).get("banned_models", current_banned)
        except Exception:
            pass

    clean_name = model_name.strip()
    if clean_name not in current_banned:
        current_banned.append(clean_name)
        os.makedirs(_CFG_DIR, exist_ok=True)
        data = {
            "banned_models": sorted(list(set(current_banned))),
            "_meta": {
                "description": "Permanently banned or decommissioned models. Auto-updated when discovery or LLM manager detects 404/decommissioned responses.",
                "schema_version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.warn(f"🚫 [BANNED REGISTRY] Permanently banned decommissioned model: {clean_name}")


def is_modality_allowed(model_name: str) -> bool:
    """Strictly filters out non-text, TTS, audio, image, and robotics models."""
    lowered = model_name.lower()
    for pattern in BANNED_MODALITY_PATTERNS:
        if re.search(pattern, lowered):
            return False
    return True


def is_model_allowed(model_name: str, banned: Set[str]) -> bool:
    """Validates modality safety and ensures model is not in the ban list."""
    if not is_modality_allowed(model_name):
        return False
    lowered = model_name.lower()
    if lowered in banned or model_name in banned:
        return False
    for b in banned:
        if b.lower() == lowered:
            return False
    return True


def _refresh_model_ids(providers: List[Dict[str, Any]], banned_models: Set[str]) -> List[Dict[str, Any]]:
    """Query each provider's /models endpoint to discover ALL active/free models without hardcoded limits."""
    expanded_providers = []
    seen_models = set()
    queried_services = set()

    for p in providers:
        api_key = os.environ.get(p.get("secret_key", ""), "")
        if not api_key and "openrouter" not in p.get("id", ""):
            expanded_providers.append(p)
            continue

        added = False

        # 1. Google Gemini dynamic discovery via models endpoint
        if "gemini" in p.get("id", ""):
            if "gemini" in queried_services:
                continue
            queried_services.add("gemini")
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                resp = _http_request(url, timeout=10.0)
                if resp.status_code == 200:
                    models = [
                        m["name"].replace("models/", "") for m in resp.json().get("models", [])
                        if "generateContent" in m.get("supportedGenerationMethods", [])
                        and not m["name"].lower().startswith("models/gemma")
                    ]
                    valid_models = [m for m in models if is_model_allowed(m, banned_models)]
                    for m in valid_models:
                        if m in seen_models:
                            continue
                        seen_models.add(m)
                        new_p = p.copy()
                        new_p["id"] = f"gemini_{m.replace('-', '_').replace('.', '_')}"
                        new_p["name"] = f"Google ({m})"
                        new_p["model"] = m
                        new_p["endpoint"] = f"v1beta/models/{m}:generateContent"
                        expanded_providers.append(new_p)
                    if valid_models:
                        added = True
                        print(f"  🔍 Discovered {len(valid_models)} Google Gemini models")
            except Exception as e:
                print(f"  ⚠️ Failed to discover Gemini models: {e}")

        # 2. Groq dynamic discovery via /openai/v1/models
        elif "groq" in p.get("id", ""):
            if "groq" in queried_services:
                continue
            queried_services.add("groq")
            try:
                url = "https://api.groq.com/openai/v1/models"
                resp = _http_request(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10.0)
                if resp.status_code == 200:
                    models = [m["id"] for m in resp.json().get("data", []) if m.get("active", True)]
                    valid_models = [m for m in models if is_model_allowed(m, banned_models)]
                    # Prioritize flagship 70B models over experimental models
                    def _groq_prio(mid: str) -> int:
                        ml = mid.lower()
                        if "llama-3.3-70b" in ml: return 1
                        if "llama-3.1-70b" in ml or "70b" in ml: return 2
                        if "llama-3.1-8b" in ml or "8b" in ml: return 3
                        if "gpt-oss-20b" in ml: return 15
                        return 10
                    valid_models.sort(key=_groq_prio)

                    for m in valid_models:
                        if m in seen_models:
                            continue
                        seen_models.add(m)
                        new_p = p.copy()
                        new_p["id"] = f"groq_{m.replace('-', '_').replace('.', '_')}"
                        new_p["name"] = f"Groq ({m})"
                        new_p["model"] = m
                        expanded_providers.append(new_p)
                    if valid_models:
                        added = True
                        print(f"  🔍 Discovered {len(valid_models)} Groq models")
            except Exception as e:
                print(f"  ⚠️ Failed to discover Groq models: {e}")

        # 3. OpenRouter dynamic discovery via /api/v1/models
        elif "openrouter" in p.get("id", ""):
            if "openrouter" in queried_services:
                continue
            queried_services.add("openrouter")
            try:
                url = "https://openrouter.ai/api/v1/models"
                resp = _http_request(url, timeout=10.0)
                if resp.status_code == 200:
                    free_models = [
                        m["id"] for m in resp.json().get("data", [])
                        if m.get("pricing", {}).get("prompt") == "0" and m.get("pricing", {}).get("completion") == "0"
                    ]
                    valid_models = [m for m in free_models if is_model_allowed(m, banned_models)]
                    # Prioritize 70B/72B open models over tiny 2B/3B models
                    def _or_prio(mid: str) -> int:
                        ml = mid.lower()
                        if "70b" in ml or "72b" in ml: return 1
                        if "qwen" in ml and ("14b" in ml or "32b" in ml): return 2
                        if "8b" in ml or "9b" in ml: return 3
                        if any(x in ml for x in ["2.5b", "2.6b", "1b", "2b", "3b"]): return 25
                        return 10
                    valid_models.sort(key=_or_prio)
                    for m in valid_models:
                        if m in seen_models:
                            continue
                        seen_models.add(m)
                        new_p = p.copy()
                        new_p["id"] = f"or_{m.split('/')[-1].replace('-', '_').replace('.', '_').replace(':', '_')}"
                        new_p["name"] = f"OpenRouter ({m.split('/')[-1]})"
                        new_p["model"] = m
                        expanded_providers.append(new_p)
                    if valid_models:
                        added = True
                        print(f"  🔍 Discovered {len(valid_models)} OpenRouter models")
            except Exception as e:
                print(f"  ⚠️ Failed to discover OpenRouter models: {e}")

        # 4. OpenAI / fallback pass-through
        if not added and p.get("type") == "text":
            if is_model_allowed(p.get("model", ""), banned_models) and p.get("model") not in seen_models:
                seen_models.add(p.get("model"))
                expanded_providers.append(p)

    return expanded_providers


def _extract_json_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Lightweight resilient JSON extractor for empirical health-check probes."""
    if not raw_text or not isinstance(raw_text, str):
        return None
    cleaned = raw_text.strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except Exception:
            pass
    return None


def _health_check(provider: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a minimal request to the provider and return health metrics.
    Returns: {"ok": bool, "latency_ms": int, "status_code": int, "error": str|None}
    Empirical functional test probe:
    Sends a structured JSON generation request to the provider.
    Verifies HTTP 200, parses the JSON payload, checks schema compliance,
    and measures empirical round-trip latency in milliseconds.
    Returns: {"ok": bool, "latency_ms": int, "status_code": int, "json_valid": bool, "error": str|None}
    """
    api_key = os.environ.get(provider.get("secret_key", ""), "")
    auth_header = provider.get("auth_header", "")
    headers = {}

    if auth_header and api_key:
        if auth_header.lower() == "authorization":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers[auth_header] = api_key

    # Test payload
    if "generativelanguage" in provider.get("base_url", ""):
        payload = {"contents": [{"parts": [{"text": "Reply with: OK"}]}]}
    elif any(d in provider.get("base_url", "") for d in ["api.groq.com", "openrouter", "api.openai.com"]):
    is_gemini = "generativelanguage" in provider.get("base_url", "")
    is_openai_compat = any(d in provider.get("base_url", "") for d in ["api.groq.com", "openrouter", "api.openai.com"])

    test_prompt = 'Output valid JSON only with keys "status" ("pass") and "scenes" (array with 1 object: {"scene_id": 1, "spoken_text": "verification test"}).'

    if is_gemini:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": test_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "maxOutputTokens": 150
            }
        }
    elif is_openai_compat:
        payload = {
            "model": provider["model"],
            "messages": [{"role": "user", "content": "Reply with: OK"}],
            "max_tokens": 5,
            "messages": [
                {"role": "system", "content": "You are a JSON evaluator. Output valid JSON only with no conversational text."},
                {"role": "user", "content": test_prompt}
            ],
            "max_tokens": 150,
            "temperature": 0.1
        }
        if "openrouter" not in provider.get("base_url", "") or not str(provider.get("model", "")).endswith(":free"):
            payload["response_format"] = {"type": "json_object"}
    else:
        payload = {"inputs": "Reply with: OK"}
        payload = {"inputs": test_prompt}

    base_url = provider["base_url"]
    endpoint = provider["endpoint"]
    if base_url.endswith("/") and endpoint.startswith("/"):
        url = base_url + endpoint[1:]
    elif not base_url.endswith("/") and not endpoint.startswith("/"):
        url = base_url + "/" + endpoint
    else:
        url = base_url + endpoint

    if "generativelanguage" in provider.get("base_url", "") and api_key:
    if is_gemini and api_key:
        sep = "&" if "?" in url else "?"
        url += f"{sep}key={api_key}"

    if "openrouter" in provider.get("base_url", ""):
        headers["HTTP-Referer"] = "https://github.com/Naruto-67/yt-automation-engine"
        headers["X-Title"] = "YT Automation Engine"

    try:
        start = time.time()
        resp = _http_request(url, method="POST", headers=headers, json_data=payload, timeout=4.0)
        resp = _http_request(url, method="POST", headers=headers, json_data=payload, timeout=8.0)
        latency = int((time.time() - start) * 1000)

        # Retry once without response_format if Groq returns 400 json_validate_failed
        if resp.status_code == 400 and "json_validate_failed" in getattr(resp, "text", "") and "response_format" in payload:
            payload.pop("response_format", None)
            start = time.time()
            resp = _http_request(url, method="POST", headers=headers, json_data=payload, timeout=8.0)
            latency = int((time.time() - start) * 1000)

        if resp.status_code == 200:
            return {"ok": True, "latency_ms": latency, "status_code": 200, "error": None}
            raw_text = ""
            if is_gemini:
                try:
                    cands = resp.json().get("candidates", [])
                    if cands and "content" in cands[0]:
                        parts = cands[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            raw_text = parts[0]["text"]
                except Exception:
                    pass
            elif is_openai_compat:
                try:
                    choices = resp.json().get("choices", [])
                    if choices and "message" in choices[0]:
                        raw_text = choices[0]["message"].get("content", "")
                except Exception:
                    pass
            else:
                raw_text = getattr(resp, "text", "")

            parsed = _extract_json_response(raw_text)
            if parsed and (parsed.get("status") == "pass" or "scenes" in parsed):
                return {"ok": True, "latency_ms": latency, "status_code": 200, "json_valid": True, "error": None}
            else:
                return {"ok": False, "latency_ms": latency, "status_code": 200, "json_valid": False, "error": "Output failed JSON schema validation"}

        elif resp.status_code == 404:
            return {"ok": False, "latency_ms": latency, "status_code": 404, "error": "Model not found / deprecated"}
            return {"ok": False, "latency_ms": latency, "status_code": 404, "json_valid": False, "error": "Model not found / decommissioned"}
        elif resp.status_code == 429:
            return {"ok": False, "latency_ms": 50000, "status_code": 429, "error": "Quota limit (rate-limited)"}
            return {"ok": False, "latency_ms": 50000, "status_code": 429, "json_valid": False, "error": "Quota limit (rate-limited)"}
        else:
            clean_err = "Error"
            try:
                err_json = resp.json().get("error", {})
                if isinstance(err_json, dict):
                    clean_err = err_json.get("message") or err_json.get("status") or str(err_json)
                elif isinstance(err_json, str):
                    clean_err = err_json
            except Exception:
                clean_err = resp.text
                clean_err = getattr(resp, "text", "Unknown error")
            clean_err = re.sub(r'https?://\S+', '[link]', str(clean_err))
            clean_err = " ".join(clean_err.split())[:70]
            return {"ok": False, "latency_ms": latency, "status_code": resp.status_code, "error": clean_err}
            return {"ok": False, "latency_ms": latency, "status_code": resp.status_code, "json_valid": False, "error": clean_err}

    except Exception as exc:
        err_msg = str(exc)
        if "timed out" in err_msg.lower():
            err_msg = "Request timed out"
        else:
            err_msg = re.sub(r'https?://\S+', '[link]', err_msg)
            err_msg = " ".join(err_msg.split())[:70]
        return {"ok": False, "latency_ms": 0, "status_code": 0, "error": err_msg}
        return {"ok": False, "latency_ms": 0, "status_code": 0, "json_valid": False, "error": err_msg}


def run_discovery(force: bool = False) -> Dict[str, Any]:
    """
    Executes live multi-provider discovery, health-checks each candidate,
    empirically ranks and interleaves provider families, and saves active providers.
    Zero hardcoded models: the priority chain is constructed purely from empirical results.
    """
    print("🔍 [PIKA FLOW DISCOVERY] Initiating Dynamic Provider Discovery & Health-Check...")
    print(f"   Timestamp: {datetime.now(timezone.utc).isoformat()}\n")

    base_providers = _load_providers()
    performance = _load_performance()
    banned_models = _load_banned_models()

    # Discover ALL active models dynamically
    providers = _refresh_model_ids(base_providers, banned_models)

    tested_results = []
    for p in providers:
        # Check if provider has secret key configured in environment
        sec_key = p.get("secret_key")
        if sec_key and not os.environ.get(sec_key):
            continue

        result = _health_check(p)
        status = "✅" if result["ok"] else "❌"
        print(f"  {status} {p['name']:35s} | {result['status_code']:3d} | {result['latency_ms']:5d} ms | {result['error'] or 'OK'}")
        json_tag = "JSON:OK" if result.get("json_valid") else "JSON:FAIL"
        print(f"  {status} {p['name']:35s} | {result['status_code']:3d} | {result['latency_ms']:5d} ms | {json_tag:9s} | {result['error'] or 'PASS'}")
        tested_results.append((p, result))

        perf = performance.setdefault("providers", {}).setdefault(p["id"], {})
        perf["avg_latency_ms"] = result["latency_ms"]
        prev_rate = perf.get("success_rate") or (1.0 if result["ok"] else 0.0)
        perf["success_rate"] = round(0.7 * prev_rate + 0.3 * (1.0 if result["ok"] else 0.0), 3)

        # Automatically ban permanently on 404 or decommissioned error
        err_msg = str(result.get("error") or "").lower()
        if result["status_code"] in (400, 404) and ("decommissioned" in err_msg or "not found" in err_msg or result["status_code"] == 404):
            p["deprecated"] = True
            p["enabled"] = False
            add_banned_model(p.get("model", ""))
            banned_models.add(p.get("model", ""))
            print(f"    🚫 Permanently banned & decommissioned: {p['name']} ({p.get('model')})")

        if perf["success_rate"] < 0.2:
        if perf["success_rate"] < 0.2 or not result["ok"]:
            p["enabled"] = False
            print(f"    ⛔ Disabled (low success rate): {p['name']}")
            if not result["ok"]:
                print(f"    ⛔ Disqualified from primary routing (test failed): {p['name']}")

    # Empirical Ranking & Interleaved Family Selection
    # Empirical Ranking based solely on live test results (Zero Hardcoding)
    def perf_rank(item):
        prov, res = item
        if not prov.get("enabled", True) or prov.get("deprecated", False) or prov.get("model") in banned_models:
            return 999999
        if not res.get("ok"):
            return 800000 + res.get("latency_ms", 9999)
        p_perf = performance.get("providers", {}).get(prov["id"], {})
        s_rate = p_perf.get("success_rate", 1.0 if res["ok"] else 0.0)
        lat = res["latency_ms"] if res["latency_ms"] > 0 else 9999
        # Tier bonus: prioritize 70B+ / flagship reasoning models over sub-4B toy models
        m_name = (prov.get("model") or "").lower()
        tier_adj = 0
        if any(x in m_name for x in ["2.6b", "2.5b", "1b", "2b", "3b"]):
            tier_adj = 1500  # Deprioritize sub-4B toy models
        elif any(x in m_name for x in ["70b", "72b", "gemini-3", "gpt-4"]):
            tier_adj = -200  # Priority boost for high-capacity flagships
        return int((1.0 - s_rate) * 1000 + lat + tier_adj)
        s_rate = p_perf.get("success_rate", 1.0)
        lat = res.get("latency_ms", 9999)
        if lat <= 0:
            lat = 9999
        # Empirical score: higher reliability and lower latency wins
        return int((1.0 - s_rate) * 5000 + lat)

    def get_provider_family(p: dict) -> str:
        pid = p.get("id", "").lower()
        burl = p.get("base_url", "").lower()
        if "gemini" in pid or "generativelanguage" in burl:
            return "google"
        elif "groq" in pid or "groq.com" in burl:
            return "groq"
        elif "openrouter" in pid or "openrouter" in burl or pid.startswith("or_"):
            return "openrouter"
        elif "openai" in pid or "api.openai.com" in burl:
            return "openai"
        return "other"

    text_items = [(p, r) for p, r in tested_results if p.get("type") == "text"]

    families: Dict[str, list] = {}
    for item in text_items:
        fam = get_provider_family(item[0])
        families.setdefault(fam, []).append(item)

    for fam in families:
        families[fam].sort(key=perf_rank)

    # Interleave across provider families
    interleaved_text_items = []
    family_order = sorted(
        families.keys(),
        key=lambda f: perf_rank(families[f][0]) if families[f] else 999999
    )

    max_len = max(len(items) for items in families.values()) if families else 0
    for idx in range(max_len):
        for fam in family_order:
            if idx < len(families[fam]):
                interleaved_text_items.append(families[fam][idx])

    final_providers = []
    for rank, (prov, _) in enumerate(interleaved_text_items, start=1):
        prov["priority"] = rank
        final_providers.append(prov)

    # Filter out banned or deprecated
    final_providers = [
        prov for prov in final_providers
        if not prov.get("deprecated", False) and prov.get("model") not in banned_models
    ]

    _save_providers(final_providers)
    _save_performance(performance)

    print("\n" + "=" * 80)
    print("🏆 EMPIRICAL LLM BENCHMARK LEADERBOARD (Dynamic Priority Chain)")
    print("=" * 80)
    for prov in sorted(final_providers, key=lambda x: x.get("priority", 99)):
        status_sym = "🟢" if prov.get("enabled", True) else "⚪"
        print(f"  {status_sym} Priority #{prov.get('priority'):2d}: {prov.get('name', 'Unknown'):35s} (Model: {prov.get('model', 'N/A')})")
    print("=" * 80 + "\n")

    logger.success(f"✅ [DISCOVERY COMPLETE] Ranked {len(final_providers)} active models dynamically across {len(families)} provider families (banned {len(banned_models)} models).")
    return {
        "status": "SUCCESS",
        "active_models_count": len(final_providers),
        "families_count": len(families),
        "banned_count": len(banned_models),
        "providers": [p["name"] for p in final_providers]
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pika Flow LLM Discovery & Empirical Benchmark")
    parser.add_argument("--force", action="store_true", help="Force refresh discovery cache")
    parser.add_argument("--benchmark", action="store_true", help="Run empirical functional benchmark on all models")
    cli_args = parser.parse_args()
    res = run_discovery(force=cli_args.force or cli_args.benchmark)
    print(f"Leaderboard saved to config/llm_providers.json ({res.get('active_models_count', 0)} active models).")
