# scripts/groq_client.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #3 (SUPPORT) — Added voice_override parameter to generate_audio()
#
# Previously generate_audio() always picked a random Groq voice. Now it accepts
# an optional voice_override so generate_voice.py can pass the tone-mapped
# equivalent of the Kokoro voice the AI Director originally chose.
# If voice_override is None or not in the valid voice list, falls back to random
# as before — zero breaking change to any other caller.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import time
import requests
import random
from engine.config_manager import config_manager


class GroqAPIClient:
    def __init__(self):
        self.api_key          = os.environ.get("GROQ_API_KEY")
        self.base_url         = "https://api.groq.com/openai/v1"
        self.headers          = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        self.AUDIO_MODEL      = "canopylabs/orpheus-v1-english"
        self._models_discovered = False

    def _discover_models(self):
        if self._models_discovered:
            return
        if not self.api_key:
            self.TEXT_MODEL = "llama-3.3-70b-versatile"
            return

        print("🔍 [GROQ] Auto-discovering latest text models...")
        try:
            response = requests.get(
                f"{self.base_url}/models", headers=self.headers, timeout=15
            )
            if response.status_code == 200:
                data             = response.json()
                available_models = [m["id"] for m in data.get("data", [])]

                valid_text_models = []
                for m in available_models:
                    m_lower = m.lower()
                    if any(x in m_lower for x in ["whisper", "llava", "vision", "tool"]):
                        continue
                    valid_text_models.append(m)

                if valid_text_models:
                    def _score(name):
                        s, n = 0, name.lower()
                        if "llama"     in n: s += 30
                        if "versatile" in n: s += 20
                        if "instruct"  in n or "-it" in n: s += 10
                        if "3.3"       in n: s += 15
                        if "70b"       in n: s += 10
                        if "preview"   in n: s -= 20
                        return s

                    valid_text_models.sort(key=_score, reverse=True)
                    self.TEXT_MODEL       = valid_text_models[0]
                    self._models_discovered = True
                    print(f"✅ [GROQ] Model auto-selected: {self.TEXT_MODEL}")
                    return
        except Exception as e:
            print(f"⚠️ [GROQ] Discovery failed: {e}")

        self.TEXT_MODEL       = "llama-3.3-70b-versatile"
        self._models_discovered = True

    def _execute_request(self, endpoint, payload, is_audio=False):
        if not self.api_key:
            return None
        url = f"{self.base_url}/{endpoint}"

        for attempt in range(3):
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=45)
                if response.status_code == 200:
                    if is_audio:
                        return response.content
                    data = response.json()
                    if "choices" in data and data["choices"]:
                        return data["choices"][0]["message"]["content"]
                    print(f"⚠️ [GROQ] Unexpected JSON schema: {data}")
                    return None
                elif response.status_code in [429, 503]:
                    print(f"⚠️ [GROQ] Server busy (HTTP {response.status_code}). Attempt {attempt+1}/3. Waiting {15*(attempt+1)}s...")
                    time.sleep(15 * (attempt + 1))
                    continue
                elif response.status_code == 404:
                    print("⚠️ [GROQ] Model deprecated (404). Forcing rediscovery...")
                    self._models_discovered = False
                    return None
                else:
                    print(f"⚠️ [GROQ] HTTP {response.status_code}: {response.text}")
                    return None
            except Exception as e:
                print(f"⚠️ [GROQ] Network fail (attempt {attempt+1}/3): {e}")
                time.sleep(10)

        print("❌ [GROQ] Fatal: all retry attempts exhausted.")
        return None

    def generate_text(self, prompt, role="creative",
                      system_prompt="You are a viral YouTube Shorts scriptwriter.",
                      throttle=False):
        self._discover_models()
        if throttle:
            time.sleep(2)
        payload = {
            "model":    self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0.7,
        }
        res = self._execute_request("chat/completions", payload)
        if res is None and not self._models_discovered:
            self._discover_models()
            payload["model"] = self.TEXT_MODEL
            res = self._execute_request("chat/completions", payload)
        return res

    def generate_audio(self, text, output_filepath, voice_override=None):
        """
        Synthesize speech via Groq Orpheus TTS.

        Args:
            text:           Text to synthesize.
            output_filepath: Where to write the .wav file.
            voice_override: Optional — a specific Groq voice name to use.
                            If None or invalid, picks randomly from settings.
                            Added by Fix #3 so generate_voice.py can pass the
                            tone-mapped equivalent of the AI Director's Kokoro choice.
        """
        settings     = config_manager.get_settings()
        valid_voices = settings.get("voice_actors", {}).get("groq", ["autumn"])

        # ── FIX #3: Use the tone-mapped override if it's a valid Groq voice ──
        if voice_override and voice_override in valid_voices:
            selected_voice = voice_override
        else:
            selected_voice = random.choice(valid_voices)
        # ─────────────────────────────────────────────────────────────────────

        print(f"🎙️ [GROQ] Orpheus TTS — voice: '{selected_voice.upper()}'...")
        payload     = {
            "model":           self.AUDIO_MODEL,
            "input":           text,
            "voice":           selected_voice,
            "response_format": "wav",
        }
        audio_bytes = self._execute_request("audio/speech", payload, is_audio=True)
        if audio_bytes:
            try:
                with open(output_filepath, "wb") as f:
                    f.write(audio_bytes)
                return True
            except Exception as e:
                print(f"❌ [GROQ] Audio write failed: {e}")
                return False
        return False

    def check_safety(self, text_to_check):
        prompt = f"Reply strictly with SAFE or UNSAFE. Is this safe? '{text_to_check}'"
        res    = self.generate_text(prompt, system_prompt="Content Moderator")
        if res and "UNSAFE" in res.upper():
            return False
        return True


groq_client = GroqAPIClient()
