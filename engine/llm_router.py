# engine/llm_router.py
# Ghost Engine V26.0.0 — Neural Routing with Step-Transparency
import os
import time
from typing import Tuple, Optional
from engine.logger import logger

class LLMRouter:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self._gemini_models = ["gemini-2.0-flash", "gemini-1.5-flash"]
        self._last_call = 0.0

    def _enforce_throttle(self):
        elapsed = time.time() - self._last_call
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed)
        self._last_call = time.time()

    def execute_generation(self, prompt: str, system_prompt: Optional[str], gemini_quota_ok: bool, task_type: str = "creative") -> Tuple[Optional[str], str, str]:
        logger.info(f"LLM Router: Task Type '{task_type}' | Gemini Quota Status: {gemini_quota_ok}")

        # 1. Primary AI: Google Gemini (2026 Optimization)
        if gemini_quota_ok and self.gemini_key:
            for model in self._gemini_models:
                logger.info(f"LLM Router: Attempting primary generation via {model}...")
                self._enforce_throttle()
                try:
                    from google import genai
                    client = genai.Client(api_key=self.gemini_key)
                    cfg = {"system_instruction": system_prompt} if system_prompt else {}
                    response = client.models.generate_content(model=model, contents=prompt, config=cfg or None)
                    if response.text:
                        logger.success(f"LLM Router: {model} generation successful.")
                        return response.text, f"Gemini ({model})", "gemini"
                except Exception as e:
                    logger.warning(f"LLM Router: Gemini {model} failed: {str(e)[:100]}")

        # 2. Secondary AI: Groq (Llama 3.3 Versatile)
        if self.groq_key:
            logger.info("LLM Router: Engaging Groq Llama 3.3 failover...")
            try:
                from scripts.groq_client import groq_client
                res = groq_client.generate_text(prompt, system_prompt=system_prompt)
                if res:
                    logger.success("LLM Router: Groq generation successful.")
                    return res, "Groq (Llama 3.3)", "groq"
            except Exception as e:
                logger.warning(f"LLM Router: Groq failover collapsed: {e}")

        return None, "All Providers Exhausted", "none"

llm_router = LLMRouter()
