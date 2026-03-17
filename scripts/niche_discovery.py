# scripts/niche_discovery.py
# Ghost Engine V26.0.0 — Automated Identity Alignment
import os
import yaml
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client

def discover_channel_niche(channel_id, yt_client):
    """
    Analyzes the channel's metadata and last 10 uploads to identify the core niche.
    Ensures the engine stays aligned with the channel's actual performance data. [cite: 367]
    """
    print(f"🕵️ [NICHE DISCOVERY] Identifying niche for {channel_id}...")
    
    try:
        # Fetch uploads playlist ID
        channel_data = yt_client.channels().list(part="contentDetails", mine=True).execute()
        uploads_id = channel_data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        # Fetch last 10 videos for context [cite: 368]
        vids = yt_client.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=10).execute()
        
        sample_data = ""
        for item in vids.get("items", []):
            title = item["snippet"]["title"]
            desc = item["snippet"]["description"][:100]
            sample_data += f"Title: {title} | Desc: {desc}\n" [cite: 369]

        if not sample_data:
            return "General Viral Trends" 

        prompt = f"""
        Analyze these YouTube video titles and descriptions:
        {sample_data}
        
        Determine the most accurate 3-5 word niche for this channel.
        Example: 'Cosmic Mystery and Science Space' [cite: 370]
        Return ONLY the niche string. No other text. [cite: 371]
        """
        
        # Quota-guarded analysis call
        niche, _ = quota_manager.generate_text(prompt, task_type="analysis")
        clean_niche = niche.strip().replace('"', '').replace("'", "")
        
        print(f"✅ [NICHE DISCOVERY] Result: '{clean_niche}'")
        return clean_niche
        
    except Exception as e:
        print(f"⚠️ [NICHE DISCOVERY] Failed: {e}")
        return "General Viral Content" [cite: 372]

def update_yaml_niche(channel_id, discovered_niche):
    """
    Safely updates the channels.yaml file.
    Preserves all existing instructional comments and formatting. [cite: 373]
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "channels.yaml")
    temp_path = f"{path}.tmp"
    
    try:
        with open(path, 'r', encoding="utf-8") as f:
            lines = f.readlines() [cite: 373]
          
        in_target_channel = False
        for i, line in enumerate(lines):
            # Locate the specific channel block
            if f'id: "{channel_id}"' in line or f"id: '{channel_id}'" in line:
                in_target_channel = True
            
            # Update only the niche field for that channel [cite: 374]
            if in_target_channel and "niche:" in line:
                indent = len(line) - len(line.lstrip())
                lines[i] = f"{' ' * indent}niche: \"{discovered_niche}\"\n"
                break
                
        with open(temp_path, 'w', encoding="utf-8") as f:
            f.writelines(lines)
         
        # Atomic replacement to prevent data loss
        os.replace(temp_path, path) [cite: 375]
    except Exception as e:
        print(f"⚠️ [NICHE DISCOVERY] YAML update failed: {e}")
