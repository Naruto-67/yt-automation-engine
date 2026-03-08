# scripts/groq_client.py
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
        self._models_discovered = False

    def _discover_models(self):
        """Auto-discovers and scores the best available Groq model."""
        if self._models_discovered:
            return
            
        if not self.api_key:
            self.TEXT_MODEL = "llama-3.3-70b-versatile"
            return

        print("🔍 [GROQ] Auto-discovering latest text models...")
        try:
            response = requests.get(f"{self.base_url}/models", headers=self.headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                available_models = [m['id'] for m in data.get('data', [])]
                
                valid_text_models = []
                for m in available_models:
                    m_lower = m.lower()
                    # Filter out audio, whisper, and vision models
                    if 'whisper' in m_lower or 'llava' in m_lower or 'vision' in m_lower or 'tool' in m_lower:
                        continue
                    valid_text_models.append(m)
                    
                if valid_text_models:
                    def _score(name):
                        s = 0
                        n = name.lower()
                        # Reward versatile/instruct models
                        if 'llama' in n: s += 30
                        if 'versatile' in n: s += 20
                        if 'instruct' in n or '-it' in n: s += 10
                        # Reward higher parameter counts implicitly by generation/version
                        if '3.3' in n: s += 15
                        if '70b' in n: s += 10
                        # Penalize previews
                        if 'preview' in n: s -= 20
                        return s
                        
                    valid_text_models.sort(key=_score, reverse=True)
                    self.TEXT_MODEL = valid_text_models[0]
                    print(f"✅ [GROQ] Model auto-selected: {self.TEXT_MODEL}")
                    self._models_discovered = True
                    return
        except Exception as e:
            print(f"⚠️ [GROQ] Discovery failed: {e}")

        # Failsafe Fallback
        self.TEXT_MODEL = "llama-3.3-70b-versatile"
        self._models_discovered = True

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
                elif response.status_code == 404:
                    print(f"⚠️ [GROQ] Model deprecated (404). Forcing rediscovery...")
                    self._models_discovered = False
                    return None
                else:
                    print(f"⚠️ [GROQ] HTTP {response.status_code} Error: {response.text}")
                    return None
            except Exception as e:
                print(f"⚠️ [GROQ] Network fail (Attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(10)
                
        print("❌ [GROQ] Fatal Failure: All retry attempts exhausted.")
        return None

    def generate_text(self, prompt, role="creative", system_prompt="You are a viral YouTube Shorts scriptwriter.", throttle=False):
        self._discover_models()
        if throttle:
            time.sleep(2)
            
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        
        res = self._execute_request("chat/completions", payload)
        
        # If the API returned a 404 (model suddenly deprecated), discover again and retry once
        if res is None and not self._models_discovered:
            self._discover_models()
            payload["model"] = self.TEXT_MODEL
            res = self._execute_request("chat/completions", payload)
            
        return res

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
