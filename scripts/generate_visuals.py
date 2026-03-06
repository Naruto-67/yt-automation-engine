import os
import requests
import urllib.parse
import time
import random

def generate_pollinations_image(prompt, output_path):
    print("      [Tier 1: Pollinations] Attempting Free FLUX AI generation...")
    try:
        # 🚨 POLLINATIONS FIX: Injecting a dynamic seed and a heavy, real-browser header stack to bypass Cloudflare
        seed = random.randint(1, 1000000)
        safe_prompt = urllib.parse.quote(f"{prompt}, vertical 9:16 format, cinematic, highly detailed, masterpiece")
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux&nologo=true&seed={seed}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive"
        }
        
        response = requests.get(url, headers=headers, timeout=60)
        
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True, ""
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, "Timeout/Connection Error"

def generate_huggingface_image(prompt, output_path):
    print("      [Tier 2: HuggingFace] Attempting FLUX AI fallback...")
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token: return False, "No Token"
        
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    payload = {"inputs": f"{prompt}, vertical 9:16 format, masterpiece"}
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                with open(output_path, 'wb') as f: 
                    f.write(response.content)
                return True, ""
            elif response.status_code == 402:
                # 🚨 HF QUOTA FIX: Immediate abort if payment is required
                return False, "HTTP 402 (Out of Quota)"
            elif response.status_code == 503:
                time.sleep(20)
            else:
                time.sleep(5)
        except:
            time.sleep(5)
            
    return False, "HF Failed/Timeout"

def fallback_pexels_image(prompt, output_path):
    print("      [Tier 3: Pexels] AI blocked. Attempting stock image fallback...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False, "No Key"
        
    try:
        # 🚨 PEXELS FIX: Skip the AI style prefix (e.g., "Photorealistic") by splitting at the first comma
        parts = prompt.split(',')
        core_subject = parts[1].strip() if len(parts) > 1 else prompt
        search_query = urllib.parse.quote(core_subject[:40]) 
        
        # Pull 15 images instead of 1
        url = f"https://api.pexels.com/v1/search?query={search_query}&orientation=portrait&per_page=15"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        
        if res.get('photos'):
            # Pick a random photo from the results to prevent duplicate scenes
            photo = random.choice(res['photos'])
            img_url = photo['src']['large2x']
            img_data = requests.get(img_url, timeout=15).content
            with open(output_path, 'wb') as f: f.write(img_data)
            return True, ""
    except Exception as e: 
        return False, "API Error"
    return False, "No images found"

def fetch_scene_images(prompts_list, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images via Decoupled 3-Tier System...")
    successful_images = []
    
    tier1_active = True
    tier2_active = True
    final_provider = "Unknown"
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {prompt[:40]}...")
        
        success = False
        
        # 1. Primary Engine: Pollinations (Bypassing Cloudflare)
        if tier1_active:
            success, err = generate_pollinations_image(prompt, output_path)
            if success: 
                final_provider = "Pollinations FLUX"
            else:
                print(f"      🚨 [VISUALS] Tier 1 Failed ({err}). Disabling for remainder of run.")
                tier1_active = False 
        else:
            print("      [Tier 1: Pollinations] Skipped (Previously Blocked)")

        # 2. Hugging Face Fallback
        if not success and tier2_active:
            success, err = generate_huggingface_image(prompt, output_path)
            if success: 
                final_provider = "HuggingFace FLUX (Fallback)"
            else:
                print(f"      🚨 [VISUALS] Tier 2 Failed ({err}). Disabling for remainder of run.")
                tier2_active = False 
        elif not success and not tier2_active:
            print("      [Tier 2: HuggingFace] Skipped (Previously Blocked)")
                
        # 3. Stock Fallback
        if not success:
            success, err = fallback_pexels_image(prompt, output_path)
            if success: 
                final_provider = "Pexels Stock (Double Fallback)"
            
        if success:
            successful_images.append(output_path)
            print(f"   ✅ Scene {i+1} saved successfully.")
        else:
            print(f"   ❌ Scene {i+1} failed completely.")
            
        print("   ⏳ Pacing generation engines (Sleeping 3s)...")
        time.sleep(3) 
        
    return successful_images, final_provider
