import os
import requests
import json
import subprocess
import urllib.parse
from google import genai
from scripts.quota_manager import quota_manager

def load_visual_preferences():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    mod = "3D cinematic animation style, 8k, vertical"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if "preferred_visuals" in d: mod = ", ".join(d["preferred_visuals"])
        except: pass
    return mod

def animate_image_to_video(image_path, output_filename):
    print(f"🎞️ [VISUALS] Animating {image_path}...")
    try:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-vf", "scale=-2:1920,crop=1080:1920,zoompan=z='min(zoom+0.0008,1.25)':d=1440:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920",
            "-c:v", "libx264", "-t", "60", "-pix_fmt", "yuv420p", "-preset", "ultrafast", output_filename
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except: return False

def download_pexels_fallback(query, output_filename):
    key = os.environ.get("PEXELS_API_KEY")
    if not key: return False
    print(f"📽️ [VISUALS] Sourcing Pexels fallback for: {query}")
    try:
        url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=1"
        res = requests.get(url, headers={"Authorization": key}, timeout=15).json()
        if not res.get('videos'):
            # Try a broader search if the specific query fails
            url = f"https://api.pexels.com/videos/search?query=cinematic+abstract&orientation=portrait&per_page=1"
            res = requests.get(url, headers={"Authorization": key}, timeout=15).json()
        
        video_url = res['videos'][0]['video_files'][0]['link']
        with open(output_filename, 'wb') as f:
            f.write(requests.get(video_url).content)
        return True
    except: return False

def fetch_background(base_query, output_filename="temp_background.mp4"):
    mod = load_visual_preferences()
    prompt = f"{base_query}, {mod}"
    temp_img = "temp_visual.jpg"
    
    # 1. Try Gemini Imagen
    print(f"🖼️ [VISUALS] Attempting AI Generation...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_image(model='imagen-3', prompt=prompt, config={'aspect_ratio': '9:16'})
            with open(temp_img, 'wb') as f: f.write(response.generated_images[0].image_bytes)
            if animate_image_to_video(temp_img, output_filename):
                if os.path.exists(temp_img): os.remove(temp_img)
                return True
        except: pass

    # 2. Try Pollinations
    try:
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1080&height=1920&nologo=true"
        res = requests.get(url, timeout=20)
        if res.status_code == 200:
            with open(temp_img, 'wb') as f: f.write(res.content)
            if animate_image_to_video(temp_img, output_filename):
                if os.path.exists(temp_img): os.remove(temp_img)
                return True
    except: pass

    # 3. Master Failsafe: Pexels
    return download_pexels_fallback(base_query, output_filename)
