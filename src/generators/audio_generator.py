import asyncio
import edge_tts
import os

def format_ass_time(seconds):
    """Converts seconds to ASS timestamp format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    communicate = edge_tts.Communicate(text, voice)
    words = []
    
    print("Generating audio and Karaoke metadata...")
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 10000000,
                    "end": (chunk["offset"] + chunk["duration"]) / 10000000
                })

    ass_path = output_file.replace(".mp3", ".ass")
    # STYLE SETTINGS: Alignment 5 = Center, Outline 3 = High visibility
    header = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,75,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,1,5,10,10,960,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")
        words_per_line = 3 
        for i in range(0, len(words), words_per_line):
            chunk = words[i:i+words_per_line]
            line_start = format_ass_time(chunk[0]['start'])
            line_end = format_ass_time(chunk[-1]['end'])
            
            # The Magic: {\kX} highlights the word for X centiseconds
            processed_text = ""
            for w in chunk:
                duration_cs = int((w['end'] - w['start']) * 100)
                processed_text += f"{{\\k{duration_cs}}}{w['text'].upper()} "
            
            f.write(f"Dialogue: 0,{line_
