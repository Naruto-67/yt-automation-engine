import os
import requests

def test_download():
    font_path = "/tmp/Montserrat-Bold.ttf"
    
    # Clean previous failed attempts
    if os.path.exists(font_path):
        os.remove(font_path)
        print("🧹 Cleaned old font file.")

    # 🚨 FIX: Using jsDelivr CDN and the Creator's raw GitHub repo. 
    # These endpoints are static, immutable, and do not use bot protection.
    mirrors = [
        "https://cdn.jsdelivr.net/gh/JulietaUla/Montserrat@master/fonts/ttf/Montserrat-Bold.ttf",
        "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Bold.ttf"
    ]

    for url in mirrors:
        print(f"📥 [TEST] Attempting download from: {url}")
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            
            with open(font_path, 'wb') as f:
                f.write(response.content)
            
            # Mathematical verification: A real TTF is > 100KB. If it's less, it's an HTML error page.
            file_size = os.path.getsize(font_path)
            if file_size > 50000: 
                print(f"✅ [SUCCESS] Cinematic Font downloaded flawlessly!")
                print(f"📊 [INFO] Valid TTF File size: {file_size} bytes")
                return True
            else:
                print(f"⚠️ [WARNING] File is too small ({file_size} bytes). Likely a blocked HTML page. Trying next mirror...")
                
        except Exception as e:
            print(f"❌ [FAILED] Mirror crashed: {e}")

    print("💀 [FATAL] All font mirrors failed.")
    return False

if __name__ == "__main__":
    test_download()
