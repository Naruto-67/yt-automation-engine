# scripts/generate_visuals.py — Ghost Engine V8.1
import os
import requests
import urllib.parse
import time
import random
import base64
import re
import yaml
import traceback
from PIL import Image, ImageDraw
from scripts.quota_manager import quota_manager
from engine.guardian import guardian

SIMULATE_CASCADE_TEST = False
_HF_MODELS_CACHE = []

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def _regenerate_safe_prompt(bad_prompt):
    prompts_cfg = load_config_prompts()
    sys_msg = prompts_cfg['visual_safety']['system_prompt']
    user_msg = prompts_cfg['visual_safety']['user_template'].format(bad_prompt=bad_prompt)
    try:
        clean_text, _ = quota_manager.generate_text(user_msg, task_type="creative", system_prompt=sys_msg)
        if clean_text: return clean_text.strip().replace('"', '').replace('\n', ' ')
    except: pass
    return "Cinematic 3D animation of a mysterious artifact, highly detailed"

def discover_hf_image_models():
    global _HF_MODELS_CACHE
    if _HF_MODELS_CACHE:
        return _HF_MODELS_CACHE

    print("🔍 [HF] Auto-discovering trending text-to-image models...")
    try:
        url = "https://huggingface.co/api/models?pipeline_tag=text-to-image&sort=trending&limit=20"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            models_data = res.json()
            candidates = [m['id'] for m in models_data]
            
            def _score_hf(name):
                s = 0
                n = name.lower()
                if 'flux' in n: s += 50
                if 'schnell' in n: s += 30
                if 'stable-diffusion' in n: s += 20
                if 'turbo' in n or 'lightning' in n: s += 15
                if 'lora' in n or 'controlnet' in n or 'adapter' in n or 'ip-adapter' in n: s -= 100
                return s
            
            valid_models = [m for m in candidates if _score_hf(m) > 0]
            valid_models.sort(key=_score_hf, reverse=True)
            
            if valid_models:
                _HF_MODELS_CACHE = valid_models[:4] 
                print(f"✅ [HF] Model cascade dynamically updated: {_HF_MODELS_CACHE}")
                return _HF_MODELS_CACHE
    except Exception as e:
        print(f"⚠️ [HF] Discovery failed: {e}")

    _HF_MODELS_CACHE = ["black-forest-labs/FLUX.1-schnell", "stabilityai/stable-diffusion-xl-base-1.0"]
    return _HF_MODELS_CACHE

def generate_cloudflare_image(prompt, output_path):
    print("      [Tier 1: Cloudflare AI] Attempting Official FLUX...")
    if SIMULATE_CASCADE_TEST or quota_manager.is_provider_exhausted("cloudflare"): return False, "Quota Reached"

    account_id, api_token = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not account_id or not api_token: return False, "Missing CF Credentials"

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    payload = {"prompt": f"{prompt[:200].replace('\"', '').replace(chr(10), ' ')}, vertical 9:16 format, masterpiece"}

    for retry in range(2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
            if response.status_code == 200:
                data = response.json() if "application/json" in response.headers.get("Content-Type", "") else None
                if data and "result" in data and "image" in data["result"]:
                    with open(output_path, 'wb') as f: f.write(base64.b64decode(data["result"]["image"]))
                else:
                    with open(output_path, 'wb') as f: f.write(response.content)
                quota_manager.consume_points("cloudflare", 1)
                return True, ""
            elif response.status_code >= 500 and retry == 0:
                time.sleep(5)
                continue
            elif response.status_code == 400: return False, "HTTP 400 (Safety Filter)"
            else: return False, f"HTTP {response.status_code}"
        except Exception as e:
            # FULL TRANSPARENCY FIX
            trace = traceback.format_exc()
            print(f"🚨 [CF AI ERROR] {type(e).__name__}: {e}\n{trace}")
            if retry == 0: time.sleep(5); continue
            return False, "Timeout Error"
    return False, "Exhausted Retries"

def generate_huggingface_cascade(prompt, output_path):
    print("      [Tier 2: HuggingFace] Attempting AI cascade...")
    if quota_manager.is_provider_exhausted("huggingface"): return False, "HF Quota Reached"
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token: return False, "No Token"

    dynamic_models = discover_hf_image_models()
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    payload = {"inputs": f"{prompt[:200].replace('\"', '').replace(chr(10), ' ')}, vertical 9:16 format"}

    for model in dynamic_models:
        short_name = model.split('/')[-1]
        print(f"      -> Routing to {short_name}...")
        if SIMULATE_CASCADE_TEST and "FLUX" in model: continue
        
        url = f"https://api-inference.huggingface.co/models/{model}"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
            if response.status_code == 200:
                with open(output_path, 'wb') as f: f.write(response.content)
                quota_manager.consume_points("huggingface", 1)
                return True, f"HF ({short_name})"
            elif response.status_code in [401, 402, 403, 404]: 
                continue
            elif response.status_code >= 500:
                wait_time = 15
                try:
                    data = response.json()
                    wait_time = min(int(data.get("estimated_time", 13)) + 2, 60)
                except Exception:
                    pass
                    
                time.sleep(wait_time)
                response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
                if response.status_code == 200:
                    with open(output_path, 'wb') as f: f.write(response.content)
                    quota_manager.consume_points("huggingface", 1)
                    return True, f"HF ({short_name})"
        except Exception as e:
            # FULL TRANSPARENCY FIX
            trace = traceback.format_exc()
            print(f"🚨 [HF AI ERROR] {type(e).__name__}: {e}\n{trace}")
            pass
    return False, "HF Exhausted"

def fallback_pexels_image(search_query, output_path, is_retry=False):
    safe_query = " ".join([w for w in re.sub(r'[^a-zA-Z0-9\s]', '', search_query).split() if len(w) >= 2][:3]) or "cinematic"
    print(f"      [Tier 3: Pexels] Searching: '{safe_query}'...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False, "No Key"

    try:
        url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(safe_query)}&orientation=portrait&per_page=15"
        res = requests.get(url, headers={"Authorization": api_key}, timeout=(10, 30)).json()
        if res.get('photos'):
            img_data = requests.get(random.choice(res['photos'])['src']['large2x'], timeout=(10, 30)).content
            with open(output_path, 'wb') as f: f.write(img_data)
            return True, ""
        elif not is_retry:
            return fallback_pexels_image("cinematic aesthetic", output_path, is_retry=True)
    except Exception as e:
        # FULL TRANSPARENCY FIX
        trace = traceback.format_exc()
        print(f"🚨 [PEXELS ERROR] {type(e).__name__}: {e}\n{trace}")
        return False, "API Error"
    return False, "No images found"

def generate_offline_gradient(output_path):
    print(f"      🛡️ [Tier 4] Local Gradient Render...")
    try:
        image = Image.new("RGB", (1080, 1920), "#000000")
        draw = ImageDraw.Draw(image)
        r1, g1, b1 = random.randint(10, 50), random.randint(10, 50), random.randint(50, 100)
        r2, g2, b2 = random.randint(0, 20), random.randint(0, 20), random.randint(0, 20)
        for y in range(1920):
            draw.line([(0, y), (1080, y)], fill=(int(r1+(r2-r1)*(y/1920)), int(g1+(g2-g1)*(y/1920)), int(b1+(b2-b1)*(y/1920))))
        image.save(output_path, "JPEG", quality=90)
        return True, "Local Render"
    except Exception as e:
        # FULL TRANSPARENCY FIX
        trace = traceback.format_exc()
        print(f"🚨 [LOCAL RENDER ERROR] {type(e).__name__}: {e}\n{trace}")
        return False, "Fatal Render"

def fetch_scene_images(prompts_list, pexels_queries, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scenes...")
    successful_images = []
    
    safe_mode = guardian.is_safe_mode()
    tier1_active = not safe_mode
    tier2_active = not safe_mode
    if safe_mode: print("🛡️ [SAFE MODE] API Quota critically low for this channel. Bypassing AI generation.")

    final_provider = "Unknown"
    for i, original_prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        success, current_prompt, safety_retries = False, original_prompt, 0

        while True:
            if tier1_active:
                success, err = generate_cloudflare_image(current_prompt, output_path)
                if success:
                    final_provider = "Cloudflare FLUX API"
                    break
                elif "400" in err and safety_retries < 1:
                    current_prompt = _regenerate_safe_prompt(current_prompt)
                    safety_retries += 1
                    continue
                elif any(x in err for x in ["401", "402", "403"]): tier1_active = False

            if not success and tier2_active:
                success, err = generate_huggingface_cascade(current_prompt, output_path)
                if success:
                    final_provider = err
                    break
                elif "400" in err and safety_retries < 1:
                    current_prompt = _regenerate_safe_prompt(current_prompt)
                    safety_retries += 1
                    continue
                elif any(x in err for x in ["401", "402", "403"]): tier2_active = False
            break

        if not success:
            success, err = fallback_pexels_image(pexels_queries[i], output_path)
            if success: final_provider = "Pexels Stock"

        if not success:
            success, err = generate_offline_gradient(output_path)
            if success: final_provider = "Offline Generator"

        if success: successful_images.append(output_path)
        time.sleep(2)

    return successful_images, final_provider
