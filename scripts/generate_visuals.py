# scripts/generate_visuals.py
import os
import requests
import urllib.parse
import time
import random
import base64
import re
import yaml
import traceback
import logging
from PIL import Image, ImageDraw
from scripts.quota_manager import quota_manager
from engine.guardian import guardian
from engine.slideshow_risk import audit_and_remedy_prompts
from engine.decision_log import decision_log
from engine.vision_critic import vision_critic

logger = logging.getLogger("yt_engine.visuals")


def is_test_mode() -> bool:
    return (
        os.environ.get("TEST_MODE", "false").lower() == "true"
        or os.environ.get("GHOST_ENGINE_ENABLED", "").lower() == "test"
    )

SIMULATE_CASCADE_TEST = is_test_mode()

_HF_MODELS_CACHE = []
# Models that returned 410 (deprecated/removed) this session — skip without retrying
_HF_SESSION_BLACKLIST: set = set()

# ── Minimum acceptable image file size ────────────────────────────────────────
# HuggingFace and Cloudflare occasionally return HTTP 200 with:
#   - An HTML error page (~1-5 KB of text)
#   - A tiny loading placeholder PNG (< 2 KB)
#   - A partially transferred JPEG (truncated / corrupt)
# Writing these to disk then passing them to FFmpeg causes silent black frames
# or render crashes. This threshold catches all three cases.
_MIN_IMAGE_BYTES = 10_000   # 10 KB — any real 1080x1920 image is well above this


def _validate_image(path: str) -> bool:
    """
    Returns True only if the file at `path` is a valid, fully-decodable image
    of at least _MIN_IMAGE_BYTES. Rejects HTML error pages, tiny placeholders,
    and truncated JPEGs before they reach FFmpeg.
    """
    try:
        if not os.path.exists(path):
            return False
        if os.path.getsize(path) < _MIN_IMAGE_BYTES:
            print(f"      ⚠️ [VALIDATE] Image too small ({os.path.getsize(path)} bytes < {_MIN_IMAGE_BYTES}). Rejecting.")
            return False
        # PIL.verify() checks the file header and trailer without loading all pixels —
        # fast and catches truncated JPEGs and non-image content.
        with Image.open(path) as img:
            img.verify()
        # verify() leaves the file in an uncertain state — re-open to confirm size
        with Image.open(path) as img:
            w, h = img.size
            if w < 64 or h < 64:
                print(f"      ⚠️ [VALIDATE] Image dimensions too small ({w}x{h}). Rejecting.")
                return False
        return True
    except Exception as e:
        print(f"      ⚠️ [VALIDATE] Image failed decode check: {e}. Rejecting.")
        return False


# Appended to every image generation request to push output quality toward
# the vivid, photorealistic aesthetic of the manually-created Topato videos.
_QUALITY_SUFFIX = (
    ", vertical 9:16 format, photorealistic, highly detailed, "
    "vibrant cinematic lighting, vivid colors, 8k quality, masterpiece"
)
# Cloudflare has a 200-char prompt limit — leave room for suffix
_PROMPT_MAX_BASE = 180

# ─── OpenMontage 5-Layer Cinematography Shot Prompt Framework ─────────────────
_SHOT_SIZE_PHRASES = {
    "extreme_wide": "extreme wide shot showing vast environment",
    "wide": "wide shot capturing full scene",
    "medium_wide": "medium-wide shot framing subject with surroundings",
    "medium": "medium shot from waist up",
    "medium_close": "medium close-up from chest up",
    "close_up": "close-up focusing on face or detail",
    "extreme_close_up": "extreme close-up on fine detail",
    "insert": "insert shot of specific detail",
    "establishing": "establishing shot setting the location",
}

_MOVEMENT_PHRASES = {
    "static": "locked-off static camera",
    "pan_left": "smooth pan to the left",
    "pan_right": "smooth pan to the right",
    "tilt_up": "gentle tilt upward",
    "tilt_down": "gentle tilt downward",
    "dolly_in": "slow dolly in toward subject",
    "dolly_out": "slow dolly out from subject",
    "tracking_left": "tracking shot moving left alongside subject",
    "tracking_right": "tracking shot moving right alongside subject",
    "orbital": "orbital camera circling subject",
    "zoom_in": "slow zoom in",
    "zoom_out": "slow zoom out",
}

_LIGHTING_PHRASES = {
    "high_key": "bright high-key lighting, minimal shadows",
    "low_key": "dramatic low-key lighting with deep shadows",
    "natural": "natural ambient lighting",
    "golden_hour": "warm golden hour sunlight",
    "blue_hour": "cool blue hour twilight",
    "volumetric": "volumetric light with visible rays",
    "neon": "neon-lit with vibrant color spill",
}

def build_cinematography_prompt(scene_data, style_hint: str = "", index: int = 0, total_scenes: int = 1) -> str:
    """
    OpenMontage 5-Layer Cinematography & Anti-Slideshow Framework:
    Layer 1: Camera (lens, DOF)
    Layer 2: Movement (shot size, dynamic camera motion)
    Layer 3: Subject (description + tactile texture keywords)
    Layer 4: Lighting (lighting key, color temperature)
    Layer 5: Style context (vertical 9:16, cinematic composition)

    If scene_data is a dict with 'shot_language', maps explicitly.
    If scene_data is a string, dynamically enriches it with progressive
    shot variation (rotating camera framing and lenses across scene indices)
    to eliminate repetitive slideshow risk.
    """
    if not scene_data:
        return ""

    if isinstance(scene_data, dict):
        sl = scene_data.get("shot_language", {})
        layers = []

        # Layer 1: Camera
        cam = []
        if sl.get("lens_mm"): cam.append(f"{sl['lens_mm']}mm lens")
        if sl.get("depth_of_field"): cam.append(f"{sl['depth_of_field']} depth of field")
        if cam: layers.append(", ".join(cam))

        # Layer 2: Movement
        mov = []
        if sl.get("shot_size"): mov.append(_SHOT_SIZE_PHRASES.get(sl["shot_size"], sl["shot_size"]))
        if sl.get("camera_movement") and sl["camera_movement"] != "static":
            mov.append(_MOVEMENT_PHRASES.get(sl["camera_movement"], sl["camera_movement"]))
        if mov: layers.append(", ".join(mov))

        # Layer 3: Subject & Textures
        subj = [scene_data.get("description", scene_data.get("visual_prompt", ""))]
        if scene_data.get("texture_keywords"):
            subj.append(", ".join(scene_data["texture_keywords"]))
        layers.append(". ".join(filter(None, subj)))

        # Layer 4: Lighting
        lit = []
        if sl.get("lighting_key"): lit.append(_LIGHTING_PHRASES.get(sl["lighting_key"], sl["lighting_key"]))
        if sl.get("color_temperature"): lit.append(f"{sl['color_temperature']} color palette")
        if lit: layers.append(", ".join(lit))

        # Layer 5: Style
        if style_hint: layers.append(f"Style: {style_hint}")

        built = ". ".join(filter(None, layers))
        return built or scene_data.get("description", scene_data.get("visual_prompt", ""))

    # When scene_data is a raw string prompt
    raw_prompt = str(scene_data).strip()
    if not raw_prompt:
        return raw_prompt

    # Rotational shot sizes and dynamic camera motion for variety (anti-slideshow)
    shot_rotations = [
        ("35mm lens, subtle depth of field", "establishing wide shot, slow cinematic push-in", "dramatic low-key lighting with deep shadows"),
        ("50mm prime lens, shallow depth of field", "medium close-up from chest up, steady camera", "warm golden hour side-lighting"),
        ("85mm portrait lens, deep optical bokeh", "close-up focusing on key subject details, slow dolly in", "volumetric light rays with atmospheric dust"),
        ("24mm wide-angle lens, deep focus", "dynamic low-angle shot looking up, subtle camera tilt", "high-contrast cinematic chiaroscuro"),
        ("100mm macro lens, ultra-shallow depth of field", "extreme close-up on fine surface textures", "cool blue hour ambient fill with rim light"),
        ("35mm anamorphic lens, cinematic oval bokeh", "tracking shot moving smoothly alongside subject", "neon-lit atmospheric glow with soft reflections"),
    ]
    cam_lens, mov_phrase, light_phrase = shot_rotations[index % len(shot_rotations)]

    lower_p = raw_prompt.lower()
    layers = []

    if not any(k in lower_p for k in ["lens", "mm", "depth of field", "bokeh"]):
        layers.append(cam_lens)
    if not any(k in lower_p for k in ["close-up", "wide shot", "tracking", "dolly", "angle", "pan"]):
        layers.append(mov_phrase)

    layers.append(raw_prompt)

    if not any(k in lower_p for k in ["lighting", "light", "golden hour", "shadow", "neon", "chiaroscuro"]):
        layers.append(light_phrase)

    if style_hint and f"style: {style_hint.lower()}" not in lower_p:
        layers.append(f"Style: {style_hint}")

    return ", ".join(filter(None, layers))


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _execute_jitter_backoff(attempt: int, api_name: str):
    if attempt == 0:
        wait_time = random.uniform(5.0, 10.0)
        tier = "Low"
    elif attempt == 1:
        wait_time = random.uniform(20.0, 40.0)
        tier = "Mid"
    else:
        wait_time = random.uniform(40.0, 60.0)
        tier = "High"
    print(f"      ⏳ [{api_name} RPM] Tier {tier} backoff. Cooling down for {wait_time:.1f}s...")
    time.sleep(wait_time)


def _regenerate_safe_prompt(bad_prompt):
    prompts_cfg = load_config_prompts()
    sys_msg  = prompts_cfg.get("visual_safety", {}).get("system_prompt", "You are an AI Safety Filter & Creative Prompt Engineer.")
    template = prompts_cfg.get("visual_safety", {}).get("user_template", "Rewrite this to be safe: {bad_prompt}")
    user_msg = template.format(bad_prompt=bad_prompt)
    try:
        clean_text, _ = quota_manager.generate_text(user_msg, task_type="creative", system_prompt=sys_msg)
        if clean_text:
            return clean_text.strip().replace('"', '').replace('\n', ' ')
    except Exception:
        trace = traceback.format_exc()
        print(f"⚠️ [VISUALS] Prompt rewrite failed:\n{trace}")
    return "Cinematic 3D animation of a mysterious artifact, highly detailed"


def discover_hf_image_models():
    global _HF_MODELS_CACHE
    if _HF_MODELS_CACHE:
        return _HF_MODELS_CACHE

    print("🔍 [HF] Auto-discovering trending text-to-image models...")
    try:
        url = "https://huggingface.co/api/models?pipeline_tag=text-to-image&sort=likes&limit=20"
        headers = {}
        token = os.environ.get("HF_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            models_data = res.json()
            candidates  = [m['id'] for m in models_data]

            def _score_hf(name):
                s = 0
                n = name.lower()
                if 'flux'         in n: s += 50
                if 'schnell'      in n: s += 40   # free tier, fast — highest priority
                # FLUX.1-dev and dev-gguf require HF Pro subscription.
                # They always 403 on free accounts → penalise so schnell wins.
                if 'flux.1-dev'   in n or 'flux-1-dev' in n: s -= 60
                if 'gguf'         in n: s -= 80   # GGUF quantized — not runnable on HF Inference API
                if 'stable-diffusion' in n: s += 20
                if 'turbo'        in n or 'lightning' in n: s += 15
                if 'lora'         in n or 'controlnet' in n or 'adapter' in n or 'ip-adapter' in n: s -= 100
                # Deprecated models (known to 410): penalise hard so they sort to bottom
                if 'xl-base-1.0' in n or 'v1-5' in n or 'v1-4' in n: s -= 200
                return s

            valid_models = [m for m in candidates if _score_hf(m) > 0]
            valid_models.sort(key=_score_hf, reverse=True)

            if valid_models:
                # Only cache on successful discovery so stale fallback list
                # is never locked in if the API later becomes available.
                _HF_MODELS_CACHE = valid_models[:4]
                print(f"✅ [HF] Model cascade dynamically updated: {_HF_MODELS_CACHE}")
                return _HF_MODELS_CACHE
        else:
            print(f"⚠️ [HF] Discovery failed (HTTP {res.status_code}): {res.text[:100]}")

    except Exception:
        trace = traceback.format_exc()
        print(f"⚠️ [HF] Discovery failed:\n{trace}")

    # Do NOT set _HF_MODELS_CACHE here — keep it empty so next run retries discovery.
    # ── BUG #5 NOTE: These fallbacks are also PRO-tier on the current HF free
    # plan. If 403s persist after upgrading, swap in smaller open-weight models.
    return ["black-forest-labs/FLUX.1-schnell", "runwayml/stable-diffusion-v1-5", "prompthero/openjourney"]


_CF_MODEL_CACHE = None
_CF_DISCOVERY_FAILED = False   # session flag: True after 2 consecutive discovery failures


def discover_cf_image_model() -> str:
    """
    Auto-discover the best available Cloudflare Workers-AI text-to-image model.

    Queries CF's model catalog, prefers FLUX/SDXL image models, and caches the
    result. Falls back to the proven default (@cf/black-forest-labs/flux-1-schnell)
    if discovery fails. Returns the fully-qualified '@cf/...' model id.

    After 2 consecutive failures the session flag _CF_DISCOVERY_FAILED is set so
    every subsequent scene skips the HTTP round-trip entirely.
    """
    global _CF_MODEL_CACHE, _CF_DISCOVERY_FAILED

    # Fast paths: already cached or disabled for this run
    if _CF_MODEL_CACHE:
        return _CF_MODEL_CACHE
    if _CF_DISCOVERY_FAILED:
        return "@cf/black-forest-labs/flux-1-schnell"

    default = "@cf/black-forest-labs/flux-1-schnell"
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    if not account_id or not api_token:
        _CF_DISCOVERY_FAILED = True
        return default

    try:
        headers = {"Authorization": f"Bearer {api_token}"}
        url = (f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
               f"/ai/models/search?task=Text-to-Image&per_page=50")
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json().get("result", [])
            if isinstance(data, list) and data:
                # Prefer modern image gen models, prioritize FLUX
                def _cf_score(model_id: str) -> int:
                    n = model_id.lower()
                    s = 0
                    if "flux" in n:
                        s += 40
                    if "schnell" in n:
                        s += 20
                    if "stable-diffusion" in n or "sd3" in n or "sd-3" in n:
                        s += 10
                    if "chat" in n or "llama" in n or "text-" in n:
                        return -1  # not an image model
                    return s

                # CF API returns a list of dicts like {"name": "@cf/...", "task": {...}}
                # Extract the model id string from each item safely.
                model_ids = []
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("name", "")
                    else:
                        name = str(item)
                    if name:
                        model_ids.append(name)

                scored = [(m, _cf_score(m)) for m in model_ids if _cf_score(m) >= 0]
                if scored:
                    scored.sort(key=lambda x: x[1], reverse=True)
                    _CF_MODEL_CACHE = scored[0][0]
                    print(f"🔍 [CF] Image model discovered: {_CF_MODEL_CACHE}")
                    return _CF_MODEL_CACHE
    except Exception as e:
        print(f"⚠️ [CF] Model discovery failed ({e}) — using default for this run.")

    # Discovery failed — disable for rest of run to avoid per-scene HTTP calls
    _CF_DISCOVERY_FAILED = True
    print("⚠️ [CF] Model discovery disabled for this run after failure. Using hardcoded default.")
    return default




def generate_cloudflare_image(prompt, output_path):
    print("      [Tier 1: Cloudflare AI] Attempting FLUX/Text-to-Image...")
    if SIMULATE_CASCADE_TEST or quota_manager.is_provider_exhausted("cloudflare"):
        return False, "Quota Reached"

    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token  = os.environ.get("CF_API_TOKEN")
    if not account_id or not api_token:
        return False, "Missing CF Credentials"

    cf_model = discover_cf_image_model()
    url     = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{cf_model}"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}

    # Trim base to leave room for the quality suffix (CF hard-limits total prompt)
    clean_base = prompt[:_PROMPT_MAX_BASE].replace('"', '').replace('\n', ' ')
    payload    = {"prompt": f"{clean_base}{_QUALITY_SUFFIX}"}

    for retry in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
            if response.status_code == 200:
                data = (
                    response.json()
                    if "application/json" in response.headers.get("Content-Type", "")
                    else None
                )
                if data and "result" in data and "image" in data["result"]:
                    with open(output_path, "wb") as f:
                        f.write(base64.b64decode(data["result"]["image"]))
                else:
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                if not _validate_image(output_path):
                    if retry < 2:
                        _execute_jitter_backoff(retry, "CF AI")
                        continue
                    return False, "Invalid image data"
                quota_manager.consume_points("cloudflare", 1)
                return True, ""
            elif response.status_code >= 500 and retry < 2:
                _execute_jitter_backoff(retry, "CF AI")
                continue
            elif response.status_code == 400:
                return False, "HTTP 400 (Safety Filter)"
            # ── BUG #3 FIX: auth/billing failures were silently returned with
            # no log output — operator had zero visibility into why CF was failing.
            # Now we log the status code and a clear action item.
            elif response.status_code in [401, 403]:
                try:
                    err_body = response.json()
                    err_msg  = err_body.get("errors", [{}])[0].get("message", response.text[:120])
                except Exception:
                    err_msg  = response.text[:120]
                print(f"      ❌ [CF {response.status_code}] Auth/billing failure: {err_msg}")
                print(f"      ⛔ Check CF_API_TOKEN secret and Cloudflare AI Workers billing.")
                return False, f"CF Auth Error ({response.status_code})"
            elif response.status_code == 429:
                print(f"      ⚠️ [CF 429] Rate limit hit. Backing off...")
                if retry < 2:
                    _execute_jitter_backoff(retry, "CF AI")
                    continue
                return False, "CF Rate Limited"
            else:
                print(f"      ❌ [CF {response.status_code}] Unexpected response.")
                return False, f"HTTP {response.status_code}"
        except Exception:
            trace = traceback.format_exc()
            print(f"🚨 [CF AI ERROR]:\n{trace}")
            if retry < 2:
                _execute_jitter_backoff(retry, "CF AI")
                continue
            return False, "Timeout Error"
    return False, "Exhausted Retries"


def generate_huggingface_cascade(prompt, output_path):
    print("      [Tier 2: HuggingFace] Attempting AI cascade...")
    if quota_manager.is_provider_exhausted("huggingface"):
        return False, "HF Quota Reached"
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        return False, "No Token"

    dynamic_models = discover_hf_image_models()
    headers        = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}

    clean_base = prompt[:_PROMPT_MAX_BASE].replace('"', '').replace('\n', ' ')
    payload    = {"inputs": f"{clean_base}{_QUALITY_SUFFIX}"}

    for model in dynamic_models:
        # Skip models already known to be deprecated/removed this session
        if model in _HF_SESSION_BLACKLIST:
            continue

        short_name = model.split('/')[-1]
        print(f"      -> Routing to {short_name}...")
        if SIMULATE_CASCADE_TEST and "FLUX" in model:
            continue

        url = f"https://router.huggingface.co/hf-inference/models/{model}"

        for retry in range(3):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=(15, 60))
                if response.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    if not _validate_image(output_path):
                        # HF returned HTTP 200 but content is garbage (HTML, tiny PNG, truncated)
                        print(f"      ⚠️ [HF VALIDATE] {short_name} returned invalid image data. Trying next model.")
                        break  # skip to next model — don't retry same bad response
                    quota_manager.consume_points("huggingface", 1)
                    return True, f"HF ({short_name})"

                # ── BUG #1 FIX: 401/402/403/404 were silently `break`-ing with
                # zero log output. The caller (fetch_scene_images) checked:
                #   any(x in err for x in ["401","402","403"])
                # but the error returned was always "HF Exhausted" — so
                # tier2_active was never set to False, causing HF to be retried
                # for EVERY remaining scene (14× today). Now:
                #   • Auth failures (401/402/403) → log + bail entire cascade
                #   • 404 (model not found) → log + try next model only
                elif response.status_code in [401, 402, 403]:
                    try:
                        err_body = response.json()
                        err_msg  = err_body.get("error", response.text[:200])
                    except Exception:
                        err_msg  = response.text[:200]
                    print(f"      ❌ [HF {response.status_code}] {short_name}: {err_msg}")
                    print(f"      ⛔ HF auth/billing failure. Bailing entire cascade.")
                    print(f"      💡 Check HF_TOKEN expiry and account plan (PRO required for FLUX/SDXL).")
                    return False, f"HF Auth Error ({response.status_code})"

                elif response.status_code == 404:
                    print(f"      ⚠️ [HF 404] {short_name} not found — trying next model.")
                    break  # 404 = this specific model gone, try the next one

                elif response.status_code == 410:
                    # 410 = model deprecated/removed from HF Inference API.
                    # Add to session blacklist so future scenes skip it immediately.
                    # Do NOT bail the entire HF tier — next model may still work.
                    _HF_SESSION_BLACKLIST.add(model)
                    print(f"      ⚠️ [HF 410] {short_name}: deprecated — blacklisted for this run, trying next model.")
                    break  # skip to next model only

                elif response.status_code >= 500:
                    try:
                        data = response.json()
                        # ── BUG #9 FIX: int() cast on estimated_time fails when
                        # HF returns a float (e.g. 42.5) or null value. Use
                        # float() with an explicit None guard for safety.
                        raw_wait  = data.get("estimated_time")
                        wait_time = min(float(raw_wait or 13) + 2, 60)
                        print(f"      ⏳ [HF LOAD] Model booting. Waiting {wait_time:.0f}s...")
                        time.sleep(wait_time)
                        continue
                    except Exception:
                        if retry < 2:
                            _execute_jitter_backoff(retry, "HF AI")
                            continue

                elif response.status_code == 429:
                    print(f"      ⚠️ [HF 429] Rate limit on {short_name}. Backing off...")
                    if retry < 2:
                        _execute_jitter_backoff(retry, "HF AI")
                        continue
                    break  # rate limited even after retries — try next model

                else:
                    # ── CATCH-ALL: log any unexpected status so we can diagnose it ──
                    # This handles cases like HTTP 422, 451, or any future HF error
                    # codes that don't fall into the buckets above. Without this,
                    # unrecognised status codes silently fall through the retry loop.
                    try:
                        err_snippet = response.json().get("error", response.text[:120])
                    except Exception:
                        err_snippet = response.text[:120]
                    print(f"      ⚠️ [HF {response.status_code}] {short_name}: {err_snippet}")
                    if response.status_code in [401, 402, 403]:
                        print(f"      ⛔ HF auth/billing failure. Bailing entire cascade.")
                        print(f"      💡 Check HF_TOKEN and account plan (PRO required for FLUX/SDXL).")
                        return False, f"HF Auth Error ({response.status_code})"
                    break  # unknown status — try next model

            except Exception as e:
                trace = traceback.format_exc()
                print(f"🚨 [HF AI ERROR]:\n{trace}")
                # ── BUG #10 FIX: DNS/connection failures (e.g. GitHub Actions
                # runner can't resolve api-inference.huggingface.co) are NOT
                # transient per-model issues — they affect ALL models and ALL
                # retries. Retrying 3× per model × 2 models × 14 scenes wastes
                # ~10 minutes of backoff on guaranteed-to-fail requests.
                # Detect the failure class and bail the entire cascade immediately.
                err_str = str(e).lower()
                if any(x in err_str for x in ["name resolution", "getaddrinfo", "gaierror", "failed to resolve", "no address associated"]):
                    print(f"      ⛔ [HF DNS] DNS resolution failure for api-inference.huggingface.co. Bailing entire cascade.")
                    print(f"      💡 This is a network/environment issue (e.g. GitHub Actions runner DNS).")

                    return False, "HF DNS Error"
                if retry < 2:
                    _execute_jitter_backoff(retry, "HF AI")
                    continue
                break

    return False, "HF Exhausted"


def fallback_pexels_image(search_query, output_path, is_retry=False):
    safe_query = " ".join(
        [w for w in re.sub(r'[^a-zA-Z0-9\s]', '', search_query).split() if len(w) >= 2][:3]
    ) or "cinematic"
    print(f"      [Tier 3: Pexels] Searching: '{safe_query}'...")
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return False, "No Key"

    try:
        url = (
            f"https://api.pexels.com/v1/search"
            f"?query={urllib.parse.quote(safe_query)}&orientation=portrait&per_page=15"
        )
        # ── BUG #6 FIX: response status was never checked before calling .json().
        # A 429 (rate limit) or 401 (bad key) returns a JSON error body, and the
        # old code would silently treat missing 'photos' as "no results", then
        # recurse with 'cinematic aesthetic' — hitting the rate limit a second time.
        pexels_resp = requests.get(url, headers={"Authorization": api_key}, timeout=(10, 30))
        if pexels_resp.status_code == 429:
            print(f"      ⚠️ [PEXELS 429] Rate limit hit. Skipping Pexels for this scene.")
            return False, "Pexels Rate Limited"
        if pexels_resp.status_code in [401, 403]:
            print(f"      ❌ [PEXELS {pexels_resp.status_code}] Auth failure — check PEXELS_API_KEY secret.")
            return False, f"Pexels Auth Error ({pexels_resp.status_code})"
        res = pexels_resp.json()
        if res.get('photos'):
            img_data = requests.get(
                random.choice(res['photos'])['src']['large2x'], timeout=(10, 30)
            ).content
            with open(output_path, 'wb') as f:
                f.write(img_data)
            if not _validate_image(output_path):
                if not is_retry:
                    return fallback_pexels_image("cinematic aesthetic", output_path, is_retry=True)
                return False, "Invalid image data"
            return True, ""
        elif not is_retry:
            return fallback_pexels_image("cinematic aesthetic", output_path, is_retry=True)
    except Exception:
        trace = traceback.format_exc()
        print(f"🚨 [PEXELS ERROR]:\n{trace}")
        return False, "API Error"
    return False, "No images found"


def generate_offline_gradient(output_path):
    print("      🛡️ [Tier 4] Local Gradient Render...")
    try:
        image = Image.new("RGB", (1080, 1920), "#000000")
        draw  = ImageDraw.Draw(image)
        r1, g1, b1 = random.randint(10, 50),  random.randint(10, 50),  random.randint(50, 100)
        r2, g2, b2 = random.randint(0,  20),  random.randint(0,  20),  random.randint(0,  20)
        for y in range(1920):
            draw.line(
                [(0, y), (1080, y)],
                fill=(
                    int(r1 + (r2 - r1) * (y / 1920)),
                    int(g1 + (g2 - g1) * (y / 1920)),
                    int(b1 + (b2 - b1) * (y / 1920)),
                )
            )
        image.save(output_path, "JPEG", quality=90)
        return True, "Local Render"
    except Exception:
        trace = traceback.format_exc()
        print(f"🚨 [LOCAL RENDER ERROR]:\n{trace}")
        return False, "Fatal Render"


def fetch_scene_images(
    prompts_list,
    pexels_queries,
    base_filename="temp_scene",
    content_type: str = "factual",
    channel_id: str = "GLOBAL",
):
    is_fictional = (content_type or "").lower() == "fictional"
    print(
        f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scenes "
        f"[content_type={content_type.upper()}{' (ANIMATION_LED: Stock Video/Photos Banned)' if is_fictional else ''}]..."
    )

    # ── OpenMontage 6-Dimension Slideshow Risk Audit & Auto-Remedy ────────────
    audited_prompts, risk_report = audit_and_remedy_prompts(prompts_list, is_fictional=is_fictional)
    if risk_report.get("remedied"):
        print(
            f"      🎬 [OPENMONTAGE] High slideshow risk detected ({risk_report.get('initial_score', 0):.2f}). "
            f"Remedied prompts with varied camera lenses, dynamic motions, and composition depth."
        )
    else:
        print(f"      🎬 [OPENMONTAGE] Slideshow risk audit passed (score: {risk_report.get('average', 0):.2f}).")

    successful_images = []

    safe_mode    = guardian.is_safe_mode()
    test_active  = is_test_mode()
    tier1_active = not safe_mode and not test_active
    tier2_active = not safe_mode
    if test_active:
        print("🧪 [TEST MODE] Bypassing Cloudflare FLUX API (Tier 1) to conserve daily neurons. Sourcing via HuggingFace / Fallback.")
    elif safe_mode:
        print("🛡️ [SAFE MODE] API Quota critically low for this channel. Bypassing AI generation.")

    _CF_DISABLE_SIGNALS = [
        "CF Auth Error",            # BUG #3 fix: 401/403 auth/billing
        "Quota Reached",            # CF daily limit exhausted (or SIMULATE_CASCADE_TEST)
        "Missing CF Credentials",   # env vars not set
        "CF Rate Limited",          # 429 after all retries
    ]
    _HF_DISABLE_SIGNALS = [
        "HF Auth Error",            # BUG #1 fix: 401/402/403
        "HF Quota Reached",         # internal quota_manager daily limit
        "No Token",                 # HF_TOKEN env var not set
        "HF Exhausted",             # BUG #10 fix: all models failed (DNS, timeout, 5xx, etc.)
        "HF DNS Error",             # BUG #10 fix: DNS resolution failure (e.g. GitHub Actions runner)
    ]

    style_hint = "3D Pixar-style digital animation render, vibrant character lighting" if is_fictional else ""
    final_provider = "Unknown"

    for i, original_prompt in enumerate(audited_prompts):
        output_path    = f"{base_filename}_{i}.jpg"
        actual_path    = output_path
        success        = False
        current_prompt = build_cinematography_prompt(
            original_prompt,
            style_hint=style_hint,
            index=i,
            total_scenes=len(audited_prompts),
        )
        safety_retries = 0

        while True:
            if tier1_active:
                success, err = generate_cloudflare_image(current_prompt, output_path)
                if success:
                    final_provider = "Cloudflare FLUX API"
                    break
                elif "400" in err and safety_retries < 1:
                    print("      ⚠️ Tier 1 Safety Filter triggered. Rewriting prompt...")
                    current_prompt = _regenerate_safe_prompt(current_prompt)
                    safety_retries += 1
                    continue
                elif any(sig in err for sig in _CF_DISABLE_SIGNALS):
                    print(f"      🚫 [TIER 1] Permanently disabling Cloudflare for remaining scenes. Reason: {err}")
                    tier1_active = False

            if not success and tier2_active:
                success, err = generate_huggingface_cascade(current_prompt, output_path)
                if success:
                    final_provider = err
                    break
                elif "400" in err and safety_retries < 1:
                    print("      ⚠️ Tier 2 Safety Filter triggered. Rewriting prompt...")
                    current_prompt = _regenerate_safe_prompt(current_prompt)
                    safety_retries += 1
                    continue
                elif any(sig in err for sig in _HF_DISABLE_SIGNALS):
                    print(f"      🚫 [TIER 2] Permanently disabling HuggingFace for remaining scenes. Reason: {err}")
                    tier2_active = False
            break

        # ── Tier 3: Pixabay Video B-Roll (RESTRICTED: Factual Only) ──────────
        if not success:
            if not is_fictional:
                safe_query = pexels_queries[i] if i < len(pexels_queries) else original_prompt
                api_key = os.environ.get("PIXABAY_API_KEY")
                if api_key:
                    try:
                        print(f"      [Tier 3: Pixabay Video] Searching: '{safe_query[:30]}'...")
                        v_url = f"https://pixabay.com/api/videos/?key={api_key}&q={urllib.parse.quote(safe_query)}&video_type=film&orientation=vertical"
                        v_res = requests.get(v_url, timeout=10)
                        if v_res.status_code == 200 and v_res.json().get('hits'):
                            hits = v_res.json().get('hits', [])
                            banned_video_tags = {'phone', 'smartphone', 'screen', 'gaming', 'app', 'laptop', 'shopping', 'makeup', 'lipstick', 'store'}
                            selected_hit = None
                            for h in hits:
                                h_tags = [t.strip().lower() for t in h.get('tags', '').split(',')]
                                if not any(bt in h_tags for bt in banned_video_tags):
                                    selected_hit = h
                                    break

                            if selected_hit:
                                vid_url = selected_hit['videos'].get('large', {}).get('url') or selected_hit['videos'].get('medium', {}).get('url')
                                if vid_url:
                                    vid_data = requests.get(vid_url, timeout=30).content
                                    actual_path = output_path.replace('.jpg', '.mp4')
                                    with open(actual_path, 'wb') as f:
                                        f.write(vid_data)
                                    success = True
                                    final_provider = "Pixabay Video"
                            else:
                                print(f"      ⚠️ [PIXABAY] All {len(hits)} hits contained irrelevant/mismatched tags. Cascading to AI generation.")
                    except Exception as e:
                        print(f"      ⚠️ [PIXABAY] Failed: {e}")
            else:
                print("      🛡️ [ISOLATION] Bypassing Pixabay Video for fictional channel (ANIMATION_LED rule).")

        # ── Tier 4: Pollinations.ai FLUX (Universal Free AI Generation) ───────
        if not success:
            print("      [Tier 4: Pollinations.ai] Attempting FLUX endpoint...")
            try:
                style_prefix = "3D Pixar digital animation render, " if is_fictional and "pixar" not in current_prompt.lower() else ""
                safe_prompt = urllib.parse.quote(style_prefix + current_prompt + _QUALITY_SUFFIX)
                url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
                res = requests.get(url, timeout=(10, 45))
                res.raise_for_status()
                with open(output_path, 'wb') as f:
                    f.write(res.content)
                if _validate_image(output_path):
                    success = True
                    final_provider = "Pollinations.ai"
            except Exception as e:
                print(f"      ⚠️ [POLLINATIONS] Failed: {e}")

        # ── Tier 5: Pexels Stock Photos (RESTRICTED: Factual Only) ───────────
        if not success:
            if not is_fictional:
                safe_query = pexels_queries[i] if i < len(pexels_queries) else original_prompt
                success, err = fallback_pexels_image(safe_query, output_path)
                if success:
                    final_provider = "Pexels Stock"
            else:
                print("      🛡️ [ISOLATION] Bypassing Pexels Stock for fictional channel (ANIMATION_LED rule).")

        # ── Tier 6: Local Offline Gradient (Deterministic Safety Net) ─────────
        if not success:
            success, err = generate_offline_gradient(output_path)
            if success:
                final_provider = "Offline Generator"

        if success:
            # ── Vision Critic Pre-Flight Quality Audit ───────────────────────
            try:
                verdict = vision_critic.evaluate_frame(
                    actual_path,
                    prompt=current_prompt,
                    scene_text=original_prompt,
                    channel_id=channel_id
                )
                if verdict.get("approved"):
                    print(f"      🔍 [VISION CRITIC] Frame {i+1} approved (score: {verdict.get('score', 0):.1f} via {verdict.get('engine', 'unknown')}).")
                else:
                    print(
                        f"      ⚠️ [VISION CRITIC] Frame {i+1} flagged (score: {verdict.get('score', 0):.1f}). "
                        f"Remedy hint: {verdict.get('remedy_hint')}"
                    )
            except Exception as vc_err:
                logger.debug(f"Vision critic pre-flight check skipped: {vc_err}")

            successful_images.append(actual_path)
        time.sleep(2)

    # ── Log Decision to CHAI Append-Only Ledger ───────────────────────────────
    try:
        decision_log.record(
            category="VISUAL_CASCADE",
            decision="Visual scene sourcing cascade completed",
            chosen=final_provider,
            options_considered=[
                "Cloudflare FLUX API",
                "HuggingFace FLUX",
                "Pixabay Video" if not is_fictional else "Bypassed (Fictional)",
                "Pollinations.ai",
                "Pexels Stock" if not is_fictional else "Bypassed (Fictional)",
                "Offline Generator",
            ],
            channel_id=channel_id,
            extra={
                "content_type": content_type,
                "is_fictional": is_fictional,
                "total_prompts": len(prompts_list),
                "successful_scenes": len(successful_images),
                "slideshow_risk": risk_report.get("average", 0),
            },
        )
    except Exception as e:
        print(f"      ⚠️ [DECISION LOG] Failed to record visual decision: {e}")

    return successful_images, final_provider

