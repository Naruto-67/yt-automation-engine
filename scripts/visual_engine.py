import os
import requests
import random

def fetch_visuals(query):
    """
    Fetches 9:16 background videos from Pexels API.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("⚠️ [VISUALS] Pexels API Key missing. Using fallback logic.")
        return []

    print(f"🖼️ [VISUALS] Sourcing footage for: {query}")
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=5"
    headers = {"Authorization": api_key}

    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        
        video_files = []
        for video in data.get('videos', []):
            # Pick the best SD/HD mobile-friendly link
            files = video.get('video_files', [])
            # Prefer 1080x1920 or 720x1280
            best_link = next((f['link'] for f in files if f['width'] <= 1080), files[0]['link'])
            video_files.append(best_link)
        
        return video_files
    except Exception as e:
        print(f"❌ [VISUALS] Pexels search failed: {e}")
        return []
