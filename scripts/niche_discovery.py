# scripts/niche_discovery.py
import os
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client

def discover_channel_niche(channel_id, yt_client):
    """Uses LLM to identify niche based on channel content."""
    print(f"🕵️ [NICHE DISCOVERY] Identifying niche for {channel_id}...")
    
    try:
        # 1. Fetch metadata from last 10 uploads
        uploads_id = yt_client.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = yt_client.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=10).execute()
        
        sample_data = ""
        for item in vids.get("items", []):
            title = item["snippet"]["title"]
            desc = item["snippet"]["description"][:100]
            sample_data += f"Title: {title} | Desc: {desc}\n"

        if not sample_data:
            return "General Viral Trends" # Failsafe for empty channels

        # 2. Ask Gemini to classify
        prompt = f"""
        Analyze these YouTube video titles and descriptions:
        {sample_data}
        
        Determine the most accurate 3-5 word niche for this channel. 
        Example: 'Cosmic Mystery and Science Space'
        Return ONLY the niche string. No other text.
        """
        
        niche, _ = quota_manager.generate_text(prompt, task_type="analysis")
        clean_niche = niche.strip().replace('"', '').replace("'", "")
        
        print(f"✅ [NICHE DISCOVERY] Result: '{clean_niche}'")
        return clean_niche
        
    except Exception as e:
        print(f"⚠️ [NICHE DISCOVERY] Failed: {e}")
        return "General Viral Content"

def update_yaml_niche(channel_id, discovered_niche):
    """Updates the channels.yaml file with the new niche."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "channels.yaml")
    
    with open(path, 'r') as f:
        data = yaml.safe_load(f)

    for ch in data.get('channels', []):
        if ch['id'] == channel_id:
            ch['niche'] = discovered_niche
    
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)
