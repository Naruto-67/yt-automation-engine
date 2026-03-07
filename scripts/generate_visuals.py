import os
import requests
import urllib.parse
import time
import random
import subprocess
import base64
import re
from PIL import Image, ImageDraw, ImageFilter
from scripts.quota_manager import quota_manager

SIMULATE_CASCADE_TEST = False 

# 🚨 FIX: Mathematical Visual Padding. Intercepts 1:1 AI Squares and converts them to professional 9:16 blurred-background layouts to stop FFmpeg from over-cropping the subjects.
def apply_cinematic_padding(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        target_w, target_h = 1080, 1920
        
        img_ratio = img.width / img.height
        target_ratio = target_w / target_h
        
        # If the image isn't already perfectly vertical (like standard 1:1 AI gens)
        if abs(img_ratio - target_ratio) > 0.1: 
            # 1. Stretch and heavily blur the background
            bg = img.resize((target_w, int(target_w / img_ratio)), Image.Resampling.LANCZOS)
            bg = bg.resize((target_w, target_h), Image.Resampling.LANCZOS) 
            bg = bg.filter(ImageFilter.GaussianBlur(50))
            
            # 2. Resize original foreground to fit perfectly inside the frame
            fg = img.copy()
            fg.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            
            # 3. Paste sharp foreground into blurred background
            offset = ((target_w - fg.width) // 2, (target_h - fg.height) // 2)
            bg.paste(fg, offset)
            bg.save(image_path, "JPEG", quality=95)
        else:
            # If it's already vertical, just standardise size
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            img.save(image_path, "JPEG", quality=95)
    except Exception as e:
        print(f"      ⚠️ [VISUALS] Cinematic padding failed, proceeding with raw image: {e}")

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
                    apply_cinematic_padding(output_path)
                    quota_manager.consume_points("cloudflare", 1)
                    return True, ""
            with open(output_path, 'wb') as f: f.write(response.content)
            apply_cinematic_padding(output_path)
            quota_manager.consume_points("cloudflare", 1)
            return True, ""
        elif response.status_code == 400:
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
                apply_cinematic_padding(output_path)
                quota_manager.consume_points("huggingface", 1)
                return True, f"HF ({short_name})"
            elif response.status_code == 400:
                print(f"      ⚠️ {short_name} rejected prompt (Safety Filter). Switching models...")
                continue
            elif response.status_code in [401, 402, 403]:
                print(f"      ⚠️ {short_name} out of free quota or unauthorized. Switching models...")
                continue 
            elif response.status_code >= 500:
                print(f"      💤 {short_name} experiencing gateway issues. Waiting 15s...")
                time.sleep(15)
                response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
                if response.status_code == 200:
                    with open(output_path, 'wb') as f: f.write(response.content)
                    apply_cinematic_padding(output_path)
                    quota_manager.consume_points("huggingface", 1)
                    return True, f"HF ({short_name})"
        except: pass
            
    return False, "HF Models Exhausted/Blocked"

def fallback_pexels_image(search_query, output_path, is_retry=False):
    clean_query = re.sub(r'[^a-zA-Z\s]', '', search_query).strip()
    words = [w for w in clean_query.split() if len(w) > 2]
    safe_query = " ".join(words[:2]) if words else "cinematic background"
    
    print(f"      [Tier 3: Pexels] AI Blocked. Searching strictly for: '{safe_query}'...")
    
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False, "No Key"
        
    try:
        query = urllib.parse.quote(safe_query) 
        url = f"https://api.pexels.com/v1/search?query={query}&orientation=portrait&per_page=15"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=(10, 30)).json()
        
        if res.get('photos') and len(res['photos']) > 0:
            photo = random.choice(res['photos'])
            img_url = photo['src']['large2x']
            img_data = requests.get(img_url, timeout=(10, 30)).content
            with open(output_path, 'wb') as f: f.write(img_data)
            apply_cinematic_padding(output_path)
            return True, ""
            
        elif not is_retry:
            print(f"      ⚠️ [Tier 3: Pexels] 0 results for '{safe_query}'. Deploying Universal Fallback...")
            return fallback_pexels_image("cinematic aesthetic background", output_path, is_retry=True)
            
    except Exception as e: 
        return False, "API Error"
        
    return False, "No images found"

def generate_offline_gradient(output_path):
    print(f"      🛡️ [Tier 4: Offline Failsafe] Total API Exhaustion. Generating Mathematical Gradient...")
    try:
        width, height = 1080, 1920
        image = Image.new("RGB", (width, height), "#000000")
        draw = ImageDraw.Draw(image)
        
        r1, g1, b1 = random.randint(10, 50), random.randint(10, 50), random.randint(50, 100)
        r2, g2, b2 = random.randint(0, 20), random.randint(0, 20), random.randint(0, 20)
        
        for y in range(height):
            r = int(r1 + (r2 - r1) * (y / height))
            g = int(g1 + (g2 - g1) * (y / height))
            b = int(b1 + (b2 - b1) * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))
            
        image.save(output_path, "JPEG", quality=90)
        return True, "Python Local Render"
    except:
        return False, "Fatal Local Render Failure"

def fetch_scene_images(prompts_list, pexels_queries, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images via Decoupled 4-Tier System...")
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
                if any(x in err for x in ["401", "402", "403"]):
                    print(f"      🚨 [VISUALS] Tier 1 Fatal Quota/Auth Error ({err}). Disabling for remainder of run.")
                    tier1_active = False 
                else:
                    print(f"      ⚠️ [VISUALS] Tier 1 localized/network failure ({err}). Keeping active for next scene.")
        else:
            print("      [Tier 1: Cloudflare] Skipped (Previously Blocked)")

        if not success and tier2_active:
            success, err = generate_huggingface_cascade(prompt, output_path)
            if success: 
                final_provider = err 
            else:
                if any(x in err for x in ["401", "402", "403"]):
                    print(f"      🚨 [VISUALS] Tier 2 Fatal Quota/Auth Error ({err}). Disabling for remainder of run.")
                    tier2_active = False 
                else:
                    print(f"      ⚠️ [VISUALS] Tier 2 localized/network failure ({err}). Keeping active for next scene.")
        elif not success and not tier2_active:
            print("      [Tier 2: Hugging Face] Skipped (Previously Blocked)")
                
        if not success:
            success, err = fallback_pexels_image(pexels_queries[i], output_path)
            if success: 
                final_provider = "Pexels Stock Fallback"
                
        if not success:
            success, err = generate_offline_gradient(output_path)
            if success:
                final_provider = "Python Offline Generator"
            
        if success:
            successful_images.append(output_path)
            print(f"   ✅ Scene {i+1} saved successfully.")
        else:
            print(f"   ❌ Scene {i+1} failed completely.")
            
        print("   ⏳ Pacing generation engines (Sleeping 3s)...")
        time.sleep(3) 
        
    return successful_images, final_provider
