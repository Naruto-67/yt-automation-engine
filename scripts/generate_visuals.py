# ================================================
# FILE: scripts/generate_visuals.py
# ================================================
import os
import requests
import urllib.parse
import time
from scripts.quota_manager import quota_manager

def generate_pollinations_image(prompt, output_path):
    """
    Primary Free Engine: Pollinations.ai. 
    No auth, no quota, highly reliable for 1080x1920 images.
    """
    # Enhancing prompt for Shorts aesthetics
    enhanced_prompt = f"{prompt}, ultra realistic, 8k, highly detailed, cinematic lighting, dramatic, vertical 9:16 aspect ratio"
    safe_prompt = urllib.parse.quote(enhanced_prompt)
    
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except:
        return False

def generate_hercai_image(prompt, output_path):
    """Secondary Free Engine: Hercai v3."""
    enhanced_prompt = f"{prompt}, cinematic vertical 9:16"
    safe_prompt = urllib.parse.quote(enhanced_prompt)
    url = f"https://hercai.onrender.com/v3/text2image?prompt={safe_prompt}"
    try:
        res = requests.get(url, timeout=30).json()
        if "url" in res:
            img_data = requests.get(res["url"], timeout=30).content
            with open(output_path, 'wb') as f:
                f.write(img_data)
            return True
    except:
        return False
    return False

def fetch_scene_images(prompts_list, base_filename="temp_scene"):
    """
    Takes a list of prompts and downloads an image for each.
    Returns a list of successful image file paths.
    """
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} AI scene images...")
    successful_images = []
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"   -> Scene {i+1}: Attempting Pollinations API...")
        
        # 1. Try Pollinations
        success = generate_pollinations_image(prompt, output_path)
        
        # 2. Fallback to Hercai if Pollinations fails
        if not success:
            print(f"   -> Scene {i+1}: Pollinations failed. Fallback to Hercai...")
            success = generate_hercai_image(prompt, output_path)
            
        if success:
            successful_images.append(output_path)
        else:
            print(f"   ❌ Scene {i+1} completely failed. Skipping this frame.")
            
        time.sleep(1) # Gentle pacing
        
    return successful_images
