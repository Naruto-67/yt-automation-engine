import os
import requests
import urllib.parse
import time
import random

def generate_pollinations_image(prompt, output_path):
    print("      [Pollinations] Attempting AI generation...")
    enhanced_prompt = f"{prompt}, ultra realistic, 8k, cinematic lighting, vertical 9:16"
    safe_prompt = urllib.parse.quote(enhanced_prompt)
    seed = random.randint(1, 100000)
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true&seed={seed}"
    
    # Disguise the GitHub Action as a standard Windows Chrome Browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }
    
    for attempt in range(3): # 3 Retries
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                print(f"      [Pollinations] ⚠️ HTTP {response.status_code} on attempt {attempt+1}")
        except Exception as e:
            print(f"      [Pollinations] ⚠️ Error on attempt {attempt+1}: {e}")
        time.sleep(2)
    return False

def generate_hercai_image(prompt, output_path):
    print("      [Hercai] Attempting AI generation...")
    enhanced_prompt = f"{prompt}, cinematic vertical 9:16"
    safe_prompt = urllib.parse.quote(enhanced_prompt)
    url = f"https://hercai.onrender.com/v3/text2image?prompt={safe_prompt}"
    
    for attempt in range(2):
        try:
            res = requests.get(url, timeout=30).json()
            if "url" in res:
                img_data = requests.get(res["url"], timeout=30).content
                with open(output_path, 'wb') as f:
                    f.write(img_data)
                return True
        except Exception as e:
            print(f"      [Hercai] ⚠️ Error on attempt {attempt+1}: {e}")
        time.sleep(2)
    return False

def fallback_pexels_image(prompt, output_path):
    print("      [Pexels] AI blocked. Attempting guaranteed stock image fallback...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("      [Pexels] ⚠️ No PEXELS_API_KEY found.")
        return False
        
    try:
        # Simplify prompt for Pexels search (grab the main subject)
        search_query = prompt.split(',')[0].split(' ')[-2:] 
        search_query = " ".join(search_query)
        
        url = f"https://api.pexels.com/v1/search?query={search_query}&orientation=portrait&per_page=1"
        headers = {"Authorization": api_key}
        res = requests.get(url, headers=headers, timeout=15).json()
        
        if res.get('photos'):
            img_url = res['photos'][0]['src']['large2x'] # Get high-res vertical
            img_data = requests.get(img_url, timeout=15).content
            with open(output_path, 'wb') as f:
                f.write(img_data)
            return True
        else:
            print(f"      [Pexels] ⚠️ No images found for query: {search_query}")
            return False
    except Exception as e:
        print(f"      [Pexels] ⚠️ Error: {e}")
        return False

def fetch_scene_images(prompts_list, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scene images (TESTING FALLBACKS ONLY)...")
    successful_images = []
    
    for i, prompt in enumerate(prompts_list):
        output_path = f"{base_filename}_{i}.jpg"
        print(f"\n   -> Scene {i+1} Prompt: {prompt[:40]}...")
        
        # 1. Primary Free AI (Pollinations)
        success = generate_pollinations_image(prompt, output_path)
        
        # 2. Secondary Free AI (Hercai)
        if not success:
            success = generate_hercai_image(prompt, output_path)
            
        # 3. Ultimate Free Failsafe (Pexels Stock Image)
        if not success:
            success = fallback_pexels_image(prompt, output_path)
            
        if success:
            successful_images.append(output_path)
            print(f"   ✅ Scene {i+1} saved successfully.")
        else:
            print(f"   ❌ Scene {i+1} completely failed across all free engines.")
            
        time.sleep(2) # Pacing to avoid rate limits
        
    return successful_images
