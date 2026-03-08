import os
import requests
import urllib.parse
import time
import random
import base64
import re
from PIL import Image, ImageDraw
from scripts.quota_manager import quota_manager

SIMULATE_CASCADE_TEST = False

def _regenerate_safe_prompt(bad_prompt):
    """🚨 V5 FEATURE: Self-Healing Prompt Protocol. If an image API rejects a prompt, the LLM rewrites it."""
    prompt = f"""
    The following image generation prompt was rejected by an AI safety filter (likely due to violence, gore, NSFW, or restricted terms):
    "{bad_prompt}"
    
    Rewrite this prompt so it conveys a similar visual concept but is 100% safe, family-friendly, and complies with strict AI content filters. Make it highly cinematic.
    Return ONLY the new prompt string, nothing else. No intro or markdown.
    """
    clean_text, _ = quota_manager.generate_text(prompt, task_type="creative")
    if clean_text:
        return clean_text.strip().replace('"', '').replace('\n', ' ')
    return "Cinematic 3D animation of a mysterious glowing artifact in space, highly detailed"

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

    for retry in range(2):
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
            elif response.status_code >= 500 and retry == 0:
                print(f"      💤 Cloudflare Transient Error ({response.status_code}). Waiting 5s and retrying...")
                time.sleep(5)
                continue
            elif response.status_code == 400:
                return False, "HTTP 400 (Safety Filter / Prompt Rejected)"
            else:
                return False, f"HTTP {response.status_code}"
        except Exception as e:
            if retry == 0:
                print(f"      💤 Cloudflare connection timeout. Retrying once...")
                time.sleep(5)
                continue
            return False, "Timeout/Connection Error"

    return False, "Exhausted Retries"

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
                return False, "HTTP 400 (Safety Filter / Prompt Rejected)"
            elif response.status_code in [401, 402, 403]:
                print(f"      ⚠️ {short_name} out of free quota or unauthorized. Switching models...")
                continue
            elif response.status_code >= 500:
                wait_time = 15
                try:
                    err_json = response.json()
                    if "estimated_time" in err_json:
                        wait_time = min(int(err_json["estimated_time"]) + 2, 60)
                except: pass

                print(f"      💤 {short_name} loading into VRAM. Sleeping adaptively for {wait_time}s...")
                time.sleep(wait_time)

                response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
                if response.status_code == 200:
                    with open(output_path, 'wb') as f: f.write(response.content)
                    quota_manager.consume_points("huggingface", 1)
                    return True, f"HF ({short_name})"
        except: pass

    return False, "HF Models Exhausted/Blocked"

def fallback_pexels_image(search_query, output_path, is_retry=False):
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', search_query).strip()
    words = [w for w in clean_query.split() if len(w) >= 2]
    safe_query = " ".join(words[:3]) if words else "cinematic background"

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

    offline_gradient_used = False
    tier1_disabled_notified = False
    tier2_disabled_notified = False
    
    # 🚨 SOLVED: Explicit integer limit on prompt regeneration to mathematically prevent infinite loops
    MAX_SAFETY_RETRIES = 1

    for i, original_prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {original_prompt[:40]}...")

        success = False
        current_prompt = original_prompt
        safety_retries = 0

        # Self-Healing Loop: Try API -> If 400 Error -> Sanitize Prompt -> Try Again (Up to MAX_SAFETY_RETRIES)
        while True:
            if tier1_active:
                success, err = generate_cloudflare_image(current_prompt, output_path)
                if success:
                    final_provider = "Cloudflare FLUX API"
                    break
                else:
                    if "400" in err and safety_retries < MAX_SAFETY_RETRIES:
                        print(f"      ⚠️ [VISUALS] Tier 1 Safety Filter triggered. Asking AI to sanitize prompt ({safety_retries + 1}/{MAX_SAFETY_RETRIES})...")
                        current_prompt = _regenerate_safe_prompt(current_prompt)
                        safety
