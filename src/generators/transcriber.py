import os
import json

def transcribe(audio_path, words_per_chunk=3):
    """
    Transcribes audio using WhisperX and produces word-level
    timing chunks in the format video_editor.py expects.

    Output JSON format:
    [
        {
            "start": 0.0,
            "end":   1.2,
            "words": [
                {"text": "TESTING",  "start": 0.0, "end": 0.4},
                {"text": "CAPTIONS", "start": 0.4, "end": 0.9},
                {"text": "NOW",      "start": 0.9, "end": 1.2}
            ]
        },
        ...
    ]
    """
    import whisperx

    timings_path = audio_path.replace(".mp3", "_timings.json")
    device       = "cpu"
    compute_type = "int8"   # int8 = fastest on CPU, no accuracy loss for short clips

    print(f"🎙️  Transcribing: {audio_path}")
    print(f"   Device: {device} | Compute: {compute_type}")

    # ── Step 1: Transcribe with Whisper ──────────────────────────────────────
    # Use "base" model — good accuracy, ~140MB, fast on CPU
    model = whisperx.load_model(
        "base",
        device=device,
        compute_type=compute_type,
        language="en"           # force English — avoids language detection overhead
    )

    audio  = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, batch_size=4)

    print(f"   Transcribed {len(result['segments'])} segments")

    # Free model from memory before loading alignment model
    del model

    # ── Step 2: Align to get word-level timestamps ────────────────────────────
    align_model, metadata = whisperx.load_align_model(
        language_code="en",
        device=device
    )

    result = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio,
        device=device,
        return_char_alignments=False
    )

    del align_model

    # ── Step 3: Extract flat word list ───────────────────────────────────────
    word_segments = result.get("word_segments", [])
    print(f"   Word segments found: {len(word_segments)}")

    if not word_segments:
        raise RuntimeError(
            "WhisperX returned no word segments. "
            "Check that the audio file has clear speech."
        )

    # Normalize — WhisperX sometimes omits start/end on edge words
    words = []
    for i, w in enumerate(word_segments):
        start = w.get("start")
        end   = w.get("end")

        # Fill missing timestamps from neighbors
        if start is None:
            start = words[-1]["end"] if words else 0.0
        if end is None:
            # Use next word's start if available, else start + 0.3s estimate
            if i + 1 < len(word_segments) and word_segments[i+1].get("start"):
                end = word_segments[i+1]["start"]
            else:
                end = start + 0.3

        words.append({
            "text":  w["word"].strip(),
            "start": round(float(start), 3),
            "end":   round(float(end),   3)
        })

    # ── Step 4: Group into N-word chunks ─────────────────────────────────────
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        group = words[i:i + words_per_chunk]
        chunks.append({
            "start": group[0]["start"],
            "end":   group[-1]["end"],
            "words": group
        })

    # ── Step 5: Save timings JSON ─────────────────────────────────────────────
    with open(timings_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2)

    print(f"✅ Timings saved: {timings_path} ({len(chunks)} chunks, {len(words)} words)")
    return timings_path


if __name__ == "__main__":
    import sys
    root_dir   = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    audio_file = os.path.join(root_dir, "test_audio.mp3")

    if not os.path.exists(audio_file):
        print(f"❌ Audio not found: {audio_file}")
        print("   Run audio_generator.py first.")
        sys.exit(1)

    transcribe(audio_file)
