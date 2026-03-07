import os
import time
import requests
import random

class GroqAPIClient:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.AUDIO_MODEL = "canopylabs/orpheus-v1-english"

    def _execute_request(self, endpoint, payload, is_audio=False):
        if not self.api_key:
            return None
        url = f"{self.base_url}/{endpoint}"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=45)
                if response.status_code == 200:
                    if is_audio:
                        return response.content
                    
                    # 🚨 FIX: Safe Dictionary Parsing prevents unhandled KeyErrors if Groq returns moderation flags instead of 'choices'
                    data = response.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        return data['choices'][0]['message']['content']
                    else:
                        print(f"⚠️ [GROQ] Unexpected JSON schema received: {data}")
                        return None
                        
                elif response.status_code in [429, 503]:
                    print(f"⚠️ [GROQ] Server Busy (HTTP {response.status_code}). Attempt {attempt+1}/{max_retries}. Retrying in 15s...")
                    time.sleep(15 * (attempt + 1))
                    continue
                else:
                    print(f"⚠️ [GROQ] HTTP {response.status_code} Error: {response.text}")
                    return None
            except Exception as e:
                print(f"⚠️ [GROQ] Network fail (Attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(10)
                
        print("❌ [GROQ] Fatal Failure: All retry attempts exhausted.")
        return None

    def generate_text(self, prompt, role="creative", system_prompt="You are a viral YouTube Shorts scriptwriter.", throttle=False):
        if throttle:
            time.sleep(2)
            
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        return self._execute_request("chat/completions", payload)

    def generate_audio(self, text, output_filepath):
        valid_voices = ["autumn", "diana", "hannah", "austin", "daniel", "troy"]
        selected_voice = random.choice(valid_voices)
        
        print(f"🎙️ [GROQ] Initializing Orpheus TTS with voice: '{selected_voice.upper()}'...")
        
        payload = {
            "model": self.AUDIO_MODEL,
            "input": text,
            "voice": selected_voice,
            "response_format": "wav" 
        }
        
        audio_bytes = self._execute_request("audio/speech", payload, is_audio=True)
        if audio_bytes:
            try:
                with open(output_filepath, 'wb') as f:
                    f.write(audio_bytes)
                return True
            except Exception as e:
                print(f"❌ [GROQ] Audio write failed: {e}")
                return False
        return False

    def check_safety(self, text_to_check):
        prompt = f"Reply strictly with SAFE or UNSAFE. Is this safe? '{text_to_check}'"
        res = self.generate_text(prompt, system_prompt="Content Moderator")
        if res and "UNSAFE" in res.upper():
            return False
        return True

groq_client = GroqAPIClient()
