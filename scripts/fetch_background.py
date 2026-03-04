import os
import requests
import random
import json

def load_visual_preferences():
    """
    Reads historical data to append proven visual modifiers to the search query.
    If the USA audience prefers 'cinematic' or 'dark' styles, the machine adapts.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    modifiers = ""
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # If analytics show certain visual styles retain better, append them
                if "preferred_visuals" in data:
                    modifiers = " " + " ".join(data["preferred_visuals"])
        except Exception as e:
            print(f"Warning: Could not read lessons_learned.json: {e}")
            
    return modifiers

def get_fallback_video(output_filename):
    """
    The ultimate failsafe. If APIs go down, pull from the local vault.
    """
    print("⚠️  Initiating Fallback Protocol...")
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
        # Copy the fallback file to the working directory, renaming it to the expected output
        with open(source_path, 'rb') as src, open(output_filename, 'wb') as dst:
            dst.write(src.read())
        print(f"✅ Fallback successful. Using local asset: {chosen_fallback}")
        return True
    except Exception as e:
        print(f"❌ Failed to copy fallback video: {e}")
        return False

def fetch_background(base_query, output_filename="master_background.mp4"):
    """
    Searches Pexels for a 1080p vertical video matching the dynamic query.
    If it fails, it instantly triggers the fallback protocol.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("Warning: PEXELS_API_KEY is missing. Defaulting to local fallbacks.")
        return get_fallback_video(output_filename)

    # Inject learned visual preferences into the query
    visual_modifiers = load_visual_preferences()
    optimized_query = f"{base_query}{visual_modifiers}".strip()
    
    print(f"🔍 Searching Pexels for optimized query: '{optimized_query}'...")
    
    headers = {"Authorization": api_key}
    # Enforcing portrait (9:16) and large (1080p/4K) for YouTube Shorts
    url = f"https://api.pexels.com/videos/search?query={optimized_query}&orientation=portrait&size=large&per_page=15"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        if not data.get("videos"):
            print(f"⚠️ No Pexels results for '{optimized_query}'.")
            return get_fallback_video(output_filename)

        # Pick a random video from the top 15 to prevent visual repetition
        video = random.choice(data["videos"])
        
        video_files = video.get("video_files", [])
        if not video_files:
            print("⚠️ Selected Pexels video has no downloadable files.")
            return get_fallback_video(output_filename)
            
        # Sort by resolution (width * height) to guarantee the crispest file
        video_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
        target_file = video_files[0]
        download_link = target_file.get("link")
        
        print(f"⬇️ Downloading high-quality asset ({target_file.get('width')}x{target_file.get('height')})...")
        vid_response = requests.get(download_link, stream=True, timeout=30)
        vid_response.raise_for_status()
        
        with open(output_filename, 'wb') as f:
            for chunk in vid_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                
        print(f"✅ Background video successfully saved to {output_filename}")
        return True

    except Exception as e:
        print(f"⚠️ API or Network failure during fetch: {e}")
        return get_fallback_video(output_filename)

if __name__ == "__main__":
    # Test the fetcher (will use Pexels if API key exists, otherwise local fallback)
    fetch_background("creepy abandoned hospital", "test_background.mp4")
