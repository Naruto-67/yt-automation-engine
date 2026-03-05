import os
import time
import requests
import json
import re

class GroqAPIClient:
    """
    Ghost Engine V4.0 - The Nervous System.
    Implements Adaptive Throttling, Model Waterfall Failovers, and 
    Safety Guardrails with a 2026-standard architecture.
    """
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 🛡️ THE WATERFALL FAILOVER QUEUES
        # If the primary model 404s (deprecated), the engine slides down the list.
        self.MODEL_QUEUES = {
            "creative": [
                "llama-3.3-70b-versatile", 
                "llama-3.1-70b-versatile",
                "llama3-70b-8192"
            ],
            "analyst": [
                "llama-3.3-70b-versatile",
                "mixtral-8x7b-32768"
            ],
            "safety": [
                "llama-guard-3-8b",       # Dedicated moderation model
                "llama3-8b-8192"          # Fast fallback
            ]
        }
        
        # Audio endpoint model
        self.AUDIO_MODEL = "canopylabs/orpheus-v1-english"

    # ==========================================
    # 🧠 THE ADAPTIVE THROTTLER (Loophole 4 Fix)
    # ==========================================
    def _handle_adaptive_pacing(self, response_headers):
        """
        Reads live headers from Groq to adaptively sleep, 
        ensuring we stay under the 30 RPM / 14.4k RPD ceiling.
        """
        try:
            # Check remaining requests in the current window
            remaining_reqs = int(response_headers.get('x-ratelimit-remaining-requests', 30))
            reset_time = response_headers.get('x-ratelimit-reset-requests', '1s')
            
            # If we are running low on requests (less than 5), pace ourselves
            if remaining_reqs < 5:
                # Convert reset string '3.4s' to float
                wait_seconds = float(re.sub(r'[a-zA-Z]', '', reset_time))
                print(f"🐢 [GROQ] Pacing Active: {remaining_reqs} reqs left. Cooling down {wait_seconds}s...")
                time.sleep(wait_seconds + 0.5)
        except Exception:
            pass # Failsafe: don't crash if headers change format

    # ==========================================
    # 🛡️ THE CORE EXECUTION ENGINE
    # ==========================================
    def _execute_request(self, endpoint, payload, is_audio=False, role="creative"):
        """
        The Master Execution Loop.
        Handles: Waterfall models, 45s Timeouts, 429 Retries, and 404 Failovers.
        """
        if not self.api_key:
            print("❌ [GROQ] GROQ_API_KEY is missing from environment.")
            return None

        url = f"{self.base_url}/{endpoint}"
        max_retries = 3
        
        # 🌊 Waterfall Logic: Select the model queue for this task
        model_pool = [self.AUDIO_MODEL] if is_audio else self.MODEL_QUEUES.get(role, self.MODEL_QUEUES["creative"])

        for model_name in model_pool:
            payload["model"] = model_name
            
            for strike in range(1, max_retries + 1):
                try:
                    # ⏲️ 45-Second Strict Timeout
                    response = requests.post(url, headers=self.headers, json=payload, timeout=45)
                    
                    # 🚦 Adaptive Throttling Update
                    self._handle_adaptive_pacing(response.headers)

                    # ✅ 200: SUCCESS
                    if response.status_code == 200:
                        if is_audio:
                            return response.content
                        return response.json()['choices'][0]['message']['content']

                    # 🛑 429: RATE LIMIT (Reactive Throttling)
                    elif response.status_code == 429:
                        wait_time = int(response.headers.get('retry-after', 10))
                        print(f"🛑 [GROQ] 429 Rate Limit. Sleeping {wait_time}s (Strike {strike})...")
                        time.sleep(wait_time + 1)
                        continue 

                    # ⚠️ 404: MODEL DEPRECATED (Waterfall Trigger)
                    elif response.status_code == 404:
                        print(f"⚠️ [GROQ] Model {model_name} is deprecated/offline. Cascading to fallback...")
                        break # Exits the strike loop to try the next model in the pool

                    # ❌ OTHER ERRORS
                    else:
                        print(f"⚠️ [GROQ] HTTP {response.status_code} Error: {response.text}")
                        time.sleep(5 * strike)
                        continue

                except requests.exceptions.Timeout:
                    print(f"⏳ [GROQ] STRIKE {strike}: Server Hang (45s reached).")
                    time.sleep(5 * strike)
                    continue
                        
                except requests.exceptions.RequestException as e:
                    print(f"❌ [GROQ] STRIKE {strike} Connection Error: {e}")
                    time.sleep(5 * strike)
                    continue

        print(f"🚨 [GROQ] FATAL: All failover models for role '{role}' failed.")
        return None

    # ==========================================
    # 📝 PUBLIC INTERFACE
    # ==========================================
    def generate_text(self, prompt, role="creative", system_prompt="You are a viral YouTube Shorts scriptwriter.", throttle=False):
        """
        Standard entry point for text generation.
        throttle: Adds a fixed 2.5s delay (for comment loops to avoid RPM spikes).
        """
        if throttle:
            time.sleep(2.5) # Hard pacing for tight loops
            
        print(f"⚡ [GROQ] Generating {role} content...")
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        return self._execute_request("chat/completions", payload, role=role)

    def generate_audio(self, text, output_filepath):
        """Generates high-fidelity audio via Orpheus."""
        print("🎙️ [GROQ] Initializing Orpheus TTS stream...")
        payload = {
            "input": text,
            "voice": "alloy",
            "response_format": "mp3"
        }
        
        audio_bytes = self._execute_request("audio/speech", payload, is_audio=True)
        
        if audio_bytes:
            try:
                with open(output_filepath, 'wb') as f:
                    f.write(audio_bytes)
                print(f"✅ [GROQ] Audio saved: {output_filepath}")
                return True
            except Exception as e:
                print(f"❌ [GROQ] Disk Write Error: {e}")
                return False
        return False

    def check_safety(self, text_to_check):
        """
        Uses Llama-Guard for content moderation. 
        Crucial for preventing comment-reply shadowbans.
        """
        print("🛡️ [GROQ] Executing Safety Audit...")
        
        system_msg = "You are a YouTube moderator. Reply strictly with the word 'SAFE' or 'UNSAFE'."
        prompt = f"Analyze this text for hate speech, spam, or toxic content: '{text_to_check}'"
        
        # Always throttle safety checks as they usually happen in loops
        result = self.generate_text(prompt, role="safety", system_prompt=system_msg, throttle=True)
        
        if result and "UNSAFE" in result.upper():
            print("🚨 [GROQ] SAFETY ALERT: Content flagged as UNSAFE.")
            return False
        return True

# Singleton Instance
groq_client = GroqAPIClient()
