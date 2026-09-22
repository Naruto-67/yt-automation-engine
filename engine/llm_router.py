# engine/llm_router.py — Autonomous Multi-Tier Multi-Provider LLM Orchestrator
"""
Autonomous Task-Centric LLM Router with Universal Multi-Provider Adapter Layer.
Dynamically routes generation tasks across Google GenAI, Groq Cloud, GitHub Models,
and OpenRouter based on live model entities, empirical task quality scores,
the 85% Scarcity Harvesting Waterfall, and dynamic HTTP response header sniffing.
"""

import os
import re
import json
import time
import random
try:
    import requests
except ImportError:
    requests = None
from typing import Tuple, Optional, Dict, Any, List
from engine.logger import logger
from engine.model_entity import (
    ModelEntity,
    DynamicQuotaTracker,
    SlidingWindowRateLimiter,
    ScarcityWaterfallResolver
)


class UniversalGreedyJSONParser:
    """Robust JSON extractor that handles markdown blocks, stray preambles, and syntax flaws."""
    @staticmethod
    def extract_json(raw_text: str) -> Optional[Dict[str, Any]]:
        if not raw_text or not isinstance(raw_text, str):
            return None

        cleaned = raw_text.strip()

        # 1. Remove markdown fences (```json ... ``` or ``` ... ```)
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
            if match:
                cleaned = match.group(1).strip()

        # 2. Try direct parse
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # 3. Greedy isolate outermost { ... }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start:end + 1]
            try:
                return json.loads(snippet)
            except Exception:
                # 4. Repair trailing commas before closing braces/brackets
                repaired = re.sub(r",\s*([\]}])", r"\1", snippet)
                try:
                    return json.loads(repaired)
                except Exception:
                    pass

        return None


class GoogleGenAIAdapter:
    """Native Google GenAI SDK Adapter with persistent client and dynamic thinking preservation."""
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = None

    def _get_client(self, timeout_ms: int = 120000):
        if self._client is None:
            from google import genai
            from google.genai import types
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=timeout_ms)
            )
        return self._client

    def generate_text(
        self,
        entity: ModelEntity,
        prompt: str,
        system_prompt: Optional[str] = None,
        task_type: str = "general",
        timeout_s: float = 120.0
    ) -> Tuple[Optional[str], Dict[str, Any], float]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        from google.genai import types

        timeout_ms = int(timeout_s * 1000)
        client = self._get_client(timeout_ms)

        cfg_kwargs: Dict[str, Any] = {
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)
        }
        if system_prompt:
            cfg_kwargs["system_instruction"] = system_prompt

        # Full Dynamic Thinking preserved: Gemini 3.x models engage in native thinking by default.
        # Per official Gemini 3.x migration rules, omit temperature, top_p, and top_k when thinking is active
        # to prevent token decoding stalls and 504 deadline exceeded.
        gen_cfg = types.GenerateContentConfig(**cfg_kwargs)

        start_time = time.time()
        response = client.models.generate_content(
            model=entity.model_name,
            contents=prompt,
            config=gen_cfg
        )
        latency = round(time.time() - start_time, 2)

        text = response.text if response and response.text else ""
        return text, {}, latency


class OpenAICompatibleAdapter:
    """
    Unified lightweight HTTP adapter serving Groq Cloud, GitHub Models (Azure AI),
    and OpenRouter with standard OpenAI-compatible completions, persistent session pooling,
    and live response header capture.
    """
    ENDPOINTS = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "github": "https://models.inference.ai.azure.com/chat/completions",
        "openrouter": "https://openrouter.ai/api/v1/chat/completions"
    }

    def __init__(self, keys: Dict[str, str]):
        self.keys = keys
        self._session = None

    def _get_session(self):
        if self._session is None and requests is not None:
            self._session = requests.Session()
        return self._session

    def generate_text(
        self,
        entity: ModelEntity,
        prompt: str,
        system_prompt: Optional[str] = None,
        task_type: str = "general",
        timeout_s: float = 120.0
    ) -> Tuple[Optional[str], Dict[str, Any], float]:
        provider = entity.provider
        api_key = self.keys.get(provider, "")
        if not api_key:
            raise ValueError(f"API key for {provider} is not configured.")

        endpoint = self.ENDPOINTS.get(provider)
        if not endpoint:
            raise ValueError(f"No endpoint configured for provider {provider}.")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Ghost-Engine/2.0"
        }

        # Extra headers for OpenRouter rankings
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/yt-automation-engine"
            headers["X-Title"] = "Ghost Engine Autonomous Pipeline"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Normalize model slug for Azure AI / GitHub Models
        model_name = entity.model_name
        if provider == "github":
            model_name = model_name.replace("/", "-")

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.7 if task_type == "creative" else 0.2
        }

        # Enable structured JSON mode ONLY when supported.
        # OpenRouter free-tier (:free) backends frequently reject response_format with HTTP 503.
        # We rely on UniversalGreedyJSONParser for robust extraction across open models.
        if task_type in ("seo_json", "json"):
            if provider != "openrouter" or not model_name.endswith(":free"):
                payload["response_format"] = {"type": "json_object"}

        session = self._get_session()
        if session is None:
            raise RuntimeError("The 'requests' library is required to execute OpenAICompatibleAdapter calls.")

        start_time = time.time()
        resp = session.post(endpoint, json=payload, headers=headers, timeout=(10.0, float(timeout_s)))
        latency = round(time.time() - start_time, 2)

        resp_headers = dict(resp.headers)

        if resp.status_code == 200:
            body_text = resp.text.strip()
            if not body_text:
                raise RuntimeError(f"Provider {provider} ({model_name}) returned empty HTTP 200 payload (char 0).")
            try:
                data = resp.json()
            except Exception as j_err:
                raise RuntimeError(f"Provider {provider} ({model_name}) failed to parse JSON: {j_err} | Body: {body_text[:120]}")

            choices = data.get("choices", [])
            text = ""
            if choices and "message" in choices[0]:
                text = choices[0]["message"].get("content", "")
            return text, resp_headers, latency
        else:
            err_msg = f"HTTP {resp.status_code}: {resp.text}"
            raise RuntimeError(f"Provider {provider} ({entity.model_name}) error: {err_msg}")


class LLMRouter:
    def __init__(self):
        self.tracker = DynamicQuotaTracker()
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.gh_key = os.environ.get("GH_MODELS_TOKEN", "").strip()
        self.openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

        # Strict isolation: Cloudflare Workers AI is banned from handling text
        self.cf_account = os.environ.get("CF_ACCOUNT_ID", "").strip()
        self.cf_token = os.environ.get("CF_API_TOKEN", "").strip()

        self.google_adapter = GoogleGenAIAdapter(self.gemini_key) if self.gemini_key else None
        self.openai_adapter = OpenAICompatibleAdapter({
            "groq": self.groq_key,
            "github": self.gh_key,
            "openrouter": self.openrouter_key
        })

        # Run-Scoped isolation set for models that fail hard in the current execution
        self._run_failed_models = set()

    def _get_active_providers(self, gemini_quota_ok: bool) -> List[str]:
        providers = []
        if self.gemini_key and gemini_quota_ok:
            providers.append("google")
        if self.groq_key:
            providers.append("groq")
        if self.gh_key:
            providers.append("github")
        if self.openrouter_key:
            providers.append("openrouter")
        return providers

    def execute_generation(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        gemini_quota_ok: bool = True,
        task_type: str = "creative"
    ) -> Tuple[Optional[str], str, str]:
        """
        Executes generation using the autonomous Scarcity Waterfall Resolver.
        Returns: (generated_text, transparent_provider_tag, provider_key)
        """
        # Hard isolation guard: Cloudflare Workers AI must never be invoked for LLM text
        active_providers = self._get_active_providers(gemini_quota_ok)
        if not active_providers:
            logger.error("🛑 [LLM ROUTER] No active LLM text providers configured with valid API keys.")
            return None, "No Providers Available", "none"

        # Resolve candidate dispatch ladder via the 85% Scarcity Waterfall
        dispatch_plan = ScarcityWaterfallResolver.resolve_candidates(
            task_type=task_type,
            tracker=self.tracker,
            active_providers=active_providers
        )

        # ── P2.8: Budget Strain Guard ─────────────────────────────────────────
        # If daily token budget is 80%+ consumed, prioritize high-quota 'flash-lite' models
        try:
            from scripts.quota_manager import cost_tracker
            if cost_tracker.is_budget_strained(threshold=0.80):
                print("   💸 [COST OPTIMIZER] Daily token budget >80% consumed. Prioritizing flash-lite models.")
                dispatch_plan = sorted(
                    dispatch_plan,
                    key=lambda item: 0 if ("lite" in item[0].model_name.lower() or item[0].max_rpd >= 500) else 1
                )
        except Exception:
            pass

        for entity, tier_label in dispatch_plan:
            if entity.entity_id in self._run_failed_models:
                continue

            # Gentle sliding-window pacing
            SlidingWindowRateLimiter.pace(entity)

            # Execution attempt with 3-attempt exponential backoff retry (503)
            for attempt in range(3):
                try:
                    logger.generation(f"🤖 [LLM DISPATCH] {entity.entity_id} | {tier_label} (Attempt {attempt + 1})")

                    if entity.provider == "google":
                        if not self.google_adapter:
                            break
                        text, headers, latency = self.google_adapter.generate_text(
                            entity=entity,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            task_type=task_type,
                            timeout_s=120.0
                        )
                    else:
                        text, headers, latency = self.openai_adapter.generate_text(
                            entity=entity,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            task_type=task_type,
                            timeout_s=120.0
                        )

                    # Sniff dynamic rate-limit response headers
                    if headers:
                        self.tracker.sniff_headers(entity.entity_id, headers)

                    if text and text.strip():
                        # Validate JSON formatting if task demands it
                        if task_type in ("seo_json", "json"):
                            parsed = UniversalGreedyJSONParser.extract_json(text)
                            if not parsed:
                                logger.warn(f"⚠️ [PARSE REJECT] {entity.entity_id} produced non-JSON text. Retrying or cascading.")
                                continue

                        # Record call success & update EMA quality
                        self.tracker.record_call_success(entity.entity_id, task_type, latency)
                        logger.success(f"✅ [LLM ROUTER] Succeeded via {tier_label} in {latency:.2f}s")
                        return text, tier_label, entity.provider
                    else:
                        logger.warn(f"⚠️ [LLM ROUTER] Empty output from {entity.entity_id}.")

                except Exception as e:
                    err_str = str(e).lower()

                    # 4-Pathway Error Handling
                    if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                        if attempt < 2:
                            backoff = ((attempt + 1) * 8.0) + random.uniform(1.0, 3.0)
                            logger.warn(f"⏳ [TRANSIENT 503] {entity.entity_id} capacity spike. Retrying attempt {attempt + 2}/3 in {backoff:.1f}s...")
                            time.sleep(backoff)
                            continue
                        else:
                            self.tracker.record_call_error(entity.entity_id, 503, str(e))
                            self._run_failed_models.add(entity.entity_id)
                            break

                    elif any(x in err_str for x in ["429", "quota", "resourceexhausted", "rate limit"]):
                        self.tracker.record_call_error(entity.entity_id, 429, str(e))
                        self._run_failed_models.add(entity.entity_id)
                        break

                    elif any(x in err_str for x in ["404", "410", "deprecated", "not found"]):
                        self.tracker.record_call_error(entity.entity_id, 404, str(e))
                        self._run_failed_models.add(entity.entity_id)
                        break

                    else:
                        logger.error(f"⚠️ [DISPATCH ERROR] {entity.entity_id} failed: {e}")
                        break

        logger.error("🛑 [LLM ROUTER] All candidate models exhausted across all active providers.")
        return None, "All Providers Exhausted", "none"


llm_router = LLMRouter()
