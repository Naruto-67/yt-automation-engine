import os
import requests
import time
from google import genai
from google.genai import types

def generate_gemini_image(prompt, output_path):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return False, "No Key"
        
    client = genai.Client(api_key=api_key)
    enhanced_prompt = f"{prompt}, cinematic lighting, highly detailed"
    
    # 🚨 THE IMMORTAL RESOLVER: Ranked list of image models to try
    IMAGE_MODELS = [
        'gemini-2.0-flash',       # The docs confirmed this is free for images
        'gemini-2.5-flash-image', # The new Nano Banana
        'gemini-1.5-flash'        # Legacy fallback
    ]
    
    for model_name in IMAGE_MODELS:
        print(f"      [Tier 1: Gemini] Attempting via {model_name}...")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=enhanced_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="9:16")
                )
            )
            for part in response.parts:
                if part.inline_data is not None:
                    image = part.as_image()
                    image.convert('RGB').save(output_path, format="JPEG")
                    return True, model_name
                    
        except Exception as e:
            error_msg = str(e).lower()
            if "404" in error_msg or "not found" in error_msg:
                print(f"      ⚠️ {model_name} unavailable. Cascading...")
                continue
            elif "400" in error_msg or "paid" in error_msg or "invalid" in error_msg:
                print(f"      ⚠️ {model_name} is Paywalled. Cascading...")
                continue
            else:
                print(f"      [Gemini] ⚠️ Failed on {model_name}: {e}")
                return False, "Error"
                
    return False, "All Gemini Models Failed/Paywalled"

def generate_huggingface_image(prompt, output_path):
    print("      [Tier 2: HuggingFace] Attempting FLUX AI generation...")
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token: return False
        
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    payload = {"inputs": f"{prompt}, vertical 9:16 format, masterpiece"}
    
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
    print("      [Tier 3: Pexels] AI blocked. Attempting guaranteed stock fallback...")
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
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images via Dynamic 3-Tier System...")
    successful_images = []
    primary_provider = "Unknown"
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {prompt[:40]}...")
        
        # 1. Try the Immortal Gemini Cascade
        success, prov_name = generate_gemini_image(prompt, output_path)
        if success: 
            primary_provider = prov_name
        
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
            
        print("   ⏳ Pacing generation engines to prevent IP bans (Sleeping 6s)...")
        time.sleep(6) 
        
    return successful_images, primary_provider
