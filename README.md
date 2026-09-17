# 👻 Ghost Engine: The Ultimate Guide

**Ghost Engine** is a multi-channel, fully-automated YouTube Shorts production engine. It operates entirely autonomously, researching trending niches, writing scripts, generating neural narration, creating AI visuals, rendering cinematic video with animated captions, and scheduling to YouTube — all running through GitHub Actions on 100% free-tier APIs.

---

## 🛠️ System Architecture & Workflow

The pipeline runs silently in the background via GitHub Actions (`01_daily_pipeline.yml`). When activated, it executes the following modules sequentially:

1. **🧠 Ideation & Research (`dynamic_researcher.py`)**
   - Fetches historical data from your channel using the YouTube API.
   - Injects the **Top 5 US Google Trends** dynamically to bridge educational facts with pop-culture for maximum virality.
   - Analyzes competitor performance and generates 5 highly optimized video concepts using **Google Gemini (Flash)**.
   - Outputs factual insights or character-driven story loglines based on the channel type.

2. **📜 Scriptwriting (`generate_script.py`)**
   - Universal Engine Constitution: Hard 131-word ceiling (≤55s duration), advertiser safety, and zero AI clichés.
   - **Prompt Sharding**: Routes to `FictionalShard` (Pixar 3-beat arc), `FactualShard` (curious loops & pattern interrupts), or `QuizShard` (interactive questions).
   - **Deterministic Closure Gate**: Strictly intercepts and rejects dangling sentences ("It was...", trailing ellipses, unfinished clauses).
   - **OpenMontage Variation Check**: Enforces scene balance (no single scene >50% duration) and variety.

3. **🎙️ Voiceover Synthesis (`generate_voice.py`)**
   - Primary: **Kokoro-82M** (Local Neural CPU TTS) with emotion preprocessing.
   - Fallback 1: **EdgeTTS** (Microsoft Azure Neural Voices).
   - Fallback 2: **Groq Orpheus** native emotion TTS.
   - **Punctuation Normalization Dictionary**: Normalizes em-dashes (`—` → ` - `), en-dashes (`–`), unicode ellipses (`…` → `.`), smart quotes, and semicolons/colons to eliminate TTS dead-air pauses and robotic pitch drops.
   - **Phonetic Normalization**: Pre-normalizes symbols and acronyms (`24/7`, `LED`, `AI`, `$`, `%`) and applies post-transcription ASR homophone corrections.
   - **Dead-Air Silence Tightener**: Clamps empty internal pauses >450ms down to 180ms for maximum viewer retention.

4. **📝 Captioning (`generate_voice.py` / `render_video.py`)**
   - Uses **Faster-Whisper** to transcribe word timestamps with millisecond accuracy.
   - Applies phonetic ASR homophone corrections before generating subtitles.
   - **Smart Punctuation & Karaoke Formatting**: Normalizes unicode punctuation and strips leading/trailing punctuation marks from active-word color tags (`{\c&H0000D7FF&}`) so only word letters highlight in bright yellow, leaving punctuation neutral.
   - Formats subtitles into `.ass` (Advanced SubStation Alpha) with modern Hormozi-style single-layer bold captions and word-by-word active highlighting.

5. **🎨 Visual Generation (`generate_visuals.py`)**
   - **5-Layer Cinematography & Anti-Slideshow Rotation**: Automatically enriches prompts with rotating camera lenses (35mm/50mm/85mm), dynamic motion framing (wide push-in, medium close-up, low-angle tilt, macro), tactile textures, and lighting keys across scenes to eliminate repetitive slideshow visuals.
   - Auto-discovers **FLUX.1** and **SDXL** models via **HuggingFace** and **Cloudflare Workers AI** (bypassed in test mode to protect daily quotas).
   - Multi-tier visual fallback: HuggingFace FLUX ➡️ Cloudflare FLUX ➡️ Pixabay Stock Video ➡️ Pollinations.ai ➡️ Pexels.

6. **🎬 Video Studio Mastering (`render_video.py`)**
   - Merges visuals, audio, and captions using complex **FFmpeg** filter graphs.
   - **Photographic Film S-Curves**: Applies `curves=all='0/0.03 0.25/0.22 0.5/0.50 0.75/0.78 1/0.97'` for rich cinematic shadows and highlight roll-off.
   - **Dynamic Sidechain Ducking**: Compresses background music by 12 dB under voice narration (`sidechaincompress`).
   - **EBU R128 Broadcast Mastering**: Delivers audio normalized to YouTube Shorts target loudness (`loudnorm=I=-14:TP=-1.0:LRA=7`).
   - **Silent Audio Synthesis Guard**: Employs `anullsrc` stereo 48kHz synthesis to prevent crashes on silent stock clips.
   - Applies sub-pixel Ken Burns motion (`zoompan`) and crossfades (`xfade`) at 60fps `1080x1920`.

7. **🚀 Publishing & Monetization (`youtube_manager.py` / `generate_metadata.py`)**
   - Uploads final video and thumbnail to a private vault on YouTube.
   - **High-Converting Pinned Comments**: Generates and automatically posts provocative debate questions to 3x comment engagement.
   - **Monetization CTA Injection**: Inserts description calls-to-action and affiliate link slots.

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
- **API Resilience:** All API calls are wrapped in `tenacity` exponential backoff (`@retry`) with 3-state Circuit Breaker.
- **Images:** HuggingFace FLUX ➡️ Cloudflare AI ➡️ Pixabay Video (B-Roll) ➡️ Pollinations.ai (Zero-Key) ➡️ Pexels Stock Footage.
- **Voiceover:** Local Kokoro-82M ➡️ EdgeTTS Azure Neural ➡️ Groq Orpheus.
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