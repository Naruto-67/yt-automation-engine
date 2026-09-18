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

2. **📜 Scriptwriting & Self-Learning Engine (`generate_script.py` / `self_learning.py`)**
   - **Calibrated Duration Floor & Ceiling**: Strict **85-word floor** and **125-word ceiling** (~40–55s duration at 143 WPM Kokoro pace), perfectly matching YouTube Shorts monetization and retention sweet spot.
   - **Continuous Self-Learning Memory**: Queries `engine/self_learning.py` (`memory/success_patterns.json`) to dynamically inject empirical golden winning trajectories directly into prompt context.
    - **Real-Time Fact Grounding & Anti-Hallucination Gate (`engine/fact_grounding.py`)**: Harnesses Google Search Grounding with Gemini Flash, Wikipedia REST API, and DuckDuckGo to extract verified empirical mechanisms and numbers, enforcing 100% verified facts for Topato (`CH_02`).
    - **Circular Script Seamless Loop Engine (2026 Playbook) (`engine/loop_engine.py`)**: Synthesizes grammatical bridges connecting ending scenes into opening hooks, eliminating sign-offs and pushing Average Percentage Viewed (APV) > 100%.
    - **Living Character Arc Gate (`CH_01` AnimeRise)**: Mandates living character protagonists (apprentice, inventor, scout) with clear dilemmas, decisions, and earned resolutions. Inanimate object poetry ("a leaf fell") is strictly banned.
    - **Empirical Science & History Gate (`CH_02` Topato)**: Mandates 100% verified facts with concrete cellular/mechanical processes, dates, and numbers. Formulaic clichés (*"The reason is stranger than anything you'd expect"*) are deterministically blocked.
    - **Deterministic Closure Gate**: Strictly intercepts and rejects dangling sentences ("It was...", trailing ellipses, unfinished clauses).

3. **🎙️ Voiceover Synthesis & C/C++ Acceleration (`generate_voice.py`)**
   - Primary: **Kokoro-82M** (Local Neural CPU TTS) with emotion preprocessing and OpenMP/ONNX multithreading (`OMP_NUM_THREADS=4`).
   - Fallback 1: **EdgeTTS** (Microsoft Azure Neural Voices).
   - Fallback 2: **Groq Orpheus** native emotion TTS.
   - **ASR & SIMD Vectorization**: Faster-Whisper accelerated with CTranslate2 pure C++ INT8 quantization and AVX2 multithreading.
   - **Prosody & Natural Breath Pauses**: Normalizes em-dashes (`—` → `, `) and en-dashes (`–` → `, `) to comma pauses in Kokoro TTS, eliminating awkward 1.5s dead air pauses and accidental hyphen vocalization.
   - **Phonetic Normalization**: Pre-normalizes symbols and acronyms (`24/7`, `LED`, `AI`, `$`, `%`) and applies post-transcription ASR homophone corrections.
   - **Dead-Air Silence Tightener**: Clamps empty internal pauses >450ms down to 180ms for maximum viewer retention.

4. **📝 Captioning (`generate_voice.py` / `render_video.py`)**
   - Uses **Faster-Whisper** to transcribe word timestamps with millisecond accuracy.
   - Applies phonetic ASR homophone corrections before generating subtitles.
   - **Hyphen & Compound Normalization**: Em-dashes normalize to clean spaces, whitespace-padded hyphens are collapsed into unified compound tokens (`RE-WINDING`), and isolated dashes are stripped.
   - **Smart Punctuation & Karaoke Formatting**: Strips leading/trailing punctuation marks from active-word color tags (`{\c&H0000D7FF&}`) so only word letters highlight in bright yellow, leaving punctuation neutral.
   - Formats subtitles into `.ass` with modern Hormozi-style single-layer bold captions.

5. **🎨 Visual Generation, Routing Isolation & Vision Critic (`generate_visuals.py` / `vision_critic.py`)**
   - **Vision Critic Pre-Flight Inspector (`engine/vision_critic.py`)**: Multimodal Gemini Flash Vision audits candidate frames for anatomical integrity, prompt relevance, and 9:16 vertical composition before compositing; re-rolls flawed frames with targeted remedy hints.
   - **OpenMontage 6-Dimension Slideshow Risk Scorer**: Audits prompt sequences across 6 dimensions (`repetition`, `decorative_visuals`, `weak_motion`, `weak_shot_intent`, `typography_overreliance`, `unsupported_cinematic_claims`). Automatically injects dynamic lenses (35mm wide, 50mm prime, 85mm portrait, 24mm low-angle) and motion framing (push-in, tracking pan, dolly-in) if risk > 0.35.
   - **Delivery Promise & Visual Isolation**: Classifies channel promises via `engine/delivery_promise.py`. Fictional channels (`ANIMATION_LED`) strictly prohibit live-action stock footage (preventing the "lipstick and mall" bug), cascading exclusively to AI generation: Cloudflare FLUX ➡️ HuggingFace FLUX ➡️ Pollinations.ai ➡️ Local Offline Gradient.
   - **CHAI Append-Only Decision Log**: Records all routing decisions to `memory/decision_log.jsonl` for transparent governance.

6. **🎬 Video Studio Mastering, Kinetic Overlays & Contextual SFX (`render_video.py`)**
   - Merges visuals, audio, and captions using complex **FFmpeg** filter graphs.
   - **Hybrid Kinetic Motion Overlays (`engine/kinetic_overlays.py` / `render/kinetic_renderer.js`)**: Real-time hardware-accelerated animated progress bar (`drawbox`) tracking video progress across the bottom edge, with Node.js vector rendering integration.
   - **Contextual Sound Effects (SFX) Layer (`engine/sfx_manager.py`)**: Procedural audio synthesis producing broadcast WAV stems (whooshes, 808 sub-drop impacts, risers) mixed at scene transitions, paired with an opening 3-second pattern interrupt zoom punch.
   - **C-Level Radio Mastering**: Voice channel 80Hz high-pass rumble filter (`highpass=f=80`), de-esser (`deesser=i=0.5:f=0.5`), stereo widener (`stereotools=mwidth=1.35`), dynamic sidechain ducking (12 dB), and EBU R128 broadcast loudness normalization (`loudnorm=I=-14:TP=-1.0:LRA=7`).
   - Applies sub-pixel Ken Burns motion (`zoompan`) and crossfades (`xfade`) at 60fps `1080x1920`.

7. **🔌 Model Context Protocol (MCP) Server & Continuous Integrity (`mcp/` & `scripts/`)**
   - **Ghost Engine Native MCP Server (`mcp/ghost_engine_server.py`)**: Zero-dependency JSON-RPC 2.0 stdio server exposing script previews, slideshow audits, fact verification, decision logs, and system health to Antigravity, Cursor, and Claude Desktop.
   - **Continuous System Health Validator (`scripts/system_integrity_check.py`)**: Automated pre-flight CI health validator verifying YAML configs, memory stores, procedural stems, and Python syntax.
   - **Dependabot Multi-Ecosystem Tracking (`.github/dependabot.yml`)**: Continuous automated dependency updates for pip, GitHub Actions, and Node.js (`/render`).

8. **🚀 Publishing & Monetization (`youtube_manager.py` / `generate_metadata.py`)**
   - Uploads final video and thumbnail to a private vault on YouTube.
   - **High-Converting Pinned Comments**: Generates and automatically posts provocative debate questions to 3x comment engagement.
   - **Monetization CTA Injection**: Inserts description calls-to-action and affiliate link slots.
   - **Self-Learning Trajectory Capture**: Persists verified video runs to `memory/success_patterns.json` to continuously elevate future generations.

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
- **LLM / Scripting:** Dynamic Auto-Discovery Free-Tier Gemini Chain (queries live Google API catalog, mathematically scores semantic versions so newest Flash models automatically rank #1 with zero hardcoding, 60s timeout guard) ➡️ Groq Cloud Chain (`llama-3.3-70b-versatile` / `mixtral-8x7b-32768`) ➡️ Hardcoded Emergency Script.
- **API Resilience:** All API calls are wrapped in `tenacity` exponential backoff (`@retry`) with 3-state Circuit Breakers and non-text / WebSocket live model exclusion filters.
- **Images:** HuggingFace FLUX ➡️ Cloudflare AI ➡️ Pixabay Video (B-Roll) ➡️ Pollinations.ai (Zero-Key) ➡️ Pexels Stock Footage.
- **Thumbnails:** Auto-crops vertical scene visual or extracts frame 1 from stock video clips via FFmpeg to generate 1280x720 YouTube thumbnails with gradient shadows and bold titles.
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