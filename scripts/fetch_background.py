import os
import requests
import random

def download_pexels_video(query, output_filename="background.mp4"):
    """
    Searches Pexels for a vertical video matching the query,
    picks a random one from the top results, and downloads the highest resolution.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("Error: PEXELS_API_KEY is missing.")
        return False

    headers = {"Authorization": api_key}
    # THE FIX: Changed size=medium to size=large
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&size=large&per_page=10"

    try:
        print(f"Searching Pexels for: '{query}'...")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        if not data.get("videos"):
            print(f"No videos found for query: {query}")
            return False

        # Pick a random video from the top results to keep your shorts unique
        video = random.choice(data["videos"])
        
        video_files = video.get("video_files", [])
        if not video_files:
            print("No downloadable files found for this video.")
            return False
            
        # THE FIX: Sort all available files by resolution (width x height) in descending order
        # This guarantees we grab the true 1080p (or even 4K) file instead of a compressed 720p version.
        video_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
        
        target_file = video_files[0]
        download_link = target_file.get("link")
        
        print(f"Downloading highest quality video ({target_file.get('width')}x{target_file.get('height')})...")
        vid_response = requests.get(download_link, stream=True)
        vid_response.raise_for_status()
        
        with open(output_filename, 'wb') as f:
            for chunk in vid_response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        print(f"Success! Video saved to {output_filename}")
        return True

    except Exception as e:
        print(f"Failed to fetch video: {e}")
        return False

if __name__ == "__main__":
    download_pexels_video("dark space galaxy", "test_video.mp4")
