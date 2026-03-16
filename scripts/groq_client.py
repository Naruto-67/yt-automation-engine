# scripts/groq_client.py
import os
import time
import requests
from engine.config_manager import config_manager

class GroqAPIClient:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1"
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        self.TEXT_MODEL = "llama-3.3-70b-versatile"
        self._models_discovered = False

    def _discover_models(self):
        if self._models_discovered or not self.api_key: return
        try:
            res = requests.get(f"{self.base_url}/models", headers=self.headers, timeout=10)
            if res.status_code == 200:
                available = {m["id"] for m in res.json().get("data", [])}
                if "llama-3.3-70b-versatile" in available:
                    self.TEXT_MODEL = "llama-3.3-70b-versatile"
        except Exception: pass
        self._models_discovered = True

    def generate_text(self, prompt: str, role: str = "creative",
                      system_prompt: str = None, 
                      throttle: bool = False) -> str | None:
        self._discover_models()
        if throttle: time.sleep(2)
        
        # FIX: Ensure system_prompt is never None
        effective_system = system_prompt or "You are a viral YouTube Shorts scriptwriter."
        
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": effective_system},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
        }
        
        try:
            res = requests.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload, timeout=45)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
            return None
        except Exception:
            return None

groq_client = GroqAPIClient()
