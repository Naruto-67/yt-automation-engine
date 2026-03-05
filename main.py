import os
import json
import traceback
import sys
import shutil

# Master Imports
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error, notify_warning
from scripts.generate_script import generate_script
from scripts.generate_metadata import generate_seo_metadata

# These will be provided in the next blocks to ensure stability
try:
    from scripts.voice_engine import generate_voiceover
    from scripts.visual_engine import fetch_visuals
    from scripts.editor_engine import assemble_video
    from scripts.vault_uploader import upload_to_vault
except ImportError as e:
    print(f"⚠️ [SYSTEM] Some engine components are missing: {e}")

def load_matrix():
    """Loads the 21 trending topics from memory."""
    path = os.path.join("memory", "content_matrix.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_matrix(matrix):
    """Updates the matrix state."""
    path = os.path.join("memory", "content_matrix.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)

def run_production_cycle():
    """
    The Master Loop.
    Processes exactly 4 videos to stay within GitHub Action & API limits.
    """
    print("🚀 [ENGINE] Ignition. Starting Daily Production Cycle...")
    matrix = load_matrix()
    
    if not matrix:
        print("❌ [ENGINE] Content Matrix is empty. Run Weekly Research first.")
        notify_warning("Production", "Matrix empty. Engine idling.")
        return

    # Filter for topics not yet processed
    unprocessed = [t for t in matrix if not t.get("processed", False)]
    batch = unprocessed[:4] # Process 4 per run

    if not batch:
        print("✅ [ENGINE] All topics in the current matrix are completed.")
        notify_summary(True, "All 21 topics processed. Awaiting next Research cycle.")
        return

    success_count = 0
    
    for item in batch:
        topic = item['topic']
        niche = item['niche']
        bg_query = item.get('bg_query', topic)
        
        print(f"\n🎬 [PROCESSING] {niche.upper()}: {topic}")
        
        try:
            # 1. Script & SEO Generation (Uses Groq/Gemini via Quota Manager)
            script_text, hook = generate_script(niche, topic)
            if not script_text: raise Exception("Script Generation Failed")
            
            metadata = generate_seo_metadata(niche, script_text)
            
            # 2. Voiceover Generation (Kokoro V1 / Edge-TTS Fallback)
            audio_path = generate_voiceover(script_text, topic)
            
            # 3. Visual Sourcing (Pexels API / AI Fallback)
            visuals = fetch_visuals(bg_query)
            
            # 4. Video Assembly (MoviePy + FFmpeg)
            video_path = assemble_video(audio_path, visuals, script_text, topic)
            
            # 5. Vault Security (YouTube Upload as Private)
            video_id = upload_to_vault(video_path, metadata)
            
            if video_id:
                item['processed'] = True
                item['video_id'] = video_id
                success_count += 1
                print(f"✅ [SUCCESS] Video secured in vault: {video_id}")
            
            # Local Cleanup to save GitHub Runner disk space
            if os.path.exists(video_path): os.remove(video_path)
            
        except Exception as e:
            print(f"🚨 [CRASH] Failed to process '{topic}': {e}")
            notify_error("Main Production", f"Topic: {topic}", traceback.format_exc())
            continue

    # Finalize state
    save_matrix(matrix)
    
    if success_count > 0:
        msg = f"Batch Complete. {success_count} videos secured in the Vault."
        print(f"🏁 [FINISH] {msg}")
        notify_summary(True, msg)
    else:
        print("⚠️ [FINISH] Batch produced 0 results. Check logs.")

if __name__ == "__main__":
    try:
        run_production_cycle()
    except Exception as e:
        notify_error("Main Engine", "Critical Runtime Failure", traceback.format_exc())
        sys.exit(1)
