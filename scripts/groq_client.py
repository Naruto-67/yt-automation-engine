import os
import time
import requests

class GroqAPIClient:
    """
    Dedicated 2026 Groq API Handler.
    Enforces TPM pacing, 45-second timeouts, and parses 'retry-after' headers.
    """
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 2026 Model Roster
        self.MODELS = {
            "creative": "llama-3.3-70b-versatile",
            "analyst": "openai/gpt-oss-120b",
            "safety": "openai/gpt-oss-safeguard-20b",
            "vision": "meta-llama/llama-4-scout-17b-16e-instruct",
            "voice": "canopylabs/orpheus-v1-english"
        }

    # ==========================================
    # 🛡️ THE CORE ENGINE (3x45s & Header Logic)
    # ==========================================
    def _execute_request(self, endpoint, payload, is_audio=False):
        """
        The universal execution engine for all Groq calls.
        Handles the 3-strike rule, 45s timeout, and precise sleeping.
        """
        if not self.api_key:
            print("❌ [GROQ API] Error: GROQ_API_KEY is missing from environment.")
            return None

        url = f"{self.base_url}/{endpoint}"
        max_strikes = 3

        for strike in range(1, max_strikes + 1):
            try:
                # 45-Second Timeout enforced on every call to prevent silent hangs
                response = requests.post(url, headers=self.headers, json=payload, timeout=45)

                # SUCCESS
                if response.status_code == 200:
                    tokens_left = response.headers.get('x-ratelimit-remaining-tokens', 'N/A')
                    reqs_left = response.headers.get('x-ratelimit-remaining-requests', 'N/A')
                    print(f"✅ [GROQ API] Success. Remaining - Tokens: {tokens_left} | Reqs: {reqs_left}")
                    
                    if is_audio:
                        return response.content # Return raw bytes for MP3 saving
                    return response.json()['choices'][0]['message']['content'] # Return Text

                # 429 RATE LIMIT (The 2026 Header Fix)
                elif response.status_code == 429:
                    wait_time = int(response.headers.get('retry-after', 10))
                    print(f"🛑 [GROQ API] 429 Rate Limit. Exact sleep required: {wait_time}s...")
                    time.sleep(wait_time + 1) # Wait exactly what Groq demands + 1s buffer
                    continue # Try again after sleeping (uses a strike)

                # SERVER ERROR OR OTHER
                else:
                    print(f"⚠️ [GROQ API] HTTP {response.status_code} Error: {response.text}")
                    if strike < max_strikes:
                        time.sleep(5 * strike)
                        continue

            except requests.exceptions.Timeout:
                print(f"⏳ [GROQ API] STRIKE {strike}: 45-Second Timeout Reached. Server hang.")
                if strike < max_strikes:
                    time.sleep(5 * strike)
                    continue
                    
            except requests.exceptions.RequestException as e:
                print(f"❌ [GROQ API] STRIKE {strike} Connection Error: {e}")
                if strike < max_strikes:
                    time.sleep(5 * strike)
                    continue

        print(f"🚨 [GROQ API] FATAL: Failed after {max_strikes} attempts.")
        return None

    # ==========================================
    # 📝 PUBLIC METHODS (Text, Voice, Safety)
    # ==========================================
    def generate_text(self, prompt, role="creative", system_prompt="You are an expert YouTube assistant."):
        """Generates text using Llama 3.3 or GPT OSS 120B."""
        model = self.MODELS.get(role, self.MODELS["creative"])
        print(f"⚡ [GROQ] Tasking {model.split('/')[-1]}...")
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        return self._execute_request("chat/completions", payload)

    def generate_audio(self, text, output_filepath):
        """Generates TTS audio via Orpheus and saves it to a file."""
        print("🎙️ [GROQ] Tasking Orpheus TTS API...")
        
        payload = {
            "model": self.MODELS["voice"],
            "input": text,
            "voice": "alloy", # Default highly expressive voice for Orpheus
            "response_format": "mp3"
        }
        
        audio_bytes = self._execute_request("audio/speech", payload, is_audio=True)
        
        if audio_bytes:
            try:
                with open(output_filepath, 'wb') as f:
                    f.write(audio_bytes)
                print(f"✅ [GROQ] Audio securely saved to {output_filepath}")
                return True
            except Exception as e:
                print(f"❌ [GROQ] Failed to save audio file: {e}")
                return False
        return False

    def check_safety(self, comment_reply):
        """Uses the Safeguard 20B model to ensure we don't post anything that gets the channel banned."""
        print("🛡️ [GROQ] Running Safety/Moderation Check...")
        
        system_prompt = "You are a content moderator. Reply strictly with the word 'SAFE' or 'UNSAFE'."
        prompt = f"Analyze this comment reply for a YouTube video. Is it safe, brand-friendly, and free of hate speech/spam?\n\nReply: '{comment_reply}'"
        
        result = self.generate_text(prompt, role="safety", system_prompt=system_prompt)
        
        if result and "UNSAFE" in result.upper():
            print("🚨 [GROQ] Moderation Alert: Reply flagged as UNSAFE.")
            return False
        return True

# Initialize a singleton instance to be imported by other files
groq_client = GroqAPIClient()
