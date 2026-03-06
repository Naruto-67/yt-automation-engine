import os
import requests
import urllib.parse
import time
import random
import subprocess
import base64
from scripts.quota_manager import quota_manager

# 🚨 FALLBACK TEST FLAG: Turned OFF for production. It will now actually use Cloudflare/HF.
SIMULATE_CASCADE_TEST = False 

def generate_cloudflare_image(prompt, output_path):
    print("      [Tier 1: Cloudflare AI] Attempting Official FLUX generation...")
    
    if SIMULATE_CASCADE_TEST or quota_manager.is_provider_exhausted("cloudflare"):
        return False, "Simulated Test Failure / Quota Reached"
        
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    
    if not account_id or not api_token:
        return False, "Missing CF Credentials"
        
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    payload = {"prompt": f"{prompt}, vertical 9:16 format, masterpiece"}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data = response.json()
                if "result" in data and "image" in data["result"]:
                    img_data = base64.b64decode(data["result"]["image"])
                    with open(output_path, 'wb') as f: f.write(img_data)
                    quota_manager.consume_points("cloudflare", 1)
                    return True, ""
            with open(output_path, 'wb') as f: f.write(response.content)
            quota_manager.consume_points("cloudflare", 1)
            return True, ""
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, "Timeout/Connection Error"

def generate_huggingface_cascade(prompt, output_path):
    print("      [Tier 2: HuggingFace] Attempting AI generation...")
    
    if quota_manager.is_provider_exhausted("huggingface"):
        return False, "HF Quota Reached"
        
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token: return False, "No Token"
        
    # 🚨 THE CASCADE: FLUX -> SDXL
    models = [
        "black-forest-labs/FLUX.1-schnell",
        "stabilityai/stable-diffusion-xl-base-1.0"
    ]
    
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    payload = {"inputs": f"{prompt}, vertical 9:16 format, masterpiece"}
    
    for model in models:
        short_name = model.split('/')[-1]
        print(f"      -> Routing to {short_name}...")
        
        if SIMULATE_CASCADE_TEST and "FLUX" in model:
            print(f"      ⚠️ {short_name} out of free quota (Simulated). Switching models...")
            continue
            
        url = f"https://api-inference.huggingface.co/models/{model}"
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                with open(output_path, 'wb') as f: 
                    f.write(response.content)
                quota_manager.consume_points("huggingface", 1)
                return True, f"HF ({short_name})"
            elif response.status_code == 402:
                print(f"      ⚠️ {short_name} out of free quota. Switching models...")
                continue 
            elif response.status_code == 503:
                print(f"      💤 {short_name} asleep. Waiting 20s...")
                time.sleep(20)
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    with open(output_path, 'wb') as f: f.write(response.content)
                    quota_manager.consume_points("huggingface", 1)
                    return True, f"HF ({short_name})"
        except: pass
            
    return False, "HF Models Exhausted/Blocked"

def fallback_pexels_image(search_query, output_path):
    print(f"      [Tier 3: Pexels] AI Blocked. Searching strictly for: '{search_query}'...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False, "No Key"
        
    try:
        query = urllib.parse.quote(search_query) 
        url = f"https://api.pexels.com/v1/search?query={query}&orientation=portrait&per_page=15"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        
        if res.get('photos'):
            photo = random.choice(res['photos'])
            img_url = photo['src']['large2x']
            img_data = requests.get(img_url, timeout=15).content
            with open(output_path, 'wb') as f: f.write(img_data)
            return True, ""
    except Exception as e: 
        return False, "API Error"
    return False, "No images found"

def fetch_scene_images(prompts_list, pexels_queries, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images via Decoupled 3-Tier System...")
    successful_images = []
    
    tier1_active = True
    tier2_active = True
    final_provider = "Unknown"
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {prompt[:40]}...")
        
        success = False
        
        # 1. Tier 1: Cloudflare AI (Official API)
        if tier1_active:
            success, err = generate_cloudflare_image(prompt, output_path)
            if success: 
                final_provider = "Cloudflare FLUX API"
            else:
                print(f"      🚨 [VISUALS] Tier 1 Failed ({err}). Disabling for remainder of run.")
                tier1_active = False 
        else:
            print("      [Tier 1: Cloudflare] Skipped (Previously Blocked)")

        # 2. Tier 2: Hugging Face Cascade (FLUX -> SDXL)
        if not success and tier2_active:
            success, err = generate_huggingface_cascade(prompt, output_path)
            if success: 
                final_provider = err 
            else:
                print(f"      🚨 [VISUALS] Tier 2 Failed ({err}). Disabling for remainder of run.")
                tier2_active = False 
        elif not success and not tier2_active:
            print("      [Tier 2: Hugging Face] Skipped (Previously Blocked)")
                
        # 3. Tier 3: Pexels Dedicated Query Fallback
        if not success:
            success, err = fallback_pexels_image(pexels_queries[i], output_path)
            if success: 
                final_provider = "Pexels Stock Fallback"
            
        if success:
            successful_images.append(output_path)
            print(f"   ✅ Scene {i+1} saved successfully.")
        else:
            print(f"   ❌ Scene {i+1} failed completely.")
            
        print("   ⏳ Pacing generation engines (Sleeping 3s)...")
        time.sleep(3) 
        
    return successful_images, final_provider
