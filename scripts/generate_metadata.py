import os
import json
from google import genai
from scripts.retry import quota_manager

def generate_seo_metadata(niche, script_text):
    """Generates viral metadata using the central Quota Manager."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ GEMINI_API_KEY missing. Using fallback metadata.")
        return get_fallback_metadata(niche)

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are an expert YouTube Shorts SEO manager. 
    Write the Title, Description, and Tags for this script:
    
    NICHE: {niche}
    SCRIPT: {script_text}

    Return EXACTLY this JSON structure:
    {{
        "title": "Viral Title #shorts",
        "description": "Engaging description.\\n\\n#tag1 #tag2",
        "tags": ["key1", "key2"]
    }}
    """

    try:
        print("🔍 AI SEO: Generating optimized metadata...")
        
        response = quota_manager.safe_execute(
            client.models.generate_content,
            model='gemini-2.0-flash',
            contents=prompt
        )
        
        if response:
            raw_json = response.text.replace("```json", "").replace("```", "").strip()
            metadata = json.loads(raw_json)
            print(f"✅ SEO Metadata locked: {metadata['title']}")
            return metadata
        return get_fallback_metadata(niche)
        
    except Exception as e:
        print(f"❌ Failed to parse SEO metadata: {e}")
        return get_fallback_metadata(niche)

def get_fallback_metadata(niche):
    clean_niche = niche.replace(" ", "")
    return {
        "title": f"The truth about {niche.title()}! 🤯 #shorts",
        "description": f"Check this out! #shorts #viral #{clean_niche}",
        "tags": ["shorts", "viral", clean_niche]
    }

if __name__ == "__main__":
    res = generate_seo_metadata("fact", "Test script text.")
    print(res)
