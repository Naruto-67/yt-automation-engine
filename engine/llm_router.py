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
        # Failsafe fallback if discovery endpoint is temporarily unreachable
        fallback_stable = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
        fallback_preview = ["gemini-3-flash-preview", "gemini-2.0-flash-exp"]

        if not self.gemini_key:
            self._gemini_models_discovered = True
            return

        try:
            from google import genai
            import re as _re

            client = genai.Client(api_key=self.gemini_key, http_options={"timeout": 15000})
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models if hasattr(m, "name")]

            # Exclude non-text modalities, live WebSocket streaming, speech, vision, embeddings, and paid pro tiers
            EXCLUDED_KEYWORDS = [
                "live", "realtime", "extended-thinking", "vision", "audio", "tts",
                "embedding", "imagen", "image", "video", "chat", "deep-research",
                "robotics", "custom", "pro"
            ]

            def _is_text_flash(name: str) -> bool:
                n = name.lower()
                # Must be a Flash model (Google's high-speed, free-tier workhorse)
                if "flash" not in n:
                    return False
                # Must not contain excluded non-text or streaming keywords
                if any(x in n for x in EXCLUDED_KEYWORDS):
                    return False
                return True

            def _score(name: str) -> float:
                """
                100% Dynamic Version Scoring — Zero hardcoded model lists.
                Extracts major.minor version number automatically from the API response:
                e.g. gemini-4.0-flash -> 400.0, gemini-3.8-flash -> 308.0,
                     gemini-3.8-flash-lite -> 307.5, gemini-2.5-flash -> 205.0.
                Newer models always automatically rank highest.
                """
                n = name.lower()
                m = _re.search(r"gemini[-\s]?(\d+)(?:\.(\d+))?", n)
                if not m:
                    return 0.0
                major = int(m.group(1))
                minor = int(m.group(2)) if m.group(2) else 0
                version_score = (major * 100) + minor
                if "lite" in n:
                    version_score -= 0.5
                return float(version_score)

            clean_flash_models = [m for m in model_names if _is_text_flash(m)]

            # Stable chain (pure dynamic ranking of discovered models)
            stable_candidates = [m for m in clean_flash_models if "exp" not in m and "preview" not in m]
            self._gemini_stable_chain = sorted(stable_candidates, key=_score, reverse=True)[:4] if stable_candidates else fallback_stable

            # Preview chain (pure dynamic ranking of discovered preview/experimental models)
            preview_candidates = [m for m in clean_flash_models if "exp" in m or "preview" in m]
            self._gemini_preview_chain = sorted(preview_candidates, key=_score, reverse=True)[:2] if preview_candidates else fallback_preview

            print(f"🤖 [GEMINI] Dynamic Auto-Discovery — Stable Chain: {self._gemini_stable_chain} | Preview Chain: {self._gemini_preview_chain}")

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
        
        # Dynamic Tuning
        temperature = 0.85 if task_type == "creative" else 0.2
        
        # Initialize Circuit Breaker blacklist (models mapped to their unban timestamp)
        if not hasattr(self, "_failed_models"):
            self._failed_models = {}

        # ROUTING: Stable -> Groq -> Preview
        execution_plan = []
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Stable", self._gemini_stable_chain, "gemini"))
        if self.groq_key:
            execution_plan.append(("Groq Chain", ["__groq__"], "groq"))
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Preview", self._gemini_preview_chain, "gemini"))

        for stage_name, models, provider_key in execution_plan:
            if "Gemini" in stage_name:
                stage_hard_failed = False
                for model in models:
                    if stage_hard_failed:
                        break
                    
                    # ── Circuit Breaker Check ──
                    if model in self._failed_models:
                        if time.time() < self._failed_models[model]:
                            # Model is currently blacklisted, skip instantly
                            continue
                        else:
                            # Blacklist expired, unban
                            del self._failed_models[model]

                    # ── Tenacity Retry Block for 429s and Network Glitches ──
                    from tenacity import retry, wait_random_exponential, stop_after_attempt
                    
                    @retry(wait=wait_random_exponential(min=2, max=10), stop=stop_after_attempt(4), reraise=True)
                    def _call_gemini_with_retry():
                        self._enforce_rpm_throttle()
                        from google import genai
                        from google.genai import types
                        client = genai.Client(api_key=self.gemini_key, http_options={"timeout": 60000})
                        gen_cfg = types.GenerateContentConfig(
                            system_instruction=system_prompt if system_prompt else None,
                            temperature=temperature,
                            max_output_tokens=8000,
                            http_options={"timeout": 60000}
                        )
                        response = client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=gen_cfg
                        )
                        text = response.text if response and response.text else ""
                        if not text:
                            raise ValueError(f"Empty response from {model}")
                        return text
                        
                    try:
                        text = _call_gemini_with_retry()
                        return text, f"Gemini ({model})", provider_key
                    except Exception as e:
                        err_str = str(e).lower()
                        from engine.logger import logger
                        if any(x in err_str for x in ["quota", "exhausted", "403", "resourceexhausted"]):
                            stage_hard_failed = True
                            break
                        # ── Circuit Breaker Trigger (genuine 503 or unavailable) ──
                        if "503" in err_str or "unavailable" in err_str:
                            logger.error(f"⚠️ [GEMINI] 503/Unavailable on {model}. Blacklisting for 5 minutes.")
                            self._failed_models[model] = time.time() + 300
                            continue
                        logger.error(f"⚠️ [GEMINI] {model} call failed: {e}. Trying next candidate.")
                        continue
            elif stage_name == "Groq Chain":
                try:
                    res = self._get_groq_client().generate_text(prompt, role=task_type, system_prompt=system_prompt)
                    if res:
                        return res, "Groq (Auto Chain)", provider_key
                except Exception:
                    continue

        return None, "All Providers Exhausted", "none"

llm_router = LLMRouter()
