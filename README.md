# 🎬 TOPATO Production Engine (v2.0)

> **Private Autonomous Production Engine for [@metopato](https://youtube.com/@metopato)**  
> Purpose-built for automated end-to-end creation, voice synthesis, video compositing, and scheduled publishing of high-retention psychological paradoxes and viral shower thoughts.

---

## 🎯 Purpose & Scope

This repository powers the automated daily content pipeline for the YouTube channel **TOPATO** (`@metopato`). 

The engine operates 100% cloud-native via **GitHub Actions CI/CD** with zero local compute requirements. It automates:
1. **Topic Discovery**: Identifies high-velocity cognitive paradoxes, shower thoughts, and psychological phenomena.
2. **Script Generation**: Drafts 50–57 second retention-engineered listicles structured for circular replay loops (and 8–10 minute long-form documentaries).
3. **Voiceover & Subtitles**: Synthesizes natural American English narration (Kokoro / Edge-TTS) paired with animated, word-level CapCut-style typography.
4. **Visual Curation**: Blends curated local tactile ASMR vault assets with high-definition stock footage, strictly enforcing brand safety and vertical 9:16 aspect ratios.
5. **Self-Improving Publishing**: Optimizes YouTube release schedules based on audience view velocity, applies trend-aware SEO titles, and generates subscriber community discussion prompts.

---

## ⚙️ Channel Controls (`config/channel_config.yaml`)

All channel-specific parameters can be customized directly in `config/channel_config.yaml` without touching code:

| Setting Group | Key Levers | Purpose |
| :--- | :--- | :--- |
| **`channel`** | `voice_id`, `speed`, `watermark_text` | Voice profile, delivery speed, and transparent branding. |
| **`prompt_settings`** | `channel_premise`, `extra_instructions`, `fallback_thoughts` | Directs the AI on specific theme angles, custom instructions, and emergency backup lines. |
| **`visual_settings`** | `vault_blend_count`, `visual_taxonomy`, `banned_keywords` | Controls how many local vault clips to blend per video, visual craft themes, and negative filters. |
| **`title_settings`** | `style_template`, `emojis`, `trend_window_days` | Controls title formatting, emoji pool, and trend keyword weighting. |
| **`upload_settings`** | `random_schedule`, `adaptive_schedule_learning`, `thumbnail_strategy` | Controls scheduled release timing, view-velocity learning, and thumbnail extraction. |

---

## 🚀 Running Production

Production runs automatically on cloud runners or can be triggered on demand:

### 1. Scheduled Production
The workflow triggers automatically every day on schedule via GitHub Actions cron, publishing directly to YouTube.

### 2. Manual Dispatch (One-Click)
1. Go to the **Actions** tab in GitHub.
2. Select **Video Production Pipeline (v2.0)** on the left.
3. Click **Run workflow**:
   - Choose `video_type`: `short` (default) or `long`.
   - Check **"Dry Run / Test Mode"** if you want to test generation without uploading to YouTube.
4. Click **Run workflow** to start execution.

### 3. Emergency Kill Switch
To pause or halt operations immediately:
* In GitHub **Actions ➔ System Control (Kill Switch & Modes)**:
  * Select `disable` to halt all production cron jobs.
  * Select `enable` to resume normal operation.
  * Select `test` to force all runs into dry-run mode.

---

## 🔒 Required Repository Secrets

The engine requires the following secrets configured under **Settings ➔ Secrets and variables ➔ Actions**:

* `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` (YouTube Data API OAuth)
* `PEXELS_API_KEY`, `PIXABAY_API_KEY` (HD Stock Video APIs)
* `GROQ_API_KEY` or `GEMINI_API_KEY` (LLM Generation)
* `DISCORD_WEBHOOK` (Optional: Real-time stage status notifications)

---
*Internal production tool for TOPATO. Not intended for public redistribution.*