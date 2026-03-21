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
from PIL import Image, ImageDraw
from scripts.quota_manager import quota_manager
from engine.guardian import guardian

# ── BUG #8 FIX: SIMULATE_CASCADE_TEST was hardcoded False — never activated
# even in TEST_MODE. Now reads from the same TEST_MODE env var used everywhere
# else. In test runs this skips real CF/HF calls, saving quota.
SIMULATE_CASCADE_TEST = os.environ.get("TEST_MODE", "false").lower() == "true"

_HF_MODELS_CACHE = []

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
        url = "https://huggingface.co/api/models?pipeline_tag=text-to-image&sort=trending&limit=20"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            models_data = res.json()
            candidates  = [m['id'] for m in models_data]

            def _score_hf(name):
                s = 0
                n = name.lower()
                if 'flux'         in n: s += 50
                if 'schnell'      in n: s += 30
                if 'stable-diffusion' in n: s += 20
                if 'turbo'        in n or 'lightning' in n: s += 15
                if 'lora'         in n or 'controlnet' in n or 'adapter' in n or 'ip-adapter' in n: s -= 100
                return s

            valid_models = [m for m in candidates if _score_hf(m) > 0]
            valid_models.sort(key=_score_hf, reverse=True)

            if valid_models:
                # Only cache on successful discovery so stale fallback list
                # is never locked in if the API later becomes available.
                _HF_MODELS_CACHE = valid_models[:4]
                print(f"✅ [HF] Model cascade dynamically updated: {_HF_MODELS_CACHE}")
                return _HF_MODELS_CACHE

    except Exception:
        trace = traceback.format_exc()
        print(f"⚠️ [HF] Discovery failed:\n{trace}")

    # Do NOT set _HF_MODELS_CACHE here — keep it empty so next run retries discovery.
    # ── BUG #5 NOTE: These fallbacks are also PRO-tier on the current HF free
    # plan. If 403s persist after upgrading, swap in smaller open-weight models.
    return ["black-forest-labs/FLUX.1-schnell", "stabilityai/stable-diffusion-xl-base-1.0"]


def generate_cloudflare_image(prompt, output_path):
    print("      [Tier 1: Cloudflare AI] Attempting Official FLUX...")
    if SIMULATE_CASCADE_TEST or quota_manager.is_provider_exhausted("cloudflare"):
        return False, "Quota Reached"

    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token  = os.environ.get("CF_API_TOKEN")
    if not account_id or not api_token:
        return False, "Missing CF Credentials"

    url     = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell"
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
        short_name = model.split('/')[-1]
        print(f"      -> Routing to {short_name}...")
        if SIMULATE_CASCADE_TEST and "FLUX" in model:
            continue

        url = f"https://api-inference.huggingface.co/models/{model}"

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

            except Exception:
                trace = traceback.format_exc()
                print(f"🚨 [HF AI ERROR]:\n{trace}")
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


def fetch_scene_images(prompts_list, pexels_queries, base_filename="temp_scene"):
    print(f"🖼️ [VISUALS] Sourcing {len(prompts_list)} scenes...")
    successful_images = []

    safe_mode    = guardian.is_safe_mode()
    tier1_active = not safe_mode
    tier2_active = not safe_mode
    if safe_mode:
        print("🛡️ [SAFE MODE] API Quota critically low for this channel. Bypassing AI generation.")

    # ── BUG #2 FIX: The original disable check only matched "401"/"402"/"403"
    # fragments. But CF quota exhaustion returns "Quota Reached" and missing
    # credentials returns "Missing CF Credentials" — neither matched. This caused
    # both tiers to be retried for EVERY scene even after a definitive failure,
    # wasting ~200ms × N scenes on guaranteed-to-fail requests.
    # Now all permanent failure signals are listed explicitly per tier.
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
    ]

    final_provider = "Unknown"
    for i, original_prompt in enumerate(prompts_list):
        output_path    = f"{base_filename}_{i}.jpg"
        success        = False
        current_prompt = original_prompt
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

        if not success:
            # Guard against IndexError when pexels_queries is shorter than prompts_list
            safe_query = pexels_queries[i] if i < len(pexels_queries) else original_prompt
            success, err = fallback_pexels_image(safe_query, output_path)
            if success:
                final_provider = "Pexels Stock"

        if not success:
            success, err = generate_offline_gradient(output_path)
            if success:
                final_provider = "Offline Generator"

        if success:
            successful_images.append(output_path)
        time.sleep(2)

    return successful_images, final_provider
