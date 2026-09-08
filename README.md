# 👻 Ghost Engine: The Ultimate Guide

**Ghost Engine** is a multi-channel, fully-automated YouTube Shorts production engine. It operates entirely autonomously, researching trending niches, writing scripts, generating neural narration, creating AI visuals, rendering cinematic video with animated captions, and scheduling to YouTube — all running through GitHub Actions on 100% free-tier APIs.

---

## 🛠️ System Architecture & Workflow

The pipeline runs silently in the background via GitHub Actions (`01_daily_pipeline.yml`). When activated, it executes the following modules sequentially:

1. **🧠 Ideation & Research (`dynamic_researcher.py`)**
   - Fetches historical data from your channel using the YouTube API.
   - Analyzes competitor performance and generates 5 highly optimized video concepts using **Google Gemini (Flash)**.
   - Outputs factual insights or character-driven story loglines based on the channel type.

2. **📜 Scriptwriting (`generate_script.py`)**
   - Expands the chosen concept into a 60-second script.
   - Uses **Gemini** (or **Groq** via fallback) with strict `json_object` enforcement to structure scenes, visual prompts, and metadata.

3. **🎙️ Voiceover Synthesis (`generate_voice.py`)**
   - Primary: **EdgeTTS** (Microsoft Azure Neural Voices) for hyper-realistic human pacing.
   - Fallback: **Kokoro-82M** (Local CPU TTS).
   - Generates the `.wav` file, dynamically routing actors (e.g., Deep/Serious vs Fast/Punchy) based on the script's mood.

4. **📝 Captioning (`generate_voice.py` / `render_video.py`)**
   - Uses **Faster-Whisper** to perfectly transcribe the `.wav` file down to the millisecond.
   - Formats the subtitles into `.ass` (Advanced SubStation Alpha), adding CapCut-style neon glow and active-word "pop" animations.

5. **🎨 Visual Generation (`generate_visuals.py`)**
   - Reads the visual prompts generated in Step 2.
   - Auto-discovers the newest **FLUX.1** and **SDXL** models via **HuggingFace** and **Cloudflare Workers AI**.
   - If AI fails, it automatically downloads relevant royalty-free footage from **Pexels**.

6. **🎬 Video Rendering (`render_video.py`)**
   - Merges visuals, audio, and captions using complex **FFmpeg** filters.
   - Applies sub-pixel Ken Burns motion (`zoompan`) and crossfades (`xfade`) for buttery-smooth video transitions.
   - Outputs a crisp `1080x1920` vertical `.mp4`.

7. **🚀 Publishing (`youtube_manager.py`)**
   - Uploads the final video and custom thumbnail to a private vault on YouTube.
   - Applies the generated SEO tags, title, and description.

---

## 📺 Channel Configuration

Your channel rules are defined in the engine.
| Channel | ID | Content Type | Behavior |
|---|---|---|---|
| **AnimeRise** | `CH_01` | **Fictional** | Enforces a strict 3-beat storytelling arc (protagonist, conflict, resolution). Perfect for Pixar-style morals. |
| **Topato** | `CH_02` | **Factual** | Anchors to educational/trending facts. Topics are guaranteed to be diverse and fast-paced. |

---

## 🛡️ The Fallback Cascades (Fail-Safes)

The engine is designed to **never crash**. Every task has a fallback:
- **LLM / Scripting:** Gemini API ➡️ Groq Llama/Mixtral ➡️ Hardcoded Emergency Script.
- **Images:** HuggingFace FLUX ➡️ Cloudflare AI ➡️ Pexels Stock Footage.
- **Voiceover:** EdgeTTS Azure Neural ➡️ Local Kokoro-82M.
- **Rendering:** `xfade` Crossfade ➡️ Hard Cuts (Simple Concat).

---

## ⚙️ How to Test & Use

Because the engine is automated via GitHub Actions, manual usage is simple:

### 1. Test Mode (Local or Sandbox)
If you want to run the pipeline without burning YouTube API quota:
```bash
# Sets TEST_MODE=true in your environment
python main.py
```
This bypasses YouTube auth, skips DB writes, limits output to 1 video per channel, and saves the `.mp4` artifact locally in your workspace.

### 2. Tuning the Settings (`config/settings.yaml`)
You can control the aesthetic of the engine purely through `settings.yaml` without touching code:
- **`render.xfade_duration`**: Adjust the length of crossfades (default 0.3s).
- **`render.pan_percent`**: Adjust the speed of the Ken Burns zoom/pan (default 0.05).
- **`caption_style_presets`**: Adjust font size, neon glow width, and blur strength for captions.

### 3. Kill Switch
To completely halt all GitHub Actions schedules:
Go to GitHub Variables and set `GHOST_ENGINE_ENABLED = false`.

---

## 📦 Requirements & Auto-Upgrading
All dependencies are tracked in `requirements.txt`. Because versioning uses `>=`, GitHub Actions will automatically install the absolute latest models and patches (like `edge-tts` and `faster-whisper`) every time the runner boots up. No manual maintenance is required.