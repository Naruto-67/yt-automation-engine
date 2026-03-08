# naruto-67-yt-automation-engine

Internal automation system. Not intended for public use or contribution.

---

## Purpose

Fully automated YouTube Shorts pipeline. Operates autonomously via GitHub Actions — no human intervention required after initial secrets setup. Produces, uploads, schedules, and promotes short-form video content on a target YouTube channel.

---

## Repository Map

```
naruto-67-yt-automation-engine/
├── main.py                        # Orchestration core — runs the full production cycle
├── requirements.txt               # Python dependencies
├── assets/
│   └── lessons_learned.json       # AI-updated content strategy rules (auto-written by performance_analyst, auto-read by generate_script + generate_metadata)
├── memory/
│   ├── api_state.json             # Per-day quota counters for Gemini / YouTube / Cloudflare / HuggingFace
│   ├── content_matrix.json        # Queue of topics to produce {niche, topic, processed, published, youtube_id}
│   ├── topic_archive.txt          # Append-only history of all used topics (prevents duplicates via Jaccard similarity)
│   └── error_log.txt              # Rolling crash log (auto-trimmed at 1MB)
├── scripts/
│   ├── quota_manager.py           # Central API router: Gemini→Groq fallback, quota tracking, dynamic model discovery
│   ├── dynamic_researcher.py      # Fills content_matrix.json with AI-generated topics using YouTube channel context
│   ├── generate_script.py         # Produces scene-split narration scripts; injects lessons_learned for feedback loop
│   ├── generate_metadata.py       # Produces YouTube SEO title/description/tags; injects channel performance hints
│   ├── generate_voice.py          # TTS pipeline: Kokoro → Groq Orpheus; Whisper subtitles → proportional fallback
│   ├── generate_visuals.py        # 4-tier image pipeline: Cloudflare FLUX → HuggingFace → Pexels → local gradient
│   ├── render_video.py            # FFmpeg render: Ken Burns animation, ASS subtitles, watermark, 1080×1920 9:16
│   ├── youtube_manager.py         # YouTube upload to private vault playlist, playlist management
│   ├── schedule_video.py          # AI-determined optimal publish times, moves from vault to public playlists
│   ├── reply_comments.py          # Replies to fan comments with AI-generated Gen-Z responses
│   ├── performance_analyst.py     # Fetches channel stats, updates lessons_learned.json with new strategy rules
│   ├── discord_notifier.py        # Webhook notifications for every pipeline step (uniform └ field format)
│   ├── groq_client.py             # Groq API client: Llama 3.3 text + Orpheus TTS
│   └── logger.py                  # Optional Google Sheets logging of completed videos
└── .github/
    ├── dependabot.yml             # Weekly pip + actions dependency updates
    └── workflows/
        ├── 00_auto_merge_deps.yml # Auto-merges dependabot patch/minor PRs; flags major bumps for review
        ├── 01_daily_pipeline.yml  # 00:00 UTC — Production: script → voice → visuals → render → vault
        ├── 02_daily_publisher.yml # 06:00 UTC — Publish: vault → AI-timed public schedule + playlists
        ├── 03_daily_pulse.yml     # 17:30 UTC — Analysis: channel stats → update lessons_learned strategy
        ├── 04_audience_engagement.yml # 14:00 UTC — Engagement: reply to 10–15 fan comments
        ├── 05_weekly_research.yml # 20:00 UTC Sunday — Research: refill content_matrix with 21 topics
        ├── 98_cache_audit.yml     # Manual: list GitHub Actions cache usage
        └── 99_cache_nuke.yml      # Manual: purge all GitHub Actions caches
```

---

## Workflow Schedule (UTC)

| Workflow | Cron | UTC Time | IST | Purpose |
|---|---|---|---|---|
| `01_daily_pipeline` | `0 0 * * *` | 00:00 daily | 05:30 | Produce up to 4 videos, upload to private vault |
| `02_daily_publisher` | `0 6 * * *` | 06:00 daily | 11:30 | Schedule vault videos for optimal public release |
| `03_daily_pulse` | `30 17 * * *` | 17:30 daily | 23:00 | Analyse channel performance, update AI strategy |
| `04_audience_engagement` | `0 14 * * *` | 14:00 daily | 19:30 | Reply to fan comments |
| `05_weekly_research` | `0 20 * * 0` | 20:00 Sunday | 01:30 Mon | Refill topic queue with 21 unique topics |

All workflows use `concurrency.group: ghost-engine-lock` to prevent simultaneous runs and quota collisions.

---

## Content Production Flow

```
dynamic_researcher.py
    └─ fills content_matrix.json with {niche, topic} pairs
           │
main.py (01_daily_pipeline)
    ├─ checks vault count (target: ≤14 queued)
    ├─ emergency research if queue < 4 topics
    └─ for each topic (up to 4/run, 3 attempts each):
           ├─ generate_script.py  → narration text + scene image_prompts + pexels_queries
           │      └─ injects lessons_learned.json (emphasize / avoid / preferred_visuals)
           ├─ generate_voice.py   → .wav audio + .srt captions (Whisper or proportional fallback)
           ├─ generate_metadata.py→ SEO title / description / tags
           ├─ generate_visuals.py → scene .jpg images (4-tier cascade)
           ├─ render_video.py     → final_output_N.mp4 (Ken Burns + subtitles + watermark)
           └─ youtube_manager.py  → upload private → vault playlist

schedule_video.py (02_daily_publisher)
    └─ AI picks optimal US publish times from historical view data
       → sets scheduled publish, moves to public playlists, removes from vault

performance_analyst.py (03_daily_pulse)
    └─ fetches channel stats → AI generates new emphasize/avoid rules
       → updates lessons_learned.json (feeds back into next production cycle)
```

---

## AI Provider Hierarchy

**Text Generation**
1. Gemini (auto-discovered latest models via `client.models.list()`, sorted by capability score)
2. Groq Llama 3.3-70b (fallback when Gemini quota exhausted or blocked)

**Text-to-Speech**
1. Kokoro (local, ultra-realistic, random voice from `am_adam / af_bella / am_michael / af_sarah`)
2. Groq Orpheus TTS (API fallback)

**Image Generation**
1. Cloudflare FLUX-1-schnell (official API, 95/day limit)
2. HuggingFace FLUX.1-schnell → SDXL cascade (50/day limit)
3. Pexels stock search (portrait orientation, 3-word query)
4. Python local gradient generator (total API exhaustion failsafe)

---

## Quota Budget (per UTC day)

| Provider | Daily Limit | Tracked In |
|---|---|---|
| YouTube Data API v3 | 9,500 points | `memory/api_state.json` → `youtube_points_used` |
| Gemini API calls | 40 | `gemini_used` |
| Cloudflare Images | 95 | `cf_images_used` |
| HuggingFace Images | 50 | `hf_images_used` |

Video upload costs ~1,600 YouTube points. Each publish/schedule costs ~200 points.

---

## Memory Files

### `memory/content_matrix.json`
Array of topic objects. Schema:
```json
[
  {
    "niche": "Mystery",
    "topic": "The Dyatlov Pass Incident",
    "processed": false,
    "failed_flag": false,
    "published": false,
    "youtube_id": "optional after upload",
    "vaulted_date": "optional ISO timestamp",
    "published_date": "optional ISO timestamp"
  }
]
```
Pruning rules: published items are removed on next research run. Items with `failed_flag: true` are skipped. Matrix targets 21 unprocessed topics maximum.

### `assets/lessons_learned.json`
AI-updated performance strategy. Written by `performance_analyst.py`, read by `generate_script.py` and `generate_metadata.py`.
```json
{
  "emphasize": ["up to 5 rotating rules about what works"],
  "avoid": ["up to 5 rotating rules about what to avoid"],
  "recent_tags": ["tags from recent high-performing videos"],
  "preferred_visuals": ["3D Animation", "Visually rich and detailed animated styles"]
}
```

### `memory/api_state.json`
```json
{
  "last_reset_date": "YYYY-MM-DD",
  "gemini_used": 0,
  "youtube_points_used": 0,
  "cf_images_used": 0,
  "hf_images_used": 0,
  "yt_last_used_date": "YYYY-MM-DD"
}
```
Auto-resets when `last_reset_date` differs from current UTC date.

---

## Required GitHub Secrets

| Secret | Used By |
|---|---|
| `GEMINI_API_KEY` | quota_manager → Gemini text generation |
| `GROQ_API_KEY` | groq_client → Llama text + Orpheus TTS |
| `PEXELS_API_KEY` | generate_visuals → Tier 3 stock images |
| `HF_TOKEN` | generate_visuals → HuggingFace image generation |
| `CF_ACCOUNT_ID` | generate_visuals → Cloudflare AI |
| `CF_API_TOKEN` | generate_visuals → Cloudflare AI |
| `YOUTUBE_CLIENT_ID` | youtube_manager → OAuth |
| `YOUTUBE_CLIENT_SECRET` | youtube_manager → OAuth |
| `YOUTUBE_REFRESH_TOKEN` | youtube_manager → OAuth (expires after ~180 days unused) |
| `DISCORD_WEBHOOK_URL` | discord_notifier → all notifications |
| `GCP_CREDENTIALS_JSON` | logger → optional Google Sheets |
| `GOOGLE_SHEETS_ID` | logger → optional Google Sheets |

---

## Target Audience

Primary: United States. Not hardcoded — `dynamic_researcher.py` queries the channel's own historical performance data and uses it to guide topic selection. If the channel performs better with a different demographic, the research will adapt automatically.

---

## Self-Improvement Loop

The system auto-improves on a 24-hour cycle without any human input:
1. `03_daily_pulse` fetches real view/subscriber data
2. Asks Gemini/Groq to generate one new rule to emphasize and one to avoid based on actual stats
3. Writes updated rules to `assets/lessons_learned.json`
4. Next day's `01_daily_pipeline` reads those rules and injects them into every script and metadata prompt

Gemini models are auto-discovered via API at runtime — when Google releases new models, the engine will use them automatically on next run.

---

## Niche Classification

The `niche` field in the content matrix affects minimum audio duration and pacing:

| Niche keywords | Type | Min audio | Scene count |
|---|---|---|---|
| `fact`, `hack`, `trend`, `brainrot` | Fact-based | 10s | 3–5 scenes |
| Everything else | Story/Mystery | 22s | 5–7 scenes |

---

## Error Handling Architecture

- Per-topic: 3 attempts with progressive API cooldown (60s, 120s)
- Per-script: 3 generation attempts for timing validation (10s–59s window)
- YouTube quota hard stop: saves matrix state and exits cleanly on `403 quota` errors
- Image generation: 4-tier cascade, tiers disabled per-run on auth failure (not per-scene)
- Whisper failure: proportional SRT fallback (words distributed across audio duration)
- `error_log.txt`: rolling, trimmed at 1MB to prevent repo bloat
- All crashes reported to Discord via `notify_error()`

---

*Internal use only. No external documentation, marketing, or contribution guidelines.*
