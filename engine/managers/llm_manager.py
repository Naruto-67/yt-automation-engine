"""
engine/managers/llm_manager.py — Dynamic Multi-Provider LLM Orchestrator (v2.0)
Harvested and adapted directly from the PikaFlow pipeline architecture.

Zero hardcoding of models:
1. Dynamically reads available providers from config/llm_providers.json and config/banned_models.json.
2. If uninitialized or cache empty, triggers dynamic discovery and health-checking automatically.
3. Ranks candidates dynamically based on empirical latency, priority, and success rate.
4. Auto-bans any model returning 404 or decommissioned errors at runtime directly into config/banned_models.json.
5. Recursively and smoothly cascades across providers without terminating the process.
6. Ultra-resilient 4-level greedy JSON parsing and syntax auto-repair.
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Callable

from engine.discovery import (
    run_discovery,
    add_banned_model,
    _load_banned_models,
    _load_providers,
    _save_providers,
    _http_request
)

logger = logging.getLogger("LLMManager")
_CFG_DIR = Path(__file__).parent.parent.parent / "config"


class UniversalGreedyJSONParser:
    """
    Ultra-Resilient 4-Level JSON & Syntax Auto-Repair Parser.
    Level 1: Direct JSON parsing.
    Level 2: Markdown fence stripping & greedy brace isolation.
    Level 3: Syntax auto-repair (trailing commas, single quotes, Python literals, token truncation).
    Level 4: Heuristic Plain-Text Fallback Synthesizer for scripts and SEO metadata.
    """

    @classmethod
    def extract_json(cls, raw_text: str) -> Optional[Dict[str, Any]]:
        if not raw_text or not isinstance(raw_text, str):
            return None

        cleaned = raw_text.strip()

        # Level 1: Direct parse
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # Level 2: Markdown fence extraction
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
            if match:
                fenced = match.group(1).strip()
                try:
                    return json.loads(fenced)
                except Exception:
                    cleaned = fenced

        # Level 2b: Greedy isolation of outermost { ... }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start:end + 1]
            try:
                return json.loads(snippet)
            except Exception:
                pass

            # Level 3: Syntax Auto-Repair
            repaired = cls._repair_syntax(snippet)
            try:
                return json.loads(repaired)
            except Exception:
                pass

        # Level 3b: Incomplete JSON with open bracket but no closing bracket (token truncation)
        if start != -1:
            snippet = cleaned[start:]
            repaired = cls._repair_truncated_json(snippet)
            try:
                return json.loads(repaired)
            except Exception:
                pass

        return None

    @classmethod
    def _repair_syntax(cls, snippet: str) -> str:
        s = re.sub(r",\s*([\]}])", r"\1", snippet)
        s = re.sub(r'\bTrue\b', 'true', s)
        s = re.sub(r'\bFalse\b', 'false', s)
        s = re.sub(r'\bNone\b', 'null', s)
        if "'" in s and '"' not in s:
            s = s.replace("'", '"')
        elif "'" in s:
            s = re.sub(r"'\s*([a-zA-Z0-9_\-]+)\s*'\s*:", r'"\1":', s)
        return s

    @classmethod
    def _repair_truncated_json(cls, snippet: str) -> str:
        s = cls._repair_syntax(snippet)
        s = s.rstrip(' ,\n\r\t')

        quotes = len(re.findall(r'(?<!\\)"', s))
        if quotes % 2 != 0:
            s += '"'
            s = s.rstrip(' ,\n\r\t')

        stack: List[str] = []
        escape = False
        in_string = False
        for ch in s:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch in ('{', '['):
                    stack.append('}' if ch == '{' else ']')
                elif ch in ('}', ']'):
                    if stack and stack[-1] == ch:
                        stack.pop()

        while stack:
            s += stack.pop()

        return s

    @classmethod
    def synthesize_script_from_prose(cls, raw_text: str, fallback_topic: str = "curiosity") -> Dict[str, Any]:
        """Level 4 Fallback: synthesizes valid script scenes from narrative text."""
        if not raw_text:
            return {
                "scenes": [
                    {"spoken_text": f"Did you know the secret of {fallback_topic}?", "stock_video_query": fallback_topic}
                ]
            }

        clean = re.sub(r'```.*?```', '', raw_text, flags=re.DOTALL)
        clean = re.sub(r'<(think|thought|THINKING)>.*?</\1>', '', clean, flags=re.DOTALL | re.IGNORECASE).strip()

        scene_splits = re.split(r'(?:^|\n+)(?:Scene\s*\d+|Act\s*\d+|\[\d+\]|\d+\.)[:\s\-]*', clean, flags=re.IGNORECASE)
        scene_chunks = [s.strip() for s in scene_splits if s and len(s.strip()) > 10]

        if len(scene_chunks) < 8:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean) if s.strip() and len(s.split()) >= 4]
            if len(sentences) >= 6:
                scene_chunks = sentences[:12]
            else:
                paras = [p.strip() for p in clean.split('\n\n') if len(p.strip()) > 15]
                if len(paras) >= 3:
                    scene_chunks = paras
                elif len(sentences) >= 3:
                    scene_chunks = sentences[:12]
                else:
                    scene_chunks = [clean]

        final_scenes = []
        for text in scene_chunks[:12]:
            first_words = " ".join(text.split()[:5])
            final_scenes.append({
                "spoken_text": text,
                "stock_video_query": f"{fallback_topic} {first_words}".strip(),
                "image_prompt": f"Cinematic shot illustrating: {text[:60]}"
            })

        return {"scenes": final_scenes}

    @classmethod
    def extract_or_synthesize(cls, raw_text: str, expected_type: str = "json", fallback_topic: str = "curiosity") -> Dict[str, Any]:
        parsed = cls.extract_json(raw_text)
        if isinstance(parsed, dict):
            return parsed
        if expected_type in ("script", "scenes"):
            return cls.synthesize_script_from_prose(raw_text, fallback_topic=fallback_topic)
        return {"raw_content": raw_text}


class LLMManager:
    """Centralized dynamic LLM manager with zero hardcoded models and automatic failover."""

    @classmethod
    def extract_json_payload(cls, raw_text: str) -> Optional[Dict[str, Any]]:
        """Extracts and repairs JSON payload embedded in raw text or markdown."""
        return UniversalGreedyJSONParser.extract_json(raw_text)

    def __init__(self):
        self._disabled_for_run: Set[str] = set()
        self._providers = self._get_active_providers()

    def _get_active_providers(self) -> List[Dict[str, Any]]:
        """Loads and filters enabled providers from llm_providers.json against banned_models.json."""
        banned = _load_banned_models()
        all_provs = _load_providers()

        active = []
        for p in all_provs:
            if not p.get("enabled", True) or p.get("deprecated", False):
                continue
            model_name = p.get("model", "")
            if model_name in banned or any(b.lower() == model_name.lower() for b in banned):
                continue

            sec_key = p.get("secret_key")
            # Must have API key in environment
            if sec_key and not os.environ.get(sec_key):
                continue

            active.append(p)

        # Sort by priority ascending (1 = highest priority)
        active.sort(key=lambda x: x.get("priority", 99))
        return active

    def benchmark_and_reorder(self) -> List[Dict[str, Any]]:
        """
        Runs empirical functional benchmarks across all candidate models,
        updates latency and reliability metrics, and regenerates the priority chain.
        """
        print("⚡ [LLM] Running empirical functional benchmark across all models...")
        run_discovery(force=True)
        self._disabled_for_run.clear()
        self._providers = self._get_active_providers()
        return self._providers

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        validator: Optional[Callable[[Dict[str, Any]], bool]] = None
    ) -> Dict[str, Any]:
        """
        Executes generation dynamically across discovered providers:
        PikaFlow interleaved family priority -> auto-banning dead models on 404 -> cascading.
        Optionally validates extracted JSON against custom predicate before accepting.
        """
        candidates = [p for p in self._get_active_providers() if p["id"] not in self._disabled_for_run]

        # If no candidates available in cache, trigger dynamic discovery
        if not candidates:
            print("🔄 [LLM] No active providers found in cache. Running dynamic discovery & health-check...")
            disc_res = run_discovery(force=True)
            candidates = [p for p in self._get_active_providers() if p["id"] not in self._disabled_for_run]

        if not candidates:
            raise RuntimeError("No viable LLM providers available. Check your API keys and banned_models.json.")

        last_error = None
        for provider in candidates:
            prov_id = provider["id"]
            model_name = provider.get("model", "")
            prov_name = provider.get("name", prov_id)
            prio = provider.get("priority", "?")

            print(f"🤖 [LLM] Routing request to {prov_name} (Model: {model_name})...")
            print(f"🤖 [LLM] Routing request to {prov_name} (Priority #{prio}, Model: {model_name})...")
            try:
                response_text = self._execute_provider_call(
                    provider=provider,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature
                )

                if response_text and response_text.strip():
                    parsed = UniversalGreedyJSONParser.extract_json(response_text)
                    if parsed:
                        if validator and not validator(parsed):
                            print(f"⚠️ [LLM VALIDATOR] {prov_name} output rejected by validator criteria. Cascading...")
                            continue
                        return parsed
                    # If JSON couldn't be parsed directly, try heuristic synthesis
                    synth = UniversalGreedyJSONParser.extract_or_synthesize(response_text, expected_type="script")
                    if synth and "scenes" in synth:
                        if validator and not validator(synth):
                            print(f"⚠️ [LLM VALIDATOR] {prov_name} synthesized output rejected by validator criteria. Cascading...")
                            continue
                        return synth

                    print(f"⚠️ [LLM] {prov_name} returned unparseable output. Cascading to next candidate...")

            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                print(f"⚠️ [LLM] {prov_name} ({model_name}) failed: {e}")

                # 404 / Decommissioned handling — permanently ban model into banned_models.json
                if any(x in err_str for x in ["404", "model_not_found", "not found", "decommissioned", "no longer available"]):
                    print(f"💀 [MODEL BENCHED 404] Permanently banning {model_name} from all future routing.")
                    add_banned_model(model_name)
                    self._disabled_for_run.add(prov_id)
                elif "429" in err_str or "quota" in err_str:
                    print(f"⏳ [QUOTA EXHAUSTED] Disabling {prov_id} for the remainder of this run.")
                    self._disabled_for_run.add(prov_id)
                else:
                    self._disabled_for_run.add(prov_id)

        raise RuntimeError(f"All dynamic LLM providers failed. Last error: {last_error}")

    def _execute_provider_call(
        self,
        provider: Dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        temperature: float
    ) -> str:
        """Executes a request to a provider using its endpoint and auth configuration."""
        api_key = os.environ.get(provider.get("secret_key", ""), "")
        base_url = provider.get("base_url", "")
        endpoint = provider.get("endpoint", "")
        model_name = provider.get("model", "")

        is_gemini = "generativelanguage" in base_url
        is_openai_compat = any(k in base_url for k in ["api.groq.com", "openrouter", "api.openai.com"])

        # URL Sanitization
        if not base_url.endswith("/"):
            base_url += "/"
        if endpoint.startswith("/"):
            endpoint = endpoint[1:]
        url = base_url + endpoint

        headers = {"Content-Type": "application/json"}
        auth_header = provider.get("auth_header", "")
        if auth_header and api_key:
            if auth_header.lower() == "authorization":
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                headers[auth_header] = api_key

        if "openrouter" in base_url:
            headers["HTTP-Referer"] = "https://github.com/Naruto-67/yt-automation-engine"
            headers["X-Title"] = "YT Automation Engine"

        # Build payload
        if is_gemini:
            if api_key:
                sep = "&" if "?" in url else "?"
                url += f"{sep}key={api_key}"
            full_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_prompt}"
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": full_prompt}]}
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                    "maxOutputTokens": 2048
                }
            }
        else:
            max_tok = 2048
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tok
            }
            # Add json_object response_format if not free openrouter model
            if "openrouter" not in base_url or not str(model_name).endswith(":free"):
                payload["response_format"] = {"type": "json_object"}

        resp = _http_request(url, method="POST", headers=headers, json_data=payload, timeout=60.0)

        # Auto-heal Groq HTTP 400 json_validate_failed (thinking models or server-side schema incompatibilities)
        if resp.status_code == 400 and "json_validate_failed" in getattr(resp, "text", "") and "response_format" in payload:
            payload.pop("response_format", None)
            resp = _http_request(url, method="POST", headers=headers, json_data=payload, timeout=60.0)

        if resp.status_code == 200:
            data = resp.json()
            if is_gemini:
                try:
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                except Exception as ex:
                    raise RuntimeError(f"Gemini response parsing error: {ex}")
            else:
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    return choices[0]["message"].get("content", "")
            return resp.text

        # Error response
        clean_text = re.sub(r'https?://\S+', '[link]', str(resp.text))
        err_msg = f"HTTP {resp.status_code}: {clean_text}"
        raise RuntimeError(f"Provider {provider['name']} ({model_name}) error: {err_msg}")

    # Backward compatibility helper methods
    def _call_groq(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        prov = next((p for p in self._get_active_providers() if "groq" in p["id"]), None)
        if not prov:
            raise RuntimeError("No active Groq provider found.")
        return self._execute_provider_call(prov, system_prompt, user_prompt, temperature)

    def _call_gemini(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        prov = next((p for p in self._get_active_providers() if "gemini" in p["id"]), None)
        if not prov:
            raise RuntimeError("No active Gemini provider found.")
        return self._execute_provider_call(prov, system_prompt, user_prompt, temperature)

    def _call_openrouter(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        prov = next((p for p in self._get_active_providers() if "openrouter" in p["id"]), None)
        if not prov:
            raise RuntimeError("No active OpenRouter provider found.")
        return self._execute_provider_call(prov, system_prompt, user_prompt, temperature)

    def _call_openai(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        prov = next((p for p in self._get_active_providers() if "openai" in p["id"]), None)
        if not prov:
            raise RuntimeError("No active OpenAI provider found.")
        return self._execute_provider_call(prov, system_prompt, user_prompt, temperature)
