# 👻 Ghost Engine

**Ghost Engine** is a multi-channel, fully-automated YouTube Shorts production engine.
It researches trending niches, writes scripts, generates narration + AI visuals,
renders vertical Shorts with cinematic Ken Burns + captions, and schedules them to a
private vault on YouTube — all through GitHub Actions on free-tier APIs.

> 📋 **Recent changes:** see [`UPGRADES.md`](UPGRADES.md) for the latest fixes and
> improvements (Node 20 CI fix, Gemini Chat API, Groq/CF model auto-discovery,
> fiction story-arc enforcement).

---

## How It Works

```
Every day:
  Researcher (weekly)  → pulls channel context + competitor insights,
                         generates topics (fact log  lines OR story loglines for fiction)
  Script generator     → writes a paced Shorts script + scene prompts via Gemini/Groq
  Voice generator        → Kokoro TTS (fallback Groq Orpheus)
  Visual generator     → Cloudflare FLUX → HuggingFace cascade → Pexels → offline
  Render engine        → Ken Burns clips with crossfades + mood grade + captions + watermark
  Vault / Publish      → upload to private vault, schedule public publish
```

---

## Channels

| Channel | ID | Content Type |
|---|---|---|
| AnimeRise | CH_01 | **fictional** — 3D/Pixar-style moral storytelling |
| Topato | CH_02 | **factual** — trending/interesting facts |

- `content_type: fictional` → researcher emits **story loglines**, scripts follow a
  **3-beat arc** (protagonist + conflict + resolution), and a deterministic gate rejects
  "nonsense" fiction.
- `content_type: factual` → researcher anchors to the configured niche, scripts are
  short/educational, and topics are guaranteed diverse.

---

## Free-Tier Stack

| Component | Tool |
|---|---|
| Video render | FFmpeg |
| AI (script/SEO/Audit) | Gemini (auto-discovered) → Groq (auto-discovered chain) |
| Voice | Kokoro (CPU) → Groq Orpheus/PlayAI TTS |
| Images | Cloudflare FLUX (auto-discovered) → HuggingFace cascade → Pexels → offline |
| Upload | YouTube Data API (per-channel vault) |
| Storage | SQLite `memory/ghost_engine.db` + git |

---

## Model Auto-Discovery

- **Gemini:** ✓ runtime `models.list()` → version-scored → stable/preview chains.
- **Groq:** ✓ runtime `GET /models` → preference-ranked *including unknown/newer*
  text models → ordered fallback chain.
- **Cloudflare:** ✓ runtime catalog search → picks best FLUX/SDXL image model.
- **HuggingFace:** ✓ runtime `discover_hf_image_models()` cascade (existing).

All fallback chains (e.g. `gemini_model_fallback_chain`, `groq_model_fallback_chain`)
are in `config/settings.yaml` and are used only if discovery fails.

---

## Testing
- `TEST_MODE=true` runs the full pipeline with **no DB writes, no YouTube uploads,
  1 video per channel** and produces downloadable artifacts.
- `python -m pytest tests/` runs the unit test suite.

---

## Manual / System Control
- Kill switch: GitHub **variable** `GHOST_ENGINE_ENABLED=false` halts all scheduled jobs.
- Workflows: `01_daily_pipeline` (build+vault) · `02_daily_publisher` (schedule) ·
  `03_daily_pulse` (analytics) · `05_weekly_research` · `11_weekly_audit`
  (token health + housekeeping + stack audit) · `98/99` cache tools · `run_tests`.