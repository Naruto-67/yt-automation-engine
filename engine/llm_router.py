# engine/llm_router.py
import os
import time
import random
import traceback
from typing import Tuple, Optional
from engine.config_manager import config_manager

class LLMRouter:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self._gemini_stable_chain = []
        self._gemini_preview_chain = []
        self._gemini_models_discovered = False
        self._last_llm_call_time = 0.0
        self._groq = None

    def _get_groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _discover_gemini_models(self):
        if self._gemini_models_discovered: return
        
        # Failsafe fallback if discovery endpoint goes down or changes format.
        # gemini-1.5-flash is Google's declared long-term stable tier.
        fallback_stable = ["gemini-1.5-flash"]
        fallback_preview = []

        if not self.gemini_key:
            self._gemini_models_discovered = True
            return

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key)
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models if hasattr(m, "name")]

            import re as _re

            def _score(name: str) -> int:
                """
                Score Gemini models by version number automatically.
                Uses dynamic version parsing so any newer model (e.g. gemini-3.0-flash,
                gemini-4.5-flash-lite) is preferred over older ones without code changes.
                """
                n = name.lower()
                # Exclude non-text models — they break the text generation chain
                if any(x in n for x in ["vision", "audio", "tts", "embedding", "imagen"]):
                    return -1

                # Extract the major.minor version number from the model name
                # e.g. "gemini-2.5-flash" → 2.5, "gemini-1.5-flash-8b" → 1.5
                m = _re.search(r"gemini[-\s]?(\d+)\.(\d+)", n)
                if not m:
                    return 0  # unknown format — rank lowest

                major = int(m.group(1))
                minor = int(m.group(2))

                # Score = (major * 100) + minor
                # This ensures: 3.0 > 2.5 > 2.0 > 1.5 > 1.0
                # So newer free models (e.g. 3.0-flash, 3.5-flash-lite) are always preferred.
                score = (major * 100) + minor
                return score

            self._gemini_stable_chain = sorted([m for m in model_names if "exp" not in m and "preview" not in m], key=_score, reverse=True)[:4]
            self._gemini_preview_chain = sorted([m for m in model_names if "exp" in m or "preview" in m], key=_score, reverse=True)[:2]
        except Exception as e:
            print(f"⚠️ [GEMINI] Model discovery failed: {e}. Using fallback stable models.")
            self._gemini_stable_chain = fallback_stable
            self._gemini_preview_chain = fallback_preview

        self._gemini_models_discovered = True

    def _enforce_rpm_throttle(self):
        elapsed = time.time() - self._last_llm_call_time
        if elapsed < 2.5: time.sleep(2.5 - elapsed)
        self._last_llm_call_time = time.time()

    def execute_generation(self, prompt: str, system_prompt: Optional[str], gemini_quota_ok: bool, task_type: str = "creative") -> Tuple[Optional[str], str, str]:
        self._discover_gemini_models()

        # ROUTING: Stable -> Groq -> Preview
        execution_plan = []
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Stable", self._gemini_stable_chain, "gemini"))
        if self.groq_key:
            # Discovered, ranked Groq text-model chain (never hardcoded single model)
            execution_plan.append(("Groq Chain", ["__groq__"], "groq"))
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Preview", self._gemini_preview_chain, "gemini"))

        for stage_name, models, provider_key in execution_plan:
            if "Gemini" in stage_name:
                stage_hard_failed = False
                for model in models:
                    if stage_hard_failed:
                        break
                    for attempt in range(3):
                        self._enforce_rpm_throttle()
                        try:
                            from google import genai
                            from google.genai import types
                            client = genai.Client(api_key=self.gemini_key)
                            # Use the recommended Chat API instead of the
                            # (deprecated-recommendation) Models.generate_content.
                            # system_instruction still travels via the config.
                            cfg = {"system_instruction": system_prompt} if system_prompt else {}
                            chat = client.chats.create(
                                model=model,
                                config=cfg or None,
                            )
                            response = chat.send_message(
                                message=prompt,
                                config=types.GenerateContentConfig(
                                    temperature=0.3,
                                    max_output_tokens=8000,
                                ) if cfg else None,
                            )
                            return response.text, f"Gemini ({model})", provider_key
                        except Exception as e:
                            if any(x in str(e).lower() for x in ["quota", "exhausted", "403"]):
                                stage_hard_failed = True
                                break
                            continue
            elif stage_name == "Groq Chain":
                # groq_client.generate_text already iterates the full discovered
                # model chain internally and its own API returns text.
                try:
                    res = self._get_groq_client().generate_text(prompt, system_prompt=system_prompt)
                    if res:
                        return res, "Groq (Auto Chain)", provider_key
                except Exception:
                    continue

        return None, "All Providers Exhausted", "none"

llm_router = LLMRouter()
