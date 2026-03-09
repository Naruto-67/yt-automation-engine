# scripts/groq_client.py — Ghost Engine V11.0
import os
import time
import random
import requests
from engine.config_manager import config_manager

class GroqAPIClient:
    def __init__(self):
        self.api_key         = os.environ.get("GROQ_API_KEY")
        self.base_url        = "https://api.groq.com/openai/v1"
        self.headers         = {"Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json"}
        self.TEXT_MODEL      = "llama-3.3-70b-versatile"
        self.AUDIO_MODEL     = "playai-tts"
        self._models_discovered = False

    def _discover_models(self):
        if self._models_discovered:
            return

        settings      = config_manager.get_settings()
        fallback_chain = settings.get("groq_model_fallback_chain", [
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama3-70b-8192",
            "mixtral-8x7b-32768",
        ])

        if not self.api_key:
            self._models_discovered = True
            return

        try:
            res = requests.get(
                f"{self.base_url}/models",
                headers=self.headers,
                timeout=10
            )
            if res.status_code != 200:
                self._models_discovered = True
                return

            available = {m["id"] for m in res.json().get("data", [])}

            def _score(name: str) -> int:
                n = name.lower()
                if any(x in n for x in ["whisper", "tts", "vision", "guard"]):
                    return -1
                score = 0
                if "70b" in n:  score += 50
                elif "8b" in n: score += 20
                if "versatile" in n: score += 30
                if "3.3" in n:      score += 20
                elif "3.1" in n:    score += 10
                elif "llama3" in n: score += 5
                return score

            for model in fallback_chain:
                if model in available and _score(model) >= 0:
                    self.TEXT_MODEL = model
                    print(f"✅ [GROQ] Selected model: {self.TEXT_MODEL}")
                    break
            else:
                ranked = sorted(
                    [m for m in available if _score(m) >= 0],
                    key=_score, reverse=True
                )
                if ranked:
                    self.TEXT_MODEL = ranked[0]
                    print(f"✅ [GROQ] Auto-selected: {self.TEXT_MODEL}")

        except Exception as e:
            print(f"⚠️ [GROQ] Model discovery failed: {e}")

        self._models_discovered = True

    def _execute(self, endpoint: str, payload: dict, is_audio: bool = False):
        if not self.api_key:
            return None
            
        url = f"{self.base_url}/{endpoint}"
        
        try:
            res = requests.post(url, headers=self.headers, json=payload, timeout=45)
            if res.status_code == 200:
                if is_audio:
                    return res.content
                data = res.json()
                choices = data.get("choices", [])
                return choices[0]["message"]["content"] if choices else None
            elif res.status_code == 404:
                print(f"⚠️ [GROQ] Model 404 — forcing rediscovery.")
                self._models_discovered = False
                self._discover_models()
                payload["model"] = self.TEXT_MODEL
                
                # Retry once after rediscovery
                res2 = requests.post(url, headers=self.headers, json=payload, timeout=45)
                if res2.status_code == 200:
                    data = res2.json()
                    return data.get("choices", [{}])[0].get("message", {}).get("content")
                else:
                    raise RuntimeError(f"HTTP {res2.status_code}: {res2.text[:200]}")
            else:
                # GOD-TIER FIX: Raise the true error instead of silently returning None. 
                # This forces quota_manager to execute the precise Jitter Backoff loops.
                raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")
        except Exception as e:
            raise e

    def generate_text(self, prompt: str, role: str = "creative",
                      system_prompt: str = "You are a viral YouTube Shorts scriptwriter.",
                      throttle: bool = False) -> str | None:
        self._discover_models()
        if throttle:
            time.sleep(2)
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt}
            ],
            "temperature": 0.7,
        }
        return self._execute("chat/completions", payload)

    def generate_audio(self, text: str, output_filepath: str,
                       voice_override: str = None) -> bool:
        settings      = config_manager.get_settings()
        voice_actors  = settings.get("voice_actors", {})
        valid_voices  = voice_actors.get("groq", ["autumn", "diana"])

        if voice_override and voice_override in valid_voices:
            selected_voice = voice_override
        else:
            selected_voice = random.choice(valid_voices)

        print(f"🎙️ [GROQ TTS] Voice: {selected_voice.upper()}")
        payload = {
            "model": self.AUDIO_MODEL,
            "input": text,
            "voice": selected_voice,
            "response_format": "wav"
        }
        
        try:
            audio_bytes = self._execute("audio/speech", payload, is_audio=True)
            if audio_bytes:
                with open(output_filepath, "wb") as f:
                    f.write(audio_bytes)
                return True
        except Exception as e:
            print(f"❌ [GROQ TTS] Failed: {e}")
            return False
            
        return False

    def check_safety(self, text: str) -> bool:
        try:
            res = self.generate_text(
                f"Reply strictly with SAFE or UNSAFE. Is this safe? '{text}'",
                system_prompt="Content Moderator"
            )
            return not (res and "UNSAFE" in res.upper())
        except Exception:
            return True

groq_client = GroqAPIClient()
