import os
import requests
import random
import json
import subprocess
import traceback
import urllib.parse

def load_visual_preferences():
    """Reads historical data to append proven visual modifiers to the search query."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    modifiers = "3D animation style, Unreal Engine 5 render, cinematic lighting, 8k resolution, highly detailed"
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "preferred_visuals" in data:
                    modifiers = ", ".join(data["preferred_visuals"])
        except Exception as e:
            print(f"⚠️ Warning: Could not read lessons_learned.json: {e}")
            
    return modifiers

def get_fallback_video(output_filename):
    """The ultimate failsafe. If APIs go down, pull from the local vault."""
    print("⚠️  Initiating Local Fallback Protocol...")
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    fallback_dir = os.path.join(root_dir, "assets", "fallbacks")
    
    if not os.path.exists(fallback_dir):
        print(f"❌ Critical Error: Fallback directory missing at {fallback_dir}")
        return False
        
    available_videos = [f for f in os.listdir(fallback_dir) if f.endswith(".mp4")]
    if not available_videos:
        print("❌ Critical Error: No .mp4 files found in the fallback directory.")
        return False
        
    chosen_fallback = random.choice(available_videos)
    source_path = os.path.join(fallback_dir, chosen_fallback)
    
    try:
        with open(source_path, 'rb') as src, open(output_filename, 'wb') as dst:
            dst.write(src.read())
        print(f"✅ Fallback successful. Using local asset: {chosen_fallback}")
        return True
    except Exception as e:
        print(f"❌ Failed to copy fallback video: {e}")
        return False

def fetch_pexels_video(query, output_filename):
    """The secondary failsafe. Uses Pexels if AI Image Generation fails."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("⚠️ PEXELS_API_KEY missing. Skipping to local fallback.")
        return get_fallback_video(output_filename)

    print(f"🔍 [PEXELS] Searching stock video for: '{query}'...")
    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&size=large&per_page=15"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return get_fallback_video(output_filename)

        data = response.json()
        if not data.get("videos"):
            return get_fallback_video(output_filename)

        video = random.choice(data["videos"])
        video_files = video.get("video_files", [])
        
        valid_files = [f for f in video_files if f.get("width", 0) < 2160]
        if not valid_files: valid_files = video_files
        if not valid_files: return get_fallback_video(output_filename)
        
        valid_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
        download_link = valid_files[0].get("link")
        
        vid_response = requests.get(download_link, stream=True, timeout=30)
        with open(output_filename, 'wb') as f:
            for chunk in vid_response.iter_content(chunk_size=8192):
                if chunk: f.write(chunk)
                
        print(f"✅ [PEXELS] Stock video securely saved to {output_filename}")
        return True
    except Exception as e:
        print(f"⚠️ [PEXELS] Fetch failed: {e}")
        return get_fallback_video(output_filename)

def animate_image_to_video(image_path, output_filename):
    """
    Takes a static AI image and uses FFmpeg to apply a 60-second slow, 
    cinematic 'Ken Burns' zoom. Returns a looping video.
    """
    print("🎬 [FFMPEG] Animating static AI image into cinematic video...")
    try:
        # 1800 frames = 60 seconds at 30fps. The zoompan filter slowly zooms in by 15%.
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", "scale=-2:10*1920,zoompan=z='min(zoom+0.0003,1.15)':d=1800:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920",
            "-c:v", "libx264",
            "-t", "60",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            output_filename
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print(f"✅ [FFMPEG] Image animated and saved to {output_filename}")
        return True
    except Exception as e:
        print(f"❌ [FFMPEG] Animation failed: {e}")
        return False

def generate_pollinations_image(prompt, output_image_path):
    """Generates a free, unlimited, high-quality AI image."""
    print(f"🎨 [POLLINATIONS] Generating AI 3D Image: '{prompt[:50]}...'")
    
    # URL encode the prompt and specify vertical dimensions (1080x1920)
    safe_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 100000)
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&seed={seed}&nologo=true"
    
    try:
        response = requests.get(url, timeout=45)
        if response.status_code == 200:
            with open(output_image_path, 'wb') as f:
                f.write(response.content)
            print("✅ [POLLINATIONS] AI Image generated successfully.")
            return True
        else:
            print(f"⚠️ [POLLINATIONS] Server returned {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ [POLLINATIONS] Generation failed: {e}")
        return False

def fetch_background(base_query, output_filename="master_background.mp4"):
    """
    The Master Visual Router.
    Attempts AI Image Gen -> Ken Burns Video -> Pexels Stock -> Local Vault.
    """
    visual_modifiers = load_visual_preferences()
    full_prompt = f"{base_query}, {visual_modifiers}"
    temp_image_path = "temp_ai_background.jpg"
    
    # Step 1: Generate AI Image
    if generate_pollinations_image(full_prompt, temp_image_path):
        
        # Step 2: Animate it into a video
        if animate_image_to_video(temp_image_path, output_filename):
            # Clean up the temp image
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
            return True
            
        # If animation fails, clean up and fall through to Pexels
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
            
    # Step 3: Fallback to Pexels Stock Video
    print("🔄 [VISUAL ROUTER] AI Generation failed. Falling back to Stock Video...")
    return fetch_pexels_video(base_query, output_filename)

if __name__ == "__main__":
    # Local Testing
    fetch_background("abandoned hospital with glowing ghosts", "test_background.mp4")
