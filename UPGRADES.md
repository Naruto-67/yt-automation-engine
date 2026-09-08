# Ghost Engine — UPGRADES / CHANGELOG

Every change below is documented with **what → why → files → verify**.

---

## 2026-08 — Four improvements

### 1. CI: Node 20 deprecation fix (build-and-vault)
- **What:** Bumped `actions/upload-artifact` from `@v5` to `@v6` in the daily pipeline and removed the `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` environment hack.
- **Why:** GitHub deprecated Node 20 on Actions runners (Sep 2025). `upload-artifact@v5` targets Node 20 and was being force-run on Node 24; `@v6` runs natively on Node 24 — no hack needed, no deprecation warning.
- **Files:**
  - `.github/workflows/01_daily_pipeline.yml`
- **Verify:** Re-run the `01_Ghost_Daily_Production` workflow — the "Upload Video Artifacts" step no longer shows the Node 20 deprecation notice.

---

### 2. Gemini: use the recommended Chat API
- **What:** Replaced `client.models.generate_content(...)` with the chat-based flow:
  `client.chats.create(model=...)` → `chat.send_message(message=..., config=...)`.
- **Why:** Google recommends Chat for automatic-function-calling (AFC) flows; direct
  `Models.generate_content` triggers a deprecation recommendation and is not the
  supported path for conversational/function-calling models.
- **Files:**
  - `engine/llm_router.py`
- **Verify:** Run any pipeline task that calls Gemini (script gen, research, SEO). Logs
  still show `🤖 [...] Using gemini-…` and the deprecation warning is gone.
- **Note:** Fallback chain, RPM throttle, and retry logic are unchanged.

---

### 3. Auto-add the newest free models (Groq + Cloudflare)
Previously only **Gemini** auto-discovered models at runtime. Groq text was hardcoded to
`llama-3.3-70b-versatile` and Cloudflare was hardcoded to `@cf/black-forest-labs/flux-1-schnell`.

- **Groq text — ranked discovery:**
  - `scripts/groq_client.py` now `GET /models`, scores known-good models by a
    preference ladder, **treats unknown text models as usable** (ranked after known ones),
    and builds an ordered `TEXT_MODELS` chain. Text generation tries each in order.
  - `engine/llm_router.py` routes to the full Groq chain (`Groq Chain -> Auto Chain`)
    instead of one hardcoded model.
  - Falls back to `groq_model_fallback_chain` from `config/settings.yaml` when the
    API call fails.
- **Cloudflare image — model auto-discovery:**
  - `scripts/generate_visuals.py` now queries CF's model catalog
    (`/ai/models/search?task=Text-to-Image`) and picks the best available
    FLUX/SDXL model, caching the result. Falls back to
    `@cf/black-forest-labs/flux-1-schnell` on any failure.
- **Why:** When Google/Groq/CF add new free models, Ghost Engine now picks them up
  with zero code changes instead of waiting for a hardcoded model to be updated.
- **Files:**
  - `scripts/groq_client.py`
  - `engine/llm_router.py`
  - `scripts/generate_visuals.py`
  - `config/settings.yaml` (uses existing `groq_model_fallback_chain`)
- **Verify:** Watch the first `🤖 [GROQ] …` / `🔍 [GROQ]` / `🔍 [CF]` discovery log lines
  in a run. They should list the discovered chain/model.
- **Note:** HuggingFace image-model discovery already existed
  (`discover_hf_image_models`) — untouched.

---

### 4. AnimeRise: real Pixar-style stories, not nonsense
- **Symptom:** The fiction channel generated "life of a random object" / abstract
  one-line topics that became incoherent vignettes.
- **Root cause:** The researcher treated fiction lenses as literal topics, and neither
  the topic stage nor the script stage enforced a character arc.
- **Fixes (layered):**
  1. **Researcher topics → Story Loglines**
     - `scripts/dynamic_researcher.py` now, for `content_type: fictional`, instructs
       the LLM that every topic must be a character-driven logline (protagonist +
       goal + obstacle + emotional payoff) and FORBIDS single nouns, "life of X",
       and abstract one-liners.
     - Creative-lens injection for fiction now says "transform this lens into a warm
       character-driven premise" instead of "make them bizarre".
  2. **Topic quality gate**
     - `run_dynamic_research` now rejects too-short (<5 words), bare-noun ("a brick"),
       or fact-musing ("what if…") topics for fictional channels before inserting.
  3. **Script generation story arc**
     - `scripts/generate_script.py` adds a FICTION STORY ARC instruction block
       (mid-action open, 3-beat arc, one protagonist, earned emotional resolution,
       3D-Pixar visual match).
  4. **Fiction script validation**
     - `validate_script_quality(..., is_fictional=True)` runs a cheap deterministic
       gate: `<20` words or zero protagonist/action markers ⇒ reject & retry
       (never rejects a coherent slow/quiet story).
- **Files:**
  - `scripts/dynamic_researcher.py`
  - `scripts/generate_script.py`
- **Verify:** Run research for AnimeRise — new topics should read like loglines
  ("A shy robot who collects broken toys learns…"). A test-mode run should render a
  short with a clear opening/conflict/resolution instead of disconnected facts.

---

## How to apply to your original repo
These changes were made in the **copy** at
`d:\Github\yt-automation-engine-main_1\yt-automation-engine-main`.
Apply the same diffs in your original:
1. `.github/workflows/01_daily_pipeline.yml`

---

## 2026-09 — The Quality Rework

### 1. Buttery Smooth Transitions (`render_video.py`)
- **What:** Replaced the FFmpeg `crop` filter with `zoompan` and appended `format=yuv420p` normalization before crossfades.
- **Why:** The `crop` filter rounds to whole integer pixels, creating severe stuttering (judder) during the Ken Burns panning effect. `zoompan` calculates sub-pixels for perfectly smooth motion. Additionally, `xfade` (crossfade) requires all input clips to have perfectly matched formats. Pre-normalizing them prevents `xfade` from crashing and falling back to harsh cuts.
- **Files:** `scripts/render_video.py`

### 2. Premium Captions (`render_video.py`)
- **What:** Upgraded the `_srt_to_ass_word_by_word` function to inject `\fscx115\fscy115\t(0,100,\fscx100\fscy100)` ASS tags on the active spoken word.
- **Why:** Replaces the static glowing word with a dynamic, CapCut-style "pop" animation where the word scales to 115% and shrinks back, making the Shorts dramatically more engaging.
- **Files:** `scripts/render_video.py`

### 3. EdgeTTS Voice Engine (`generate_voice.py`)
- **What:** Integrated Microsoft Azure Neural Voices (`edge-tts`) as the primary text-to-speech engine. Relegated Kokoro-82M to a fallback layer.
- **Why:** The free Kokoro model lacked emotional pacing and sounded robotic. EdgeTTS provides completely free, premium Azure neural voices (`en-US-ChristopherNeural`, `en-US-AndrewNeural`, etc.) with 1-to-1 mapping to the LLM's chosen voice persona.
- **Files:** `scripts/generate_voice.py`, `requirements.txt`

### 4. Hugging Face Auto-Discovery Fix (`generate_visuals.py`)
- **What:** Swapped API query parameter from `sort=trending` to `sort=likes`.
- **Why:** HuggingFace removed the `trending` parameter from their public API, causing models discovery to 400 error and fail down to stock footage.
- **Files:** `scripts/generate_visuals.py`

### 5. JSON Format Enforcement (`groq_client.py`)
- **What:** Added logic to strictly inject `response_format={"type": "json_object"}` into the Groq API payload if the prompt demands JSON.
- **Why:** Prevented the LLM from outputting raw text instead of JSON during script generation, eliminating `JSONDecodeError` exhaustion loops.
- **Files:** `scripts/groq_client.py`
2. `engine/llm_router.py`
3. `scripts/groq_client.py`
4. `scripts/generate_visuals.py`
5. `scripts/dynamic_researcher.py`
6. `scripts/generate_script.py`