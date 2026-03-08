# scripts/generate_visuals.py (Safe Mode Snippet Update)
import os
import requests
import urllib.parse
import time
import random
import base64
import re
import yaml
from PIL import Image, ImageDraw
from scripts.quota_manager import quota_manager
from engine.guardian import guardian # Added import

SIMULATE_CASCADE_TEST = False

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

# ... [generate_cloudflare_image, generate_huggingface_cascade, fallback_pexels_image, generate_offline_gradient remain identical to previous implementation] ...

def fetch_scene_images(prompts_list, pexels_queries, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scenes...")
    successful_images = []
    
    # 🚨 V5 PER-CHANNEL SAFE MODE
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
