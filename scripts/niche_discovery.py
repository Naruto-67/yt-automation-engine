# scripts/niche_discovery.py — Ghost Engine V7.1
import os
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client

def discover_channel_niche(channel_id, yt_client):
    """Uses LLM to identify niche based on channel content."""
    print(f"🕵️ [NICHE DISCOVERY] Identifying niche for {channel_id}...")
    
    try:
        uploads_id = yt_client.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = yt_client.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=10).execute()
        
        sample_data = ""
        for item in vids.get("items", []):
            title = item["snippet"]["title"]
            desc = item["snippet"]["description"][:100]
            sample_data += f"Title: {title} | Desc: {desc}\n"

        if not sample_data:
            return "General Viral Trends" 

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
    """
    GOD-TIER FIX: Updates the channels.yaml file safely.
    Replaces the destructive yaml.dump() to prevent stripping instructional comments.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "channels.yaml")
    temp_path = f"{path}.tmp"
    
    try:
        with open(path, 'r', encoding="utf-8") as f:
            lines = f.readlines()
            
        in_target_channel = False
        for i, line in enumerate(lines):
            if f'id: "{channel_id}"' in line or f"id: '{channel_id}'" in line:
                in_target_channel = True
            
            if in_target_channel and "niche:" in line:
                indent = len(line) - len(line.lstrip())
                lines[i] = f"{' ' * indent}niche: \"{discovered_niche}\"\n"
                break
                
        with open(temp_path, 'w', encoding="utf-8") as f:
            f.writelines(lines)
            
        os.replace(temp_path, path)
    except Exception as e:
        print(f"⚠️ [NICHE DISCOVERY] YAML update failed: {e}")
