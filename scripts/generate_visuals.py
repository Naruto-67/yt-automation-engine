import os
import requests
import random
import json
import subprocess
import urllib.parse
from google import genai

# Import the Master Quota Manager and AI Doctor
from scripts.retry import quota_manager

def load_visual_preferences():
    """Reads historical data to append proven visual modifiers (e.g., 3D Pixar Style)."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    # Default High-Retention Style
    modifiers = "3D Pixar animation style, Unreal Engine 5 render, cinematic lighting, vibrant colors, 8k resolution, highly detailed"
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "preferred_visuals" in data:
                    modifiers = ", ".join(data["preferred_visuals"])
        except Exception: pass
            
    return modifiers

# ==========================================
# 🎬 THE ANIMATOR (Ken Burns Effect)
# ==========================================
def animate_image_to_video(image_path, output_filename):
    """
    Takes a static AI image and uses FFmpeg to apply a cinematic zoom.
    Optimized for RAM-Safe processing on GitHub Actions.
    """
    print("🎬 [VISUALS] Animating static AI image (Ken Burns Zoom)...")
    try:
        # 1800 frames = 60 seconds at 30fps. 
        # zoompan: z=zoom, d=duration, s=size
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", "scale=-2:10*1920,zoompan=z='min(zoom+0.0005,1.25)':d=1800:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920",
            "-c:v", "libx264",
            "-t", "60",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            output_filename
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        print(f"❌ [VISUALS] Animation failed: {e}")
        return False

# ==========================================
# 🖼️ GENERATION ENGINES (The Waterfall)
# ==========================================
def generate_imagen_image(prompt, output_path):
    """Primary: Gemini Imagen (Highest Quality)."""
    print("🧠 [VISUALS] Tasking Gemini Imagen Engine...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return False

    try:
        client = genai.Client(api_key=api_key)
        # Imagen 3/4 is the current 2026 standard for high-fidelity 3D
        response = client.models.generate_image(
            model='imagen-3', 
            prompt=prompt,
            config={'aspect_ratio': '9:16'}
        )
        
        # Save the first generated image bytes
        with open(output_path, 'wb') as f:
            f.write(response.generated_images[0].image_bytes)
            
        print("✅ [VISUALS] Imagen generation successful.")
        return True
    except Exception as e:
        print(f"⚠️ [VISUALS] Imagen failed or quota hit: {e}")
        return False

def generate_pollinations_image(prompt, output_path):
    """Secondary: Pollinations.ai (Free/Unlimited Fallback)."""
    print("🎨 [VISUALS] Triggering Pollinations.ai Fallback...")
    safe_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 999999)
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&seed={seed}&nologo=true"
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
    except Exception: pass
    return False

def fetch_pexels_video(query, output_filename):
    """Tertiary: Pexels Stock Video (Final API Fallback)."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key: return False

    print(f"🔍 [VISUALS] Searching Pexels for: '{query}'...")
    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=1"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        if data.get("videos"):
            video_url = data["videos"][0]["video_files"][0]["link"]
            vid_res = requests.get(video_url, stream=True)
            with open(output_filename, 'wb') as f:
                for chunk in vid_res.iter_content(chunk_size=8192):
                    if chunk: f.write(chunk)
            return True
    except Exception: pass
    return False

# ==========================================
# 🧠 MASTER VISUAL ROUTER
# ==========================================
def fetch_background(base_query, output_filename="master_background.mp4"):
    """
    The Visual Orchestrator.
    Imagen 4.0 -> Pollinations -> Pexels -> Local Fallback.
    """
    visual_modifiers = load_visual_preferences()
    full_prompt = f"{base_query}, {visual_modifiers}"
    temp_img = "temp_visual.jpg"
    
    # 1. Try Imagen
    if generate_imagen_image(full_prompt, temp_img):
        if animate_image_to_video(temp_img, output_filename):
            if os.path.exists(temp_img): os.remove(temp_img)
            return True

    # 2. Try Pollinations
    if generate_pollinations_image(full_prompt, temp_img):
        if animate_image_to_video(temp_img, output_filename):
            if os.path.exists(temp_img): os.remove(temp_img)
            return True

    # 3. Try Pexels
    if fetch_pexels_video(base_query, output_filename):
        return True

    # 4. Final Failsafe: Local Assets
    print("🚨 [VISUALS] All APIs failed. Pulling from Local Vault...")
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    fallback_dir = os.path.join(root_dir, "assets", "fallbacks")
    
    if os.path.exists(fallback_dir):
        files = [f for f in os.listdir(fallback_dir) if f.endswith(".mp4")]
        if files:
            source = os.path.join(fallback_dir, random.choice(files))
            subprocess.run(["cp", source, output_filename])
            return True

    return False

if __name__ == "__main__":
    fetch_background("abandoned space station with floating crystals")
