"""
engine/managers/llm_manager.py — Multi-Provider LLM Orchestrator (v2.0)
Harvests robust JSON parsing and rate-limit mitigation from v1.0.
Supports Groq, Google GenAI, and OpenAI with automatic failover and official SDK adherence.
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional
from engine.managers.error_manager import ErrorManager

logger = logging.getLogger("LLMManager")


class UniversalGreedyJSONParser:
    """Ultra-Resilient 4-Level JSON & Syntax Auto-Repair Parser."""

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

        return None

    @classmethod
    def _repair_syntax(cls, snippet: str) -> str:
        s = re.sub(r",\s*([\]}])", r"\1", snippet)
        s = re.sub(r'\bTrue\b', 'true', s)
        s = re.sub(r'\bFalse\b', 'false', s)
        s = re.sub(r'\bNone\b', 'null', s)
        if "'" in s and '"' not in s:
            s = s.replace("'", '"')
        return s


class LLMManager:
    """Centralized LLM routing with multi-provider fallbacks."""

    def __init__(self):
        self.groq_api_key = os.environ.get("GROQ_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> Dict[str, Any]:
        """
        Executes generation with automatic failover:
        Primary: Groq Llama 3.3 70B -> Secondary: Google Gemini 2.5 Flash -> Tertiary: OpenAI.
        """
        providers = []
        if self.groq_api_key:
            providers.append(("Groq", self._call_groq))
        if self.gemini_api_key:
            providers.append(("Gemini", self._call_gemini))
        if self.openai_api_key:
            providers.append(("OpenAI", self._call_openai))

        if not providers:
            raise RuntimeError("No LLM API keys configured. Set GROQ_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY.")

        last_error = None
        for provider_name, provider_fn in providers:
            try:
                print(f"🤖 [LLM] Routing request to {provider_name}...")
                response_text = ErrorManager.execute_with_retry(
                    operation=lambda: provider_fn(system_prompt, user_prompt, temperature),
                    context_name=f"LLM Call ({provider_name})",
                    max_retries=2,
                    initial_backoff=2.0
                )
                parsed = UniversalGreedyJSONParser.extract_json(response_text)
                if parsed:
                    return parsed
                print(f"⚠️ [LLM] {provider_name} returned unparseable JSON. Attempting next provider...")
            except Exception as e:
                last_error = e
                print(f"⚠️ [LLM] {provider_name} failed: {e}. Falling back...")

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def _call_groq(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        from groq import Groq
        client = Groq(api_key=self.groq_api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=2048,
        )
        return completion.choices[0].message.content

    def _call_gemini(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=self.gemini_api_key)
        full_content = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_prompt}"
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_content,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
            )
        )
        return response.text

    def _call_openai(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        import requests
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

