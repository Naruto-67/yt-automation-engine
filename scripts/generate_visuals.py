import os
import requests
import urllib.parse
import time
import random
import subprocess
import base64
from scripts.quota_manager import quota_manager

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
    
    # Pre-emptively truncate massively long prompts to protect the payload format
    safe_prompt = prompt[:200].replace('"', '').replace('\n', ' ')
    payload = {"prompt": f"{safe_prompt}, vertical 9:16 format, masterpiece"}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
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
        elif response.status_code == 400:
            # 🚨 FIX: Specifically catch safety filter rejections
            return False, "HTTP 400 (Safety Filter / Prompt Rejected)"
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
        
    models = [
        "black-forest-labs/FLUX.1-schnell",
        "stabilityai/stable-diffusion-xl-base-1.0"
    ]
    
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    safe_prompt = prompt[:200].replace('"', '').replace('\n', ' ')
    payload = {"inputs": f"{safe_prompt}, vertical 9:16 format, masterpiece"}
    
    for model in models:
        short_name = model.split('/')[-1]
        print(f"      -> Routing to {short_name}...")
        
        if SIMULATE_CASCADE_TEST and "FLUX" in model:
            print(f"      ⚠️ {short_name} out of free quota (Simulated). Switching models...")
            continue
            
        url = f"https://api-inference.huggingface.co/models/{model}"
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
            if response.status_code == 200:
                with open(output_path, 'wb') as f: 
                    f.write(response.content)
                quota_manager.consume_points("huggingface", 1)
                return True, f"HF ({short_name})"
            elif response.status_code == 400:
                print(f"      ⚠️ {short_name} rejected prompt (Safety Filter). Switching models...")
                continue
            elif response.status_code in [401, 402, 403]:
                print(f"      ⚠️ {short_name} out of free quota or unauthorized. Switching models...")
                continue 
            elif response.status_code == 503:
                print(f"      💤 {short_name} asleep. Waiting 20s...")
                time.sleep(20)
                response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
                if response.status_code == 200:
                    with open(output_path, 'wb') as f: f.write(response.content)
                    quota_manager.consume_points("huggingface", 1)
                    return True, f"HF ({short_name})"
        except: pass
            
    return False, "HF Models Exhausted/Blocked"

def fallback_pexels_image(search_query, output_path, is_retry=False):
    print(f"      [Tier 3: Pexels] AI Blocked. Searching strictly for: '{search_query}'...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False, "No Key"
        
    try:
        query = urllib.parse.quote(search_query) 
        url = f"https://api.pexels.com/v1/search?query={query}&orientation=portrait&per_page=15"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=(10, 30)).json()
        
        if res.get('photos') and len(res['photos']) > 0:
            photo = random.choice(res['photos'])
            img_url = photo['src']['large2x']
            img_data = requests.get(img_url, timeout=(10, 30)).content
            with open(output_path, 'wb') as f: f.write(img_data)
            return True, ""
            
        elif not is_retry:
            print(f"      ⚠️ [Tier 3: Pexels] 0 results for '{search_query}'. Deploying Universal Fallback...")
            return fallback_pexels_image("cinematic aesthetic background", output_path, is_retry=True)
            
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
        
        if tier1_active:
            success, err = generate_cloudflare_image(prompt, output_path)
            if success: 
                final_provider = "Cloudflare FLUX API"
            else:
                # 🚨 FIX: Safety Filter Awareness. Do NOT permanently disable Cloudflare if it just rejected one prompt!
                if "400" in err or "Timeout" in err:
                    print(f"      ⚠️ [VISUALS] Tier 1 localized failure ({err}). Keeping active for next scene.")
                else:
                    print(f"      🚨 [VISUALS] Tier 1 Fatal Quota/Auth Error ({err}). Disabling for remainder of run.")
                    tier1_active = False 
        else:
            print("      [Tier 1: Cloudflare] Skipped (Previously Blocked)")

        if not success and tier2_active:
            success, err = generate_huggingface_cascade(prompt, output_path)
            if success: 
                final_provider = err 
            else:
                if "400" in err or "Timeout" in err:
                    print(f"      ⚠️ [VISUALS] Tier 2 localized failure ({err}). Keeping active for next scene.")
                else:
                    print(f"      🚨 [VISUALS] Tier 2 Fatal Quota/Auth Error ({err}). Disabling for remainder of run.")
                    tier2_active = False 
        elif not success and not tier2_active:
            print("      [Tier 2: Hugging Face] Skipped (Previously Blocked)")
                
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
