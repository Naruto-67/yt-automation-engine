import os
import requests
import urllib.parse
import time
from google import genai

def generate_gemini_image(prompt, output_path):
    print("      [Tier 1: Gemini] Attempting Imagen generation...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return False
        
    try:
        client = genai.Client(api_key=api_key)
        enhanced_prompt = f"{prompt}, cinematic lighting, 8k, highly detailed"
        result = client.models.generate_images(
            model='imagen-3.0-generate-001',
            prompt=enhanced_prompt,
            config=dict(number_of_images=1, aspect_ratio="9:16", output_mime_type="image/jpeg")
        )
        with open(output_path, 'wb') as f: f.write(result.generated_images[0].image.image_bytes)
        return True
    except Exception as e:
        print(f"      [Gemini] ⚠️ Failed: {e}")
        return False

def generate_huggingface_image(prompt, output_path):
    print("      [Tier 2: HuggingFace] Attempting FLUX AI generation...")
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token: return False
        
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    payload = {"inputs": f"{prompt}, vertical 9:16 format, 8k resolution, masterpiece"}
    
    for attempt in range(2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            if response.status_code == 200:
                with open(output_path, 'wb') as f: f.write(response.content)
                return True
            elif response.status_code == 503:
                time.sleep(15)
        except: pass
        time.sleep(2)
    return False

def fallback_pexels_image(prompt, output_path):
    print("      [Tier 3: Pexels] AI blocked. Attempting guaranteed stock image fallback...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False
        
    try:
        search_query = " ".join(prompt.split(',')[0].split(' ')[-2:]) 
        url = f"https://api.pexels.com/v1/search?query={search_query}&orientation=portrait&per_page=1"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        if res.get('photos'):
            img_url = res['photos'][0]['src']['large2x']
            img_data = requests.get(img_url, timeout=15).content
            with open(output_path, 'wb') as f: f.write(img_data)
            return True
    except: pass
    return False

def fetch_scene_images(prompts_list, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images via 3-Tier System...")
    successful_images = []
    primary_provider = "Unknown"
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {prompt[:40]}...")
        
        # 1. Try Gemini
        success = generate_gemini_image(prompt, output_path)
        if success: primary_provider = "Gemini Imagen 3"
        
        # 2. Try Hugging Face Fallback
        if not success:
            success = generate_huggingface_image(prompt, output_path)
            if success: primary_provider = "HuggingFace FLUX"
            
        # 3. Try Stock Fallback
        if not success:
            success = fallback_pexels_image(prompt, output_path)
            if success: primary_provider = "Pexels Stock"
            
        if success:
            successful_images.append(output_path)
            print(f"   ✅ Scene {i+1} saved successfully.")
        else:
            print(f"   ❌ Scene {i+1} failed completely.")
            
        # 🚨 THE PACING PROTOCOL: Sleep 6s to prevent IP/RPM bans across all services
        print("   ⏳ Pacing generation engines to prevent IP bans (Sleeping 6s)...")
        time.sleep(6) 
        
    return successful_images, primary_provider
