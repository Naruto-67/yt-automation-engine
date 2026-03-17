# scripts/generate_visuals.py
# Ghost Engine V26.0.0 — 4-Tier Visual Cascade & Integrity Validation
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

# ── Minimum acceptable image file size ────────────────────────────────────────
# Threshold to catch HTML error pages or tiny loading placeholders
_MIN_IMAGE_BYTES = 10_000   # 10 KB 

def _validate_image(path: str) -> bool:
    """
    Returns True only if the file is a valid, fully-decodable image.
    Rejects HTML error pages and truncated JPEGs before they reach FFmpeg.
    """
    try:
        if not os.path.exists(path):
            return False [cite: 279]
        if os.path.getsize(path) < _MIN_IMAGE_BYTES:
            print(f"      ⚠️ [VALIDATE] Image too small ({os.path.getsize(path)} bytes). Rejecting.")
            return False
        # PIL.verify() checks header/trailer for corruption [cite: 280]
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            w, h = img.size
            if w < 64 or h < 64: [cite: 281]
                print(f"      ⚠️ [VALIDATE] Dimensions too small ({w}x{h}). Rejecting.")
                return False
        return True
    except Exception as e:
        print(f"      ⚠️ [VALIDATE] Image failed decode check: {e}. Rejecting.")
        return False

# Pushes output quality toward the photorealistic V26 aesthetic 
_QUALITY_SUFFIX = (
    ", vertical 9:16 format, photorealistic, highly detailed, "
    "vibrant cinematic lighting, vivid colors, 8k quality, masterpiece"
)
_PROMPT_MAX_BASE = 180

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _execute_jitter_backoff(attempt: int, api_name: str):
    """Tiered delay brackets to handle API rate limits [cite: 283]"""
    if attempt == 0:
        wait_time = random.uniform(5.0, 10.0)
    elif attempt == 1:
        wait_time = random.uniform(20.0, 40.0)
    else:
        wait_time = random.uniform(40.0, 60.0)
    print(f"      ⏳ [{api_name} RPM] Backoff: cooling down for {wait_time:.1f}s...")
    time.sleep(wait_time)

def _regenerate_safe_prompt(bad_prompt):
    """Uses LLM to rewrite prompts rejected by safety filters [cite: 284]"""
    prompts_cfg = load_config_prompts()
    sys_msg = prompts_cfg.get("visual_safety", {}).get("system_prompt", "AI Safety Filter")
    template = prompts_cfg.get("visual_safety", {}).get("user_template", "{bad_prompt}")
    user_msg = template.format(bad_prompt=bad_prompt)
    try:
        clean_text, _ = quota_manager.generate_text(user_msg, task_type="creative", system_prompt=sys_msg)
        if clean_text:
            return clean_text.strip().replace('"', '').replace('\n', ' ')
    except Exception:
        pass
    return "Cinematic 3D animation of a mysterious artifact, highly detailed"

def discover_hf_image_models():
    """Auto-discovers trending text-to-image models on HuggingFace [cite: 285-290]"""
    global _HF_MODELS_CACHE
    if _HF_MODELS_CACHE: return _HF_MODELS_CACHE
    try:
        url = "https://huggingface.co/api/models?pipeline_tag=text-to-image&sort=trending&limit=20"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            candidates = [m['id'] for m in res.json()]
            valid_models = [m for m in candidates if any(x in m.lower() for x in ['flux', 'sdxl', 'diffusion'])]
            if valid_models:
                _HF_MODELS_CACHE = valid_models[:4]
                return _HF_MODELS_CACHE
    except Exception:
        pass
    return ["black-forest-labs/FLUX.1-schnell", "stabilityai/stable-diffusion-xl-base-1.0"]

def generate_cloudflare_image(prompt, output_path):
    """Tier 1: High-speed FLUX generation [cite: 291-297]"""
    if quota_manager.is_provider_exhausted("cloudflare"): return False, "Quota"
    account_id, api_token = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not account_id or not api_token: return False, "Credentials"

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    clean_base = prompt[:_PROMPT_MAX_BASE].replace('"', '').replace('\n', ' ')
    payload = {"prompt": f"{clean_base}{_QUALITY_SUFFIX}"}

    for retry in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                if _validate_image(output_path):
                    quota_manager.consume_points("cloudflare", 1)
                    return True, ""
            _execute_jitter_backoff(retry, "CF AI")
        except Exception:
            _execute_jitter_backoff(retry, "CF AI")
    return False, "Failed"

def generate_huggingface_cascade(prompt, output_path):
    """Tier 2: Multi-model AI failover [cite: 298-308]"""
    if quota_manager.is_provider_exhausted("huggingface"): return False, "Quota"
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token: return False, "No Token"

    dynamic_models = discover_hf_image_models()
    headers = {"Authorization": f"Bearer {hf_token}"}
    payload = {"inputs": f"{prompt[:_PROMPT_MAX_BASE]}{_QUALITY_SUFFIX}"}

    for model in dynamic_models:
        url = f"https://api-inference.huggingface.co/models/{model}"
        for retry in range(2):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=60)
                if res.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(res.content)
                    if _validate_image(output_path):
                        quota_manager.consume_points("huggingface", 1)
                        return True, model
                elif res.status_code == 503: # Model Loading [cite: 305]
                    time.sleep(15)
                    continue
                break
            except Exception:
                break
    return False, "Exhausted"

def fallback_pexels_image(search_query, output_path):
    """Tier 3: Stock imagery fallback [cite: 309-312]"""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False, "No Key"
    safe_query = urllib.parse.quote(search_query[:50])
    url = f"https://api.pexels.com/v1/search?query={safe_query}&orientation=portrait&per_page=1"
    try:
        res = requests.get(url, headers={"Authorization": api_key}, timeout=20).json()
        if res.get('photos'):
            img_url = res['photos'][0]['src']['large2x']
            data = requests.get(img_url, timeout=20).content
            with open(output_path, 'wb') as f:
                f.write(data)
            return _validate_image(output_path), "Pexels"
    except Exception:
        pass
    return False, "Failed"

def generate_offline_gradient(output_path):
    """Tier 4: Emergency local render to prevent black frames [cite: 313-315]"""
    try:
        image = Image.new("RGB", (1080, 1920), "#000000")
        draw = ImageDraw.Draw(image)
        r1, g1, b1 = random.randint(10, 50), random.randint(10, 50), random.randint(50, 100)
        r2, g2, b2 = random.randint(0, 20), random.randint(0, 20), random.randint(0, 20)
        for y in range(1920):
            draw.line([(0, y), (1080, y)], fill=(
                int(r1 + (r2 - r1) * (y / 1920)),
                int(g1 + (g2 - g1) * (y / 1920)),
                int(b1 + (b2 - b1) * (y / 1920))
            ))
        image.save(output_path, "JPEG", quality=90)
        return True, "Local Render"
    except Exception:
        return False, "Fatal"

def fetch_scene_images(prompts_list, pexels_queries, base_filename="temp_scene"):
    """Main Orchestrator for visual sourcing [cite: 316-324]"""
    successful_images = []
    safe_mode = guardian.is_safe_mode() [cite: 316]
    
    for i, original_prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        success = False
        
        if not safe_mode: [cite: 317-322]
            # Try AI Tiers
            success, _ = generate_cloudflare_image(original_prompt, output_path)
            if not success:
                success, _ = generate_huggingface_cascade(original_prompt, output_path)
        
        if not success:
            # Fallback to Stock [cite: 323]
            query = pexels_queries[i] if i < len(pexels_queries) else original_prompt
            success, _ = fallback_pexels_image(query, output_path)
            
        if not success:
            # Emergency Local Render
            success, _ = generate_offline_gradient(output_path)
            
        if success:
            successful_images.append(output_path) [cite: 324]
        time.sleep(1)

    return successful_images, "Hybrid Cascade"
