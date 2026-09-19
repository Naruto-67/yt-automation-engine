# engine/llm_router.py — Autonomous Multi-Tier LLM Orchestrator
"""
Autonomous Task-Centric LLM Router with Run-Scoped Circuit Breaking.
Dynamically routes generation tasks across Google GenAI and Groq Cloud based on
live capability registries, thinking profiles, and sub-second failover.
"""

import os
import time
import random
import traceback
from typing import Tuple, Optional, Dict, Any, List
from engine.config_manager import config_manager
from engine.logger import logger


class LLMRouter:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._last_llm_call_time = 0.0
        self._groq = None
        # Run-Scoped Circuit Breaker: Models that fail in this process run are bypassed in 0ms
        self._run_failed_models = set()
        self._gemini_models_discovered = False
        self._gemini_stable_chain: List[str] = []
        self._gemini_preview_chain: List[str] = []

    def _get_groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _discover_gemini_models(self):
        if self._gemini_models_discovered:
            return

        from engine.dynamic_discovery import load_registry, discover_google_models
        registry = load_registry()

        # Workhorses that work universally across all accounts
        gold_gemini = registry.get("gold_anchors", {}).get("gemini", [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite"
        ])
        canaries = registry.get("canaries", {}).get("gemini", [
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash"
        ])

        if not self.gemini_key:
            self._gemini_stable_chain = gold_gemini
            self._gemini_preview_chain = canaries
            self._gemini_models_discovered = True
            return

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key, http_options={"timeout": 15000})
            live_models = discover_google_models(client=client)
            if live_models:
                # Prioritize active models discovered live
                self._gemini_stable_chain = [m for m in live_models if "preview" not in m and "exp" not in m]
                # Ensure gold workhorses are present
                for g in gold_gemini:
                    if g not in self._gemini_stable_chain and g not in registry.get("deprecated_models", []):
                        self._gemini_stable_chain.append(g)

                self._gemini_preview_chain = [m for m in live_models if "preview" in m or "exp" in m]
            else:
                self._gemini_stable_chain = gold_gemini
                self._gemini_preview_chain = canaries

            logger.info(f"🤖 [GEMINI] Dynamic Discovery — Stable: {self._gemini_stable_chain} | Canaries: {canaries}")
        except Exception as e:
            logger.error(f"⚠️ [GEMINI] Model discovery failed: {e}. Using registry defaults.")
            self._gemini_stable_chain = gold_gemini
            self._gemini_preview_chain = canaries

        self._gemini_models_discovered = True

    def _enforce_rpm_throttle(self):
        elapsed = time.time() - self._last_llm_call_time
        if elapsed < 2.5:
            time.sleep(2.5 - elapsed)
        self._last_llm_call_time = time.time()

    def execute_generation(
        self,
        prompt: str,
        system_prompt: Optional[str],
        gemini_quota_ok: bool,
        task_type: str = "creative"
    ) -> Tuple[Optional[str], str, str]:
        """
        Executes generation using task-centric multi-tier routing.
        - creative (scriptwriting): Canary Flash -> Groq Llama-3.3-70B -> Gold Flash-Lite
        - json / analytical (SEO, schemas): Gold Flash-Lite -> Groq Llama-3.1-8B -> Canary Flash
        """
        self._discover_gemini_models()
        from engine.dynamic_discovery import load_registry
        registry = load_registry()
        thinking_profiles = registry.get("thinking_profiles", {})

        # Task-Centric stage planning
        if task_type == "creative":
            # Scriptwriting favors intelligence and storytelling capability
            gemini_primary = [
                m for m in (self._gemini_stable_chain + self._gemini_preview_chain)
                if m not in self._run_failed_models
            ]
            # Prioritize 3.6 / 3.8 Flash canary first, then fallback to high-intelligence Groq 70B
            execution_stages = [
                ("Gemini Canary", gemini_primary[:2], "gemini"),
                ("Groq 70B Anchor", ["llama-3.3-70b-versatile"], "groq"),
                ("Gemini Flash-Lite", [m for m in gemini_primary if "lite" in m], "gemini"),
                ("Groq Auto Chain", ["__groq__"], "groq"),
            ]
        else:
            # JSON / SEO extraction favors ultra-low latency & deterministic structure
            gemini_fast = [
                m for m in self._gemini_stable_chain
                if "lite" in m and m not in self._run_failed_models
            ]
            if not gemini_fast:
                gemini_fast = [m for m in self._gemini_stable_chain if m not in self._run_failed_models]

            execution_stages = [
                ("Gemini Flash-Lite", gemini_fast, "gemini"),
                ("Groq 8B Fast Anchor", ["llama-3.1-8b-instant"], "groq"),
                ("Gemini General", [m for m in self._gemini_stable_chain if m not in self._run_failed_models], "gemini"),
                ("Groq Auto Chain", ["__groq__"], "groq"),
            ]

        # Execute stages in order
        for stage_name, candidate_models, provider_key in execution_stages:
            if not candidate_models:
                continue

            # Skip Gemini if quota is known to be exhausted
            if provider_key == "gemini" and not (gemini_quota_ok and self.gemini_key):
                continue

            if provider_key == "groq" and not self.groq_key:
                continue

            if provider_key == "gemini":
                for model in candidate_models:
                    if model in self._run_failed_models:
                        continue

                    # Determine thinking profile and timeouts
                    profile = thinking_profiles.get(model, {})
                    timeout_ms = int(profile.get("timeout_s", 60.0) * 1000)
                    thinking_level = profile.get("thinking_level", "low") if any(v in model for v in ["3.8", "3.7", "3.6", "3.5"]) else None

                    try:
                        self._enforce_rpm_throttle()
                        from google import genai
                        from google.genai import types

                        client = genai.Client(api_key=self.gemini_key, http_options={"timeout": timeout_ms})

                        cfg_kwargs: Dict[str, Any] = {
                            "http_options": {"timeout": timeout_ms},
                            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)
                        }
                        if system_prompt:
                            cfg_kwargs["system_instruction"] = system_prompt

                        # Apply thinking config for 3.x models
                        if thinking_level:
                            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

                        # Set temperature only on models where it is supported
                        if not profile.get("strip_sampling_params", False):
                            cfg_kwargs["temperature"] = 0.85 if task_type == "creative" else 0.2

                        gen_cfg = types.GenerateContentConfig(**cfg_kwargs)

                        response = client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=gen_cfg
                        )

                        text = response.text if response and response.text else ""
                        if text:
                            logger.info(f"🤖 [LLM ROUTER] Success via {model} ({stage_name})")
                            return text, f"Gemini ({model})", "gemini"
                        else:
                            logger.warn(f"⚠️ [LLM ROUTER] Empty output from {model}. Trying next candidate.")

                    except Exception as e:
                        err_str = str(e).lower()
                        # Circuit Breaker: If model is 404 deprecated or 429 quota exhausted, mark failed for this run
                        if "404" in err_str or "not available" in err_str or "no longer available" in err_str:
                            logger.error(f"🛑 [CIRCUIT BREAKER] {model} is deprecated/unavailable (404). Bypassing for this run.")
                            self._run_failed_models.add(model)
                        elif any(x in err_str for x in ["quota", "exhausted", "429", "resourceexhausted"]):
                            logger.error(f"🛑 [CIRCUIT BREAKER] {model} quota exhausted (429). Bypassing for this run.")
                            self._run_failed_models.add(model)
                        elif "timeout" in err_str or "timed out" in err_str or "deadline" in err_str:
                            logger.warn(f"⏳ [TIMEOUT] {model} timed out ({timeout_ms}ms). Failing over instantly.")
                            self._run_failed_models.add(model)
                        elif "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                            logger.warn(f"⚠️ [CAPACITY SPIKE] {model} experiencing transient high demand (503). Failing over instantly.")
                            self._run_failed_models.add(model)
                        else:
                            logger.error(f"⚠️ [LLM ROUTER] {model} failed: {e}. Trying next candidate.")
                        continue

            elif provider_key == "groq":
                groq_client_inst = self._get_groq_client()
                for target_model in candidate_models:
                    try:
                        if target_model == "__groq__":
                            res = groq_client_inst.generate_text(prompt, role=task_type, system_prompt=system_prompt)
                            if res:
                                logger.info(f"🤖 [LLM ROUTER] Success via Groq Auto Chain")
                                return res, "Groq (Auto Chain)", "groq"
                        else:
                            # Direct call to specific anchor model
                            orig_models = groq_client_inst.TEXT_MODELS
                            groq_client_inst.TEXT_MODELS = [target_model] + [m for m in orig_models if m != target_model]
                            res = groq_client_inst.generate_text(prompt, role=task_type, system_prompt=system_prompt)
                            if res:
                                logger.info(f"🤖 [LLM ROUTER] Success via Groq ({target_model})")
                                return res, f"Groq ({target_model})", "groq"
                    except Exception as ge:
                        logger.error(f"⚠️ [GROQ] Model {target_model} attempt failed: {ge}")
                        continue

        return None, "All Providers Exhausted", "none"


llm_router = LLMRouter()
