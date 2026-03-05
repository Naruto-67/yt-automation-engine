import os
import requests
import json
import subprocess
import urllib.parse
from google import genai
from scripts.quota_manager import quota_manager

def load_visual_preferences():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    modifiers = "3D cinematic, high detail, vertical 9:16"
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "preferred_visuals" in data: modifiers = ", ".join(data["preferred_visuals"])
        except: pass
    return modifiers

def animate_image_to_video(image_path, output_filename):
    print(f"🎞️ [VISUALS] Animating image into 60s motion background...")
    try:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-vf", "scale=-2:1920,crop=1080:1920,zoompan=z='min(zoom+0.0008,1.25)':d=1440:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920",
            "-c:v", "libx264", "-t", "60", "-pix_fmt", "yuv420p", "-preset", "ultrafast", output_filename
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

def generate_pollinations_image(prompt, output_path):
    safe_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
    try:
        res = requests.get(url, timeout=30)
        if res.status_code == 200:
            with open(output_path, 'wb') as f: f.write(res.content)
            return True
    except: return False
    return False

def download_pexels_fallback(query, output_filename):
    """Safety Net: Downloads a real video if AI generation fails."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False
    print(f"📽️ [VISUALS] AI generation failed. Sourcing Pexels fallback for: {query}")
    try:
        url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=1"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        video_url = res['videos'][0]['video_files'][0]['link']
        
        vid_data = requests.get(video_url, stream=True)
        with open(output_filename, 'wb') as f:
            for chunk in vid_data.iter_content(chunksize=1024): f.write(chunk)
        return True
    except: return False

def fetch_background(base_query, output_filename="temp_background.mp4"):
    visual_modifiers = load_visual_preferences()
    full_prompt = f"{base_query}, {visual_modifiers}"
    temp_img = "temp_visual.jpg"
    
    # Try AI Generation Primary
    if generate_imagen_image(full_prompt, temp_img):
        if animate_image_to_video(temp_img, output_filename):
            if os.path.exists(temp_img): os.remove(temp_img)
            return True

    # Try AI Generation Secondary
    if generate_pollinations_image(full_prompt, temp_img):
        if animate_image_to_video(temp_img, output_filename):
            if os.path.exists(temp_img): os.remove(temp_img)
            return True

    # Master Fallback: Pexels
    return download_pexels_fallback(base_query, output_filename)
