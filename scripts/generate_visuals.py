import os
import requests
import urllib.parse
import time
import random
import subprocess
import base64

def generate_cloudflare_image(prompt, output_path):
    print("      [Tier 1: Cloudflare AI] Attempting Official FLUX generation...")
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    
    if not account_id or not api_token:
        return False, "Missing CF_ACCOUNT_ID or CF_API_TOKEN Secrets"
        
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
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
                    return True, ""
            # Fallback if CF returns binary directly
            with open(output_path, 'wb') as f: f.write(response.content)
            return True, ""
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, "Timeout/Connection Error"

def generate_pollinations_curl(prompt, output_path):
    print("      [Tier 2: Pollinations cURL] Attempting Cloudflare bypass...")
    seed = random.randint(1, 1000000)
    safe_prompt = urllib.parse.quote(f"{prompt}, vertical 9:16 format, cinematic, highly detailed")
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux&nologo=true&seed={seed}"
    
    try:
        cmd = [
            "curl", "-s", "-L", 
            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0", 
            "-o", output_path, 
            url
        ]
        subprocess.run(cmd, check=True, timeout=60)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 15000:
            return True, ""
        return False, "Cloudflare Blocked (Invalid File Size)"
    except Exception as e:
        return False, "cURL Failed"

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
            print("      [Tier 1: Cloudflare] Skipped (Previously Blocked/No Keys)")

        # 2. Tier 2: Pollinations cURL Bypass
        if not success and tier2_active:
            success, err = generate_pollinations_curl(prompt, output_path)
            if success: 
                final_provider = "Pollinations cURL Bypass"
            else:
                print(f"      🚨 [VISUALS] Tier 2 Failed ({err}). Disabling for remainder of run.")
                tier2_active = False 
        elif not success and not tier2_active:
            print("      [Tier 2: Pollinations cURL] Skipped (Previously Blocked)")
                
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
