# scripts/groq_client.py
import os
import time
import traceback
import requests
from engine.config_manager import config_manager

# Known PlayAI voice fallbacks — used if the configured groq voice names
# are not accepted by the active TTS model endpoint.
_GROQ_TTS_VOICE_FALLBACKS = ["Fritz-PlayAI", "Celeste-PlayAI", "Chip-PlayAI"]


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

        # Ensure system_prompt is never None
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

    def generate_audio(self, text: str, output_path: str, voice_override: str = None) -> bool:
        """
        Generate TTS audio using Groq's speech API (Orpheus / PlayAI backend).

        The method tries each model in groq_tts_models (from settings.yaml) in order.
        For each model it tries: the requested voice → all configured groq voices →
        known PlayAI fallback voices. This ensures audio is always produced even if
        a specific voice name is not supported by a particular model version.

        Parameters
        ----------
        text          : script text to synthesise (max 4096 chars per request)
        output_path   : destination .wav file path
        voice_override: specific voice name to prefer (from kokoro_to_groq_map)

        Returns
        -------
        True if a valid audio file was written, False if all models/voices failed.
        """
        if not self.api_key:
            print("⚠️ [GROQ TTS] No GROQ_API_KEY configured. Skipping audio generation.")
            return False

        settings = config_manager.get_settings()
        tts_models    = settings.get("groq_tts_models", ["playai-tts"])
        groq_voices   = settings.get("voice_actors", {}).get("groq", [])

        # Build voice candidate list: requested → configured → PlayAI fallbacks
        # Deduplicate while preserving order
        seen            = set()
        voice_candidates = []
        if voice_override:
            voice_candidates.append(voice_override)
        voice_candidates.extend(groq_voices)
        voice_candidates.extend(_GROQ_TTS_VOICE_FALLBACKS)
        voice_candidates = [v for v in voice_candidates if not (v in seen or seen.add(v))]

        # Audio headers differ from text headers (no Content-Type override needed for binary)
        audio_headers = {"Authorization": f"Bearer {self.api_key}"}

        for model in tts_models:
            for voice in voice_candidates[:4]:   # Try up to 4 voices per model
                try:
                    payload = {
                        "model":           model,
                        "input":           text[:4096],
                        "voice":           voice,
                        "response_format": "wav",
                    }
                    resp = requests.post(
                        f"{self.base_url}/audio/speech",
                        headers={**audio_headers, "Content-Type": "application/json"},
                        json=payload,
                        timeout=60,
                    )

                    if resp.status_code == 200:
                        with open(output_path, "wb") as f:
                            f.write(resp.content)
                        size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                        if size > 1000:
                            print(f"✅ [GROQ TTS] {model} | Voice: {voice} | {size // 1024} KB")
                            return True
                        # File too small — empty or corrupt response
                        print(f"⚠️ [GROQ TTS] {model}/{voice} returned suspiciously small file ({size} bytes). Trying next voice.")
                        continue

                    elif resp.status_code in (400, 422):
                        # Voice name not recognized by this model — try the next voice
                        err_snippet = resp.text[:150] if resp.text else "(empty)"
                        print(f"⚠️ [GROQ TTS] {model}/{voice} rejected (HTTP {resp.status_code}): {err_snippet}")
                        continue

                    else:
                        # Non-voice error (auth, rate limit, server error) — skip this model
                        print(f"⚠️ [GROQ TTS] {model}/{voice} → HTTP {resp.status_code}. Skipping model.")
                        break

                except requests.exceptions.Timeout:
                    print(f"⚠️ [GROQ TTS] {model}/{voice} timed out. Trying next.")
                    break
                except Exception:
                    trace = traceback.format_exc()
                    print(f"⚠️ [GROQ TTS] {model}/{voice} exception:\n{trace}")
                    break

        print("❌ [GROQ TTS] All TTS models and voice candidates exhausted.")
        return False


groq_client = GroqAPIClient()
