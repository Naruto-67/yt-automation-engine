# engine/llm_router.py
# Ghost Engine V26.0.0 — Neural Routing & Rate-Limit Protection
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
        self._last_llm_call_time = 0.0 [cite: 131]
        self._groq = None

    def _get_groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _discover_gemini_models(self):
        """
        V26: Dynamically discovers and ranks available Gemini models.
        Prioritizes the latest Flash models for cost-efficiency. [cite: 132-135]
        """
        if self._gemini_models_discovered: return
        
        fallback_stable = ["gemini-3-flash", "gemini-2.0-flash"]
        fallback_preview = ["gemini-3-flash-exp"]

        if not self.gemini_key:
            self._gemini_stable_chain, self._gemini_preview_chain = fallback_stable, fallback_preview
            self._gemini_models_discovered = True
            return

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key) [cite: 133]
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models if hasattr(m, "name")]

            def _score(name: str) -> int:
                n = name.lower()
                # Exclude specialized models not suitable for scriptwriting
                if any(x in n for x in ["vision", "audio", "tts"]): return -1
                score = 0
                if "3.0" in n: score += 120
                elif "2.0" in n: score += 80
                elif "1.5" in n: score += 60
                return score [cite: 134-135]

            self._gemini_stable_chain = sorted([m for m in model_names if "exp" not in m and "preview" not in m], key=_score, reverse=True)[:4]
            self._gemini_preview_chain = sorted([m for m in model_names if "exp" in m or "preview" in m], key=_score, reverse=True)[:2]
        except Exception:
            self._gemini_stable_chain, self._gemini_preview_chain = fallback_stable, fallback_preview

        self._gemini_models_discovered = True

    def _enforce_rpm_throttle(self):
        """
        V26 Hard Throttle: Ensures at least 2.5s between calls to prevent 
        429 Rate Limit errors on free-tier API keys. 
        """
        elapsed = time.time() - self._last_llm_call_time
        if elapsed < 2.5: 
            time.sleep(2.5 - elapsed)
        self._last_llm_call_time = time.time()

    def execute_generation(self, prompt: str, system_prompt: Optional[str], gemini_quota_ok: bool, task_type: str = "creative") -> Tuple[Optional[str], str, str]:
        """
        V26 Routing Logic: Gemini Stable -> Groq Llama 3.3 -> Gemini Preview. [cite: 137]
        """
        self._discover_gemini_models()

        execution_plan = []
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Stable", self._gemini_stable_chain, "gemini"))
        if self.groq_key:
            execution_plan.append(("Groq Llama 3.3", ["llama-3.3-70b-versatile"], "groq")) [cite: 137]
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Preview", self._gemini_preview_chain, "gemini"))

        for stage_name, models, provider_key in execution_plan:
            if "Gemini" in stage_name:
                stage_hard_failed = False
                for model in models:
                    if stage_hard_failed: break
                    for attempt in range(3):
                        self._enforce_rpm_throttle() [cite: 138]
                        try:
                            from google import genai
                            client = genai.Client(api_key=self.gemini_key) [cite: 139]
                            cfg = {"system_instruction": system_prompt} if system_prompt else {} [cite: 140]
                            response = client.models.generate_content(model=model, contents=prompt, config=cfg or None)
                            return response.text, f"Gemini ({model})", provider_key
                        except Exception as e:
                            # If we hit a quota error, kill this stage and move to Groq [cite: 141-142]
                            if any(x in str(e).lower() for x in ["quota", "exhausted", "403"]):
                                stage_hard_failed = True
                                break
                            continue
            elif stage_name == "Groq Llama 3.3":
                try:
                    res = self._get_groq_client().generate_text(prompt, system_prompt=system_prompt)
                    if res: return res, "Groq (Llama 3.3)", provider_key [cite: 143]
                except Exception: 
                    continue

        return None, "All Providers Exhausted", "none"

llm_router = LLMRouter()
