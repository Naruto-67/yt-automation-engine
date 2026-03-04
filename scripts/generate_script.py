import os
import json
from google import genai

def load_improvement_data():
    """
    Reads historical performance data to inject into the prompt.
    This is the foundation of the 'self-improvement' loop.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not read lessons_learned.json: {e}")
            
    return {"avoid": [], "emphasize": ["Fast pacing", "Strong visual hooks"]}

def generate_script(niche, topic):
    """Generates a highly engaging, self-improving YouTube Shorts script."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is missing. Check your environment variables.")
        return None

    client = genai.Client(api_key=api_key)
    
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", []))
    emphasize_list = ", ".join(improvements.get("emphasize", []))

    prompt = f"""
    You are an elite YouTube Shorts scriptwriter targeting a USA demographic.
    Write a highly engaging, fast-paced script for the following niche: {niche}
    The specific topic is: {topic}
    
    CRITICAL RULES BASED ON PAST PERFORMANCE:
    - Emphasize: {emphasize_list}
    - Strictly Avoid: {avoid_list}
    
    NICHE SPECIFICS:
    1. Facts: 100% true, strictly verified, logical order.
    2. Brainrot: High-energy, internet culture, chaotic but retaining attention.
    3. Short Stories: Self-improvement focus, fast pacing, viral hooks.
    
    FORMATTING:
    - The script must be under 130 words total to fit within a 60-second window.
    - Return ONLY the spoken text. 
    - Do not use [HOOK], [BODY], or [OUTRO] headers.
    - Do not include stage directions, music cues, or visual notes. 
    - Just output the exact words to be spoken by the TTS engine.
    """

    try:
        print(f"Generating optimized script for [{niche.upper()}] - {topic}...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        script_text = response.text.strip()
        print("✅ Script generated successfully.")
        return script_text
    except Exception as e:
        print(f"❌ Failed to generate script: {e}")
        return None

if __name__ == "__main__":
    test_script = generate_script("fact", "Crazy hidden secrets inside the Statue of Liberty")
    print("\n--- GENERATED SCRIPT ---")
    print(test_script)
