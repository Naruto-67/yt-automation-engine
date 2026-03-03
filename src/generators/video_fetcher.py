import os
import requests
import random

def download_pexels_video(query, output_filename="background.mp4"):
    """
    Searches Pexels for a vertical video matching the query,
    picks a random one from the top results, and downloads it.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("Error: PEXELS_API_KEY is missing.")
        return False

    headers = {"Authorization": api_key}
    # We force 'portrait' orientation so it perfectly fits YouTube Shorts
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&size=medium&per_page=10"

    try:
        print(f"Searching Pexels for: '{query}'...")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        if not data.get("videos"):
            print(f"No videos found for query: {query}")
            return False

        # Pick a random video from the results to keep your shorts unique
        video = random.choice(data["videos"])
        
        # Grab the highest quality link available for this video
        video_files = video.get("video_files", [])
        if not video_files:
            print("No downloadable files found for this video.")
            return False
            
        # Sort by quality (resolving to HD if possible)
        hd_files = [f for f in video_files if f.get("quality") == "hd"]
        target_file = hd_files[0] if hd_files else video_files[0]
        
        download_link = target_file.get("link")
        
        print(f"Downloading video from Pexels...")
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
    # Test the API by searching for a cinematic space video
    download_pexels_video("dark space galaxy", "test_video.mp4")
