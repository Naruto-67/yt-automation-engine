import os
import google.generativeai as genai

def generate_script(niche, topic):
    """Generates a YouTube Shorts script tailored to the specific niche."""
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        print("Error: GEMINI_API_KEY is missing.")
        return None
        
    genai.configure(api_key=api_key)
    
    # Using the updated 2.5 Flash model
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    You are an elite YouTube Shorts scriptwriter. 
    Write a highly engaging, fast-paced script for the following niche: {niche}
    The specific topic is: {topic}
    
    CRITICAL FORMATTING RULES:
    1. If the niche is 'facts', every single detail MUST be 100% true, factually verified, and presented in a completely logical, step-by-step order. Zero exaggeration or made-up claims.
    2. If the niche is 'brainrot' or 'short stories', focus entirely on high-energy pacing, viral hooks, and retaining the viewer's attention at all costs.
    3. The script must be under 150 words total (around 45-60 seconds spoken).
    
    Output the script using exactly these three headers:
    [HOOK] 
    (Write the first 3 seconds here)
    
    [BODY]
    (Write the main content here)
    
    [OUTRO]
    (Write a quick call to action here)
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Failed to generate script: {e}")
        return None

if __name__ == "__main__":
    # Testing the logic constraints with a factual prompt
    print("Booting up Gemini AI...")
    test_script = generate_script("facts", "How black holes bend time")
    print("\n--- GENERATED SCRIPT ---")
    print(test_script)
