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
        # Ordered fallback chain — first available model is used for text gen.
        self.TEXT_MODELS = ["llama-3.3-70b-versatile"]
        self._models_discovered = False

    # ── Groq text-model discovery (auto-add newest free models) ─────────────
    # Score known-good models by a preference ladder and treat ANY unknown
    # text model as usable (ranked below known ones). This means when Groq
    # ships a new free Llama/Qwen/DeepSeek model we pick it up automatically
    # without code changes.
    _TEXT_PREFERENCE = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]
    # Lightweight / task-specific models we never use for script generation.
    _NON_TEXT_MARKERS = ["whisper", "tts", "playai", "embed", "rerank", "vision", "guard"]

    def _score_text_model(self, model_id: str) -> int:
        n = model_id.lower()
        if any(marker in n for marker in self._NON_TEXT_MARKERS):
            return -1  # excluded from text generation
        for i, pref in enumerate(self._TEXT_PREFERENCE):
            if n == pref:
                return 1000 - i
        # Unknown but likely a text-in/text-out model — usable, ranked after known ones.
        return 10

    def _discover_models(self):
        if self._models_discovered or not self.api_key:
            return
        from engine.config_manager import config_manager
        try:
            settings = config_manager.get_settings()
            fallback_chain = settings.get("groq_model_fallback_chain", []) or \
                ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
            res = requests.get(f"{self.base_url}/models", headers=self.headers, timeout=10)
            if res.status_code == 200:
                raw_ids = [m["id"] for m in res.json().get("data", [])]
                scored = [(m, self._score_text_model(m)) for m in raw_ids]
                text_models = sorted([m for m, s in scored if s >= 0],
                                     key=lambda mid: self._score_text_model(mid), reverse=True)
                if text_models:
                    # Always ensure the static fallback chain is present at the end
                    # in case discovery misses a preferred model.
                    self.TEXT_MODELS = text_models + [
                        f for f in fallback_chain if f not in text_models
                    ]
                    print(f"🔍 [GROQ] Text model chain discovered: {self.TEXT_MODELS[:5]} ...")
                else:
                    self.TEXT_MODELS = fallback_chain
            else:
                self.TEXT_MODELS = fallback_chain
        except Exception:
            self.TEXT_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        self._models_discovered = True

    def generate_text(self, prompt: str, role: str = "creative",
                      system_prompt: str = None,
                      throttle: bool = False) -> str | None:
        self._discover_models()
        if throttle:
            time.sleep(2)

        # Ensure system_prompt is never None
        effective_system = system_prompt or "You are a viral YouTube Shorts scriptwriter."

        # Try each model in the discovered chain until one returns valid text.
        for model in self.TEXT_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": effective_system},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
            }
            # Enforce strict JSON output if the prompt explicitly demands it
            if "json" in prompt.lower() or "json" in effective_system.lower():
                payload["response_format"] = {"type": "json_object"}
            try:
                res = requests.post(f"{self.base_url}/chat/completions", headers=self.headers,
                                    json=payload, timeout=45)
                if res.status_code == 200:
                    content = res.json()["choices"][0]["message"]["content"]
                    if content:
                        print(f"🤖 [GROQ] Used {model}")
                        return content
                # 401/429/503 → move to next model; don't spam
            except Exception as e:
                print(f"⚠️ [GROQ] {model} failed: {e}")
                continue
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
