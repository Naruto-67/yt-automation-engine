import os
import requests
import urllib.parse
import time

def generate_huggingface_image(prompt, output_path):
    print("      [HuggingFace] Attempting FLUX AI generation...")
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("      [HuggingFace] ⚠️ No HF_TOKEN found in environment secrets.")
        return False
        
    # 🚨 THE 410 FIX: New Router URL
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json"
    }
    
    enhanced_prompt = f"{prompt}, vertical 9:16 format, 8k resolution, masterpiece"
    payload = {"inputs": enhanced_prompt}
    
    for attempt in range(2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            elif response.status_code == 503:
                print(f"      [HuggingFace] ⏳ Model is booting up. Waiting 15 seconds...")
                time.sleep(15)
            else:
                print(f"      [HuggingFace] ⚠️ HTTP {response.status_code} - {response.text[:100]}")
        except Exception as e:
            print(f"      [HuggingFace] ⚠️ Error: {e}")
        time.sleep(2)
    return False

def fallback_pexels_image(prompt, output_path):
    print("      [Pexels] AI blocked. Attempting guaranteed stock image fallback...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("      [Pexels] ⚠️ No PEXELS_API_KEY found.")
        return False
        
    try:
        search_query = " ".join(prompt.split(',')[0].split(' ')[-2:]) 
        url = f"https://api.pexels.com/v1/search?query={search_query}&orientation=portrait&per_page=1"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        
        if res.get('photos'):
            img_url = res['photos'][0]['src']['large2x']
            img_data = requests.get(img_url, timeout=15).content
            with open(output_path, 'wb') as f:
                f.write(img_data)
            return True
        else:
            print(f"      [Pexels] ⚠️ No images found for query: {search_query}")
            return False
    except Exception as e:
        print(f"      [Pexels] ⚠️ Error: {e}")
        return False

def fetch_scene_images(prompts_list, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images (FORCING TIER 2: HUGGINGFACE)...")
    successful_images = []
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {prompt[:40]}...")
        
        # We are intentionally skipping Gemini here to test HuggingFace (Tier 2)
        success = generate_huggingface_image(prompt, output_path)
            
        # Ultimate Free Failsafe (Pexels Stock Image)
        if not success:
            success = fallback_pexels_image(prompt, output_path)
            
        if success:
            successful_images.append(output_path)
            print(f"   ✅ Scene {i+1} saved successfully.")
        else:
            print(f"   ❌ Scene {i+1} completely failed across all engines.")
            
        time.sleep(2) 
        
    return successful_images
