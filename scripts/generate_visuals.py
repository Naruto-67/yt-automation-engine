import os
import requests
import json
import subprocess
import random
import urllib.parse
from google import genai
from scripts.quota_manager import quota_manager

def animate_image_to_video(image_path, output_filename):
    print(f"🎞️ [VISUALS] Animating AI image into cinematic background...")
    try:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-vf", "scale=-2:1920,crop=1080:1920,zoompan=z='min(zoom+0.0005,1.15)':d=1800:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920",
            "-c:v", "libx264", "-t", "60", "-r", "30", "-preset", "ultrafast", output_filename
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except: return False

def generate_imagen_image(prompt, output_path):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return False
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_image(model='imagen-3', prompt=prompt, config={'aspect_ratio': '9:16'})
        with open(output_path, 'wb') as f:
            f.write(response.generated_images[0].image_bytes)
        return True
    except: return False

def generate_hercai_image(prompt, output_path):
    """Secondary Failsafe: Hercai free API (bypasses Pollinations IP block)"""
    safe_prompt = urllib.parse.quote(prompt)
    url = f"https://hercai.onrender.com/v3/text2image?prompt={safe_prompt}"
    try:
        res = requests.get(url, timeout=30).json()
        if "url" in res:
            img_data = requests.get(res["url"], timeout=30).content
            with open(output_path, 'wb') as f:
                f.write(img_data)
            return True
    except: return False
    return False

def download_pexels_fallback(query, output_filename):
    """Ultimate Failsafe: Pexels Video (Now works perfectly with 2-step Render)"""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False
    print(f"📽️ [VISUALS] AI Blocked. Sourcing Pexels fallback video for: {query}")
    try:
        url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=1"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        if not res.get('videos'):
            url = f"https://api.pexels.com/videos/search?query=cinematic+abstract&orientation=portrait&per_page=1"
            res = requests.get(url, headers=headers, timeout=15).json()
            
        video_url = res['videos'][0]['video_files'][0]['link']
        vid_data = requests.get(video_url, stream=True)
        with open(output_filename, 'wb') as f:
            for chunk in vid_data.iter_content(chunksize=1024): f.write(chunk)
        return True
    except: return False

def fetch_background(base_query, output_filename="temp_background.mp4"):
    full_prompt = f"{base_query}, ultra realistic, 8k, cinematic lighting, vertical portrait"
    temp_img = "temp_visual.jpg"
    
    print(f"🖼️ [VISUALS] Attempting AI Image Generation (Primary: Gemini)...")
    if generate_imagen_image(full_prompt, temp_img):
        if animate_image_to_video(temp_img, output_filename):
            if os.path.exists(temp_img): os.remove(temp_img)
            return True

    print(f"🖼️ [VISUALS] Gemini failed. Attempting AI Secondary (Hercai)...")
    if generate_hercai_image(full_prompt, temp_img):
        if animate_image_to_video(temp_img, output_filename):
            if os.path.exists(temp_img): os.remove(temp_img)
            return True

    # Pexels Video Failsafe
    return download_pexels_fallback(base_query, output_filename)
