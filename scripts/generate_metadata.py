import os
import json
from google import genai

def generate_seo_metadata(niche, script_text):
    """
    Feeds the final script back into Gemini to generate highly optimized, 
    click-inducing YouTube metadata formatted as JSON.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ GEMINI_API_KEY missing. Using fallback metadata.")
        return get_fallback_metadata(niche)

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are an expert YouTube Shorts SEO manager. I am giving you a script for a Short.
    You need to write the Title, Description, and Tags to make it go viral.

    NICHE: {niche}
    SCRIPT: {script_text}

    RULES:
    1. Title must be under 80 characters, highly engaging, and include "#shorts".
    2. Description should be 2 engaging sentences, followed by 3-5 highly relevant hashtags.
    3. Tags must be a list of 5 to 8 comma-separated keywords.
    
    You MUST return EXACTLY this JSON structure and absolutely nothing else. Do not use markdown blocks like ```json. Just raw text:
    {{
        "title": "Your Viral Title Here #shorts",
        "description": "Your engaging description here.\\n\\n#tag1 #tag2",
        "tags": ["keyword1", "keyword2", "keyword3"]
    }}
    """

    try:
        print("🔍 Generating viral SEO Metadata (Title, Description, Tags)...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        # Clean up the output just in case Gemini tries to use markdown
        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        metadata = json.loads(raw_json)
        
        print(f"✅ SEO Metadata locked! Title: {metadata['title']}")
        return metadata
        
    except Exception as e:
        print(f"❌ Failed to parse SEO metadata: {e}")
        return get_fallback_metadata(niche)

def get_fallback_metadata(niche):
    """Provides safe fallback metadata if the AI hallucinates or fails."""
    clean_niche = niche.replace(" ", "")
    return {
        "title": f"You won't believe this {niche.title()}! 🤯 #shorts",
        "description": f"Check out this crazy {niche.title()}! Make sure to like and subscribe for more daily content.\n\n#shorts #viral #{clean_niche}",
        "tags": ["shorts", "viral", clean_niche, "trending"]
    }

if __name__ == "__main__":
    # Local Test
    res = generate_seo_metadata("fact", "Did you know that honey never spoils? Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still perfectly good to eat.")
    print(json.dumps(res, indent=4))
