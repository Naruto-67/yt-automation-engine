# engine/llm_router.py
import os
import time
import random
from typing import Tuple, Optional
from engine.logger import logger

class LLMRouter:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self._gemini_models = ["gemini-2.0-flash", "gemini-1.5-flash"]
        self._last_call = 0.0

    def execute_generation(self, prompt: str, system_prompt: Optional[str], gemini_quota_ok: bool, task_type: str = "creative") -> Tuple[Optional[str], str, str]:
        logger.info(f"LLM Router: Task={task_type}, GeminiQuotaOk={gemini_quota_ok}")
        
        # 1. Attempt Gemini
        if gemini_quota_ok and self.gemini_key:
            for model in self._gemini_models:
                logger.info(f"LLM Router: Attempting Gemini ({model})...")
                # Throttle to avoid 429
                wait = 2.0 - (time.time() - self._last_call)
                if wait > 0: time.sleep(wait)
                
                try:
                    from google import genai
                    client = genai.Client(api_key=self.gemini_key)
                    cfg = {"system_instruction": system_prompt} if system_prompt else {}
                    response = client.models.generate_content(model=model, contents=prompt, config=cfg or None)
                    self._last_call = time.time()
                    if response.text:
                        logger.success(f"LLM Router: Gemini ({model}) responded.")
                        return response.text, f"Gemini ({model})", "gemini"
                except Exception as e:
                    logger.warning(f"LLM Router: Gemini ({model}) failed: {str(e)}")

        # 2. Attempt Groq Fallback
        if self.groq_key:
            logger.info("LLM Router: Attempting Groq (Llama 3.3)...")
            try:
                from scripts.groq_client import groq_client
                res = groq_client.generate_text(prompt, system_prompt=system_prompt)
                if res:
                    logger.success("LLM Router: Groq responded.")
                    return res, "Groq (Llama 3.3)", "groq"
            except Exception as e:
                logger.warning(f"LLM Router: Groq failed: {str(e)}")

        return None, "All Providers Failed", "none"

llm_router = LLMRouter()
