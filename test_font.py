import os
import requests
import zipfile
import io

def download_cinematic_font_secure():
    font_path = "/tmp/Montserrat-Bold.ttf"
    
    # If it's already there, clean it so we force a fresh test
    if os.path.exists(font_path):
        os.remove(font_path)
        print(f"🧹 Removed old font at {font_path} for fresh test.")

    print("📥 [TEST] Downloading Cinematic Font from Google Fonts API...")
    
    # 🚨 FIX: We bypass GitHub entirely. We download the official ZIP bundle directly from the Google Fonts API.
    url = "https://fonts.google.com/download?family=Montserrat"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Google Fonts returns a ZIP file containing all weights (Regular, Bold, Italic, etc.)
        # We must extract it in memory and pull only the Bold TTF.
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # Find the exact filename inside the zip. Usually it's 'static/Montserrat-Bold.ttf' or 'Montserrat-Bold.ttf'
            bold_font_name = next((name for name in z.namelist() if 'Montserrat-Bold.ttf' in name), None)
            
            if not bold_font_name:
                raise FileNotFoundError("Montserrat-Bold.ttf not found inside the downloaded ZIP.")
                
            with open(font_path, 'wb') as f:
                f.write(z.read(bold_font_name))
                
        print(f"✅ [SUCCESS] Font downloaded and extracted to: {font_path}")
        print(f"📊 [INFO] File size: {os.path.getsize(font_path)} bytes")
        return True

    except Exception as e:
        print(f"❌ [FAILED] Font download crashed: {e}")
        return False

if __name__ == "__main__":
    download_cinematic_font_secure()
