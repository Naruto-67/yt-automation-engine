"""
engine/managers/stock_video_manager.py — Pexels & Pixabay Stock Video Sourcing Engine (v2.0)
Replaces all AI image generation. Queries video APIs, filters aspect ratios, and provides CDN URL auto-refresh.
Includes 3-layer anti-duplication (intra-video uniqueness, persistent 30-day cooldown, and ASMR taxonomy rotation).
"""

import os
import sys
import re
import json
import time
import random
try:
    import requests
except ImportError:
    import urllib.request
    import urllib.parse
    import urllib.error

    class _RequestsShim:
        class Response:
            def __init__(self, data: bytes, status_code: int):
                self._data = data
                self.status_code = status_code
            def json(self):
                return json.loads(self._data.decode("utf-8"))
            def raise_for_status(self):
                if 400 <= self.status_code < 600:
                    raise urllib.error.HTTPError("", self.status_code, "HTTP Error", None, None)
            @property
            def content(self):
                return self._data
            def iter_content(self, chunk_size=65536):
                for i in range(0, len(self._data), chunk_size):
                    yield self._data[i:i + chunk_size]

        def get(self, url, headers=None, params=None, timeout=10, stream=False):
            if params:
                qs = urllib.parse.urlencode(params)
                url = f"{url}?{qs}" if "?" not in url else f"{url}&{qs}"
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return self.Response(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return self.Response(b"", e.code)

    requests = _RequestsShim()

from typing import Optional, List, Dict, Any, Set
from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.models import SpecOutput, ClipsManifest, ClipItem

# Reconfigure stdout/stderr on Windows console if needed
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import shutil as _shutil
_FFMPEG_AVAILABLE: bool = _shutil.which("ffmpeg") is not None


def _check_frame_brightness(url: str, min_brightness: int = 15) -> bool:
    """
    Samples the first frame of a video URL using ffmpeg and checks its mean brightness.
    Returns True if the frame is bright enough (mean pixel value >= min_brightness) or
    if ffmpeg is unavailable / the check fails (fail-open to avoid false rejects).
    """
    if not _FFMPEG_AVAILABLE:
        return True
    try:
        import subprocess
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-nostats", "-loglevel", "error",
                "-i", url,
                "-vframes", "1",
                "-vf", "scale=64:64,signalstats",
                "-f", "null", "-"
            ],
            capture_output=True, text=True, timeout=12
        )
        # ffmpeg prints "YAVG" (luma average) in stderr when signalstats filter is used
        for line in result.stderr.splitlines():
            if "YAVG" in line:
                parts = line.strip().split(":")
                if len(parts) >= 2:
                    try:
                        yavg = float(parts[-1].strip())
                        if yavg < min_brightness:
                            print(f"🌑 [STOCK FRAME] Clip too dark (YAVG={yavg:.1f} < {min_brightness}). Rejecting.", flush=True)
                            return False
                    except ValueError:
                        pass
    except Exception:
        pass
    return True


# ─── HIGH-RETENTION BRAND-SAFE ASMR & CRAFT TAXONOMY FOR SHORTS ────────────────
SHORTS_VISUAL_TAXONOMY: List[str] = [
    "soap carving cubes ASMR",
    "kinetic sand squishing satisfying",
    "carpet cleaning foam squeegee satisfying",
    "colored pencils sharpening macro",
    "wood turning lathe chisel shavings",
    "pottery wheel clay shaping satisfying",
    "thick oil paint palette knife canvas",
    "sand pendulum harmonograph geometric",
    "resin lathe turning wood polishing",
    "ice block crushing hydraulic press ASMR",
    "laser rust removal beam metal clean",
    "marble run wooden track kinetic",
    "wax seal stamp melting drip",
    "honeycomb uncapping scraper golden wax",
    "3d printing timelapse nozzle layer",
    "fluid acrylic pour art colorful cells",
    "bubble wrap popping slow motion",
    "domino cascade chain reaction smooth",
    "glitter slime scoop satisfying",
    "hot wire foam cutting smooth shapes",
    "peeling silicone spiked mat ASMR"
]
# Backward-compatibility alias
SHORTS_ASMR_TAXONOMY = SHORTS_VISUAL_TAXONOMY

# ─── TIER 1: UNIVERSAL PERMANENT BRAND SAFETY & YOUTUBE POLICY BAN ─────────────
UNIVERSAL_BANNED_KEYWORDS: Set[str] = {
    # Non-veg butchery / meat / slaughter / carcass
    "meat", "butcher", "slaughter", "carcass", "slaughterhouse", "pork", "beef", "chicken",
    "raw meat", "steak", "flesh", "blood", "bloody", "offal", "entrails",
    # Animal abuse / cruelty
    "animal abuse", "animal cruelty", "dog fight", "cock fight", "dead animal", "hunting kill",
    # Adult / NSFW / fetish / contraceptive
    "latex", "rubber", "balloon", "condom", "contraceptive", "intimate", "nude", "erotic",
    "fetish", "underwear", "bra", "lingerie", "sex", "porn",
    # Violence / weapons / self-harm
    "suicide", "self-harm", "gun", "pistol", "rifle", "weapon", "shooting", "corpse",
    # Graphic medical / surgery
    "surgery", "operation", "wound", "syringe", "needle", "injection", "hospital surgery"
}

# ─── TIER 2: TOPATO AESTHETIC NEGATIVE KEYWORDS (PURGES FOOD & LIFESTYLE) ──────
TOPATO_BANNED_KEYWORDS: Set[str] = {
    # Kitchen / food preparation / cooking / vegetables / fruits
    "kitchen", "cook", "cooking", "chef", "cutting board", "food", "vegetable", "fruit",
    "onion", "garlic", "pepper", "lemon", "orange", "meal", "dish", "recipe", "baking", "stove", "pot", "pan", "plate",
    # Haircuts / people / lifestyle
    "haircut", "barber", "barbershop", "hairdresser", "hairstyle", "salon", "hair", "fade", "shave", "trim",
    "graffiti", "mural", "spray paint", "wall art",
    "person", "people", "man", "woman", "girl", "boy", "kid", "child",
    "face", "interview", "talking", "vlog", "walking", "crowd",
    "model", "fashion", "makeup", "cosmetics", "selfie",
    # Real-world non-ASMR scenery
    "street", "city", "building", "house", "aerial", "drone", "suburb",
    "traffic", "car", "road", "pavement", "sidewalk", "highway", "asphalt", "pedestrian",
    "landscape", "sunset", "sky", "clouds",
    # Instruments / music / static gradients
    "guitar", "instrument", "musician", "concert", "singing", "music",
    "gradient", "background", "wallpaper", "abstract", "portrait"
}

BANNED_STOCK_KEYWORDS: Set[str] = UNIVERSAL_BANNED_KEYWORDS | TOPATO_BANNED_KEYWORDS


class StockVideoManager:
    """Manages searching, ranking, and refreshing stock videos from Pexels and Pixabay with deduplication."""

    REGISTRY_FILE = os.path.join("memory", "used_stock_clips.json")

    def __init__(self):
        self.pexels_key = os.environ.get("PEXELS_API_KEY")
        self.pixabay_key = os.environ.get("PIXABAY_API_KEY")
        os.makedirs("memory", exist_ok=True)

    @classmethod
    def load_registry(cls) -> Dict[str, Any]:
        """Loads the persistent registry of previously used stock video clips."""
        if not os.path.exists(cls.REGISTRY_FILE):
            return {"used_clips": {}}
        try:
            with open(cls.REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"used_clips": {}}

    @classmethod
    def save_registry(cls, data: Dict[str, Any]) -> None:
        """Saves registry data, pruning entries older than 45 days."""
        try:
            os.makedirs(os.path.dirname(cls.REGISTRY_FILE) or "data", exist_ok=True)
            now = time.time()
            cutoff = now - (45 * 86400)
            cleaned = {
                vid: meta for vid, meta in data.get("used_clips", {}).items()
                if meta.get("timestamp", 0) > cutoff
            }
            with open(cls.REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump({"used_clips": cleaned}, f, indent=2)
        except Exception as e:
            print(f"⚠️ [STOCK] Failed to save used clips registry: {e}", flush=True)

    @classmethod
    def is_clip_recent(cls, video_id: str, cooldown_days: int = 30) -> bool:
        """Checks if a video clip was used within the cooldown period."""
        registry = cls.load_registry()
        meta = registry.get("used_clips", {}).get(str(video_id))
        if not meta:
            return False
        age_days = (time.time() - meta.get("timestamp", 0)) / 86400.0
        return age_days < cooldown_days

    @classmethod
    def record_clip_usage(cls, video_id: str, provider: str, query: str) -> None:
        """Records a video clip ID in persistent history to enforce cooldown."""
        registry = cls.load_registry()
        registry.setdefault("used_clips", {})[str(video_id)] = {
            "timestamp": time.time(),
            "provider": provider,
            "query": query
        }
        cls.save_registry(registry)

    @classmethod
    def is_safe_clip(cls, metadata_text: str) -> bool:
        """Enforces strict brand-safety filter, rejecting suggestive, medical, or latex content."""
        if not metadata_text:
            return True
        meta_lower = metadata_text.lower()
        for banned in BANNED_STOCK_KEYWORDS:
            if re.search(r"\b" + re.escape(banned) + r"\b", meta_lower):
                return False
        return True

    def search_video(
        self,
        query: str,
        orientation: str = "portrait",
        min_duration: float = 3.0,
        exclude_ids: Optional[Set[str]] = None,
        retry_depth: int = 0
    ) -> Optional[ClipItem]:
        """
        Searches Pexels first, falling back to Pixabay.
        Enforces intra-video uniqueness and past 30-day cooldown via exclude_ids.
        Guarded against infinite recursion via retry_depth <= 2.
        """
        if retry_depth > 2:
            return None

        # Sanitize query against banned keywords: if query contains banned concepts (e.g. hair, street, barber), replace with safe taxonomy query
        for banned in BANNED_STOCK_KEYWORDS:
            if re.search(r"\b" + re.escape(banned) + r"\b", query, re.IGNORECASE):
                safe_choice = random.choice(SHORTS_VISUAL_TAXONOMY)
                print(f"🛡️ [STOCK SAFETY] Query '{query}' contains banned term '{banned}'. Replacing with '{safe_choice}'.", flush=True)
                query = safe_choice
                break

        exclude = set(exclude_ids) if exclude_ids else set()
        clip = None

        if self.pexels_key:
            try:
                clip = self._search_pexels(query, orientation=orientation, min_duration=min_duration, exclude_ids=exclude)
            except Exception as e:
                print(f"⚠️ [STOCK] Pexels search failed for '{query}': {e}. Falling back to Pixabay...", flush=True)

        if not clip and self.pixabay_key:
            try:
                clip = self._search_pixabay(query, orientation=orientation, exclude_ids=exclude)
            except Exception as e:
                print(f"⚠️ [STOCK] Pixabay search failed for '{query}': {e}", flush=True)

        # Fallback 1: If specific query failed, try taxonomy query
        if not clip and retry_depth < 2:
            fallback_query = "satisfying soap cutting ASMR"
            if query != fallback_query:
                print(f"🔄 [STOCK] Retrying query with ASMR fallback: '{fallback_query}'", flush=True)
                clip = self.search_video(fallback_query, orientation=orientation, min_duration=min_duration, exclude_ids=exclude, retry_depth=retry_depth + 1)

        # Fallback 2: Universal tactile ASMR craft
        if not clip and retry_depth < 2 and query != "kinetic sand slicing hot knife":
            print(f"🔄 [STOCK] Retrying with tactile ASMR craft fallback for: '{query}'", flush=True)
            clip = self.search_video("kinetic sand slicing hot knife", orientation=orientation, min_duration=min_duration, exclude_ids=exclude, retry_depth=retry_depth + 1)

        # Fallback 3: Local Curated B-Roll Vault (resilient offline fallback)
        if not clip and retry_depth == 0:
            print(f"📦 [STOCK] Online APIs yielded no safe clips for '{query}'. Invoking local vault fallback...", flush=True)
            clip = self.get_local_fallback(query=query, orientation=orientation, min_duration=min_duration, exclude_ids=exclude)

        return clip

    def get_local_fallback(
        self,
        query: str = "",
        orientation: str = "portrait",
        min_duration: float = 3.0,
        exclude_ids: Optional[Set[str]] = None
    ) -> Optional[ClipItem]:
        """
        Retrieves a brand-safe, muted B-roll clip from the local repository vault.
        Scans assets/broll_vault/ (satisfying, gaming, etc.) and assets/fallbacks/.
        Applies archetype keyword matching, intra-video uniqueness, and 30-day cooldown.
        If all candidates are in cooldown, automatically picks the least recently used clip.
        """
        import glob
        exclude = set(exclude_ids) if exclude_ids else set()

        search_dirs = [
            os.path.join("assets", "broll_vault", "satisfying"),
            os.path.join("assets", "broll_vault", "gaming"),
            os.path.join("assets", "broll_vault"),
            os.path.join("assets", "fallbacks"),
        ]

        candidate_paths = []
        seen_paths = set()
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for mp4 in glob.glob(os.path.join(sdir, "*.mp4")):
                norm = os.path.normpath(mp4)
                if norm not in seen_paths:
                    seen_paths.add(norm)
                    candidate_paths.append(norm)

        if not candidate_paths:
            print("⚠️ [STOCK LOCAL] No local clips found in broll vault or fallbacks.", flush=True)
            return None

        # Filter out intra-video excluded clips
        eligible = [
            p for p in candidate_paths
            if os.path.basename(p) not in exclude and p not in exclude and os.path.splitext(os.path.basename(p))[0] not in exclude
        ]

        if not eligible:
            print("⚠️ [STOCK LOCAL] All local clips excluded by current run; resetting intra-video filter.", flush=True)
            eligible = list(candidate_paths)

        # Keyword archetype matching
        archetype_keywords = {
            "kinetic_sand": ["sand", "kinetic"],
            "soap_cubes": ["soap"],
            "slime_floam": ["slime", "floam", "bead", "putty"],
            "honeycomb": ["honey", "wax", "comb"],
            "natural_stone": ["stone", "rock", "shale"],
            "power_wash": ["wash", "clean", "pressure", "moss"],
            "candy_craft": ["candy", "sweet", "gelato", "chocolate"],
            "jelly_slice": ["jelly", "gelatin"],
            "art_paint": ["paint", "art", "canvas", "brush", "pastel", "drawing"],
            "physics_marble": ["marble", "physics", "ball", "domino"],
            "hedge_trim": ["hedge", "bush", "lawn", "grass", "trim"],
            "bottle_stairs": ["bottle", "stair"],
            "tactile_macro": ["macro", "tactile", "slice", "press", "wire", "crush", "cut", "hydraulic", "shredder", "oddly", "satisfying"],
            "gaming": ["minecraft", "subway", "game", "gaming", "parkour"],
        }

        q_lower = (query or "").lower()
        matched_pool = []
        for arch, kws in archetype_keywords.items():
            if any(kw in q_lower for kw in kws):
                matched_pool.extend([p for p in eligible if arch in os.path.basename(p).lower()])

        # Prioritize matching archetype pool if non-empty, otherwise use all eligible clips
        pool = matched_pool if matched_pool else eligible

        # Apply 30-day cooldown
        cooldown_pool = [p for p in pool if not self.is_clip_recent(os.path.basename(p))]

        if cooldown_pool:
            chosen = random.choice(cooldown_pool)
        else:
            # Cooldown exhaustion: all candidates in pool have been used within 30 days.
            # Gracefully pick the least recently used candidate!
            registry = self.load_registry()
            used_clips = registry.get("used_clips", {})
            pool.sort(key=lambda p: used_clips.get(os.path.basename(p), {}).get("timestamp", 0))
            chosen = pool[0]
            print(f"🔄 [STOCK LOCAL] All candidates under cooldown. Selected least recently used: '{os.path.basename(chosen)}'", flush=True)

        vid_id = os.path.basename(chosen)
        width, height = (1080, 1920) if orientation == "portrait" else (1920, 1080)

        return ClipItem(
            scene_id=0,
            query=query,
            video_id=vid_id,
            download_url=chosen.replace("\\", "/"),
            provider="local",
            duration=12.0,
            width=width,
            height=height
        )


    def _search_pexels(
        self,
        query: str,
        orientation: str = "portrait",
        min_duration: float = 3.0,
        exclude_ids: Optional[Set[str]] = None,
        page: int = 1
    ) -> Optional[ClipItem]:
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        actual_page = page if page > 1 else random.randint(1, 3)
        params = {
            "query": query,
            "orientation": orientation,
            "size": "medium",
            "per_page": 15,
            "page": actual_page
        }
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        videos = data.get("videos", [])
        exclude = exclude_ids or set()
        
        # Shuffle candidates so we don't deterministically pick the same top-1 clip
        shuffled_videos = list(videos)
        random.shuffle(shuffled_videos)

        for vid in shuffled_videos:
            vid_id = str(vid.get("id"))
            # Skip if used in current video or used recently
            if vid_id in exclude or self.is_clip_recent(vid_id):
                continue

            # Brand safety check against slug, tags, URL, and creator
            clean_slug = vid.get("url", "").replace("-", " ").replace("/", " ").replace("_", " ")
            user_obj = vid.get("user")
            user_name = user_obj.get("name", "") if isinstance(user_obj, dict) else ""
            tag_list = vid.get("tags") or []
            meta_str = f"{clean_slug} {user_name} {' '.join(str(t) for t in tag_list)}"
            if not self.is_safe_clip(meta_str):
                continue

            files = vid.get("video_files", [])
            # Find best HD file
            hd_files = [f for f in files if f.get("quality") == "hd" or (f.get("height", 0) >= 1280)]
            chosen = hd_files[0] if hd_files else (files[0] if files else None)

            if chosen and chosen.get("link"):
                # 9:16 Vertical Aspect Ratio Guard: reject horizontal or square clips for portrait
                if orientation == "portrait":
                    cw = chosen.get("width", 1080)
                    ch = chosen.get("height", 1920)
                    if cw > 0 and (ch / cw) < 1.3:
                        continue
                clip_url = chosen["link"]
                # Frame-brightness inspection: reject clips that appear blank/black
                if not _check_frame_brightness(clip_url):
                    continue
                return ClipItem(
                    scene_id=0,
                    query=query,
                    video_id=vid_id,
                    download_url=clip_url,
                    provider="pexels",
                    duration=float(vid.get("duration", 5.0)),
                    width=chosen.get("width", 1080),
                    height=chosen.get("height", 1920)
                )

        # If chosen page exhausted due to deduplication, try page 1
        if actual_page != 1:
            return self._search_pexels(query, orientation=orientation, min_duration=min_duration, exclude_ids=exclude, page=1)

        return None

    def _search_pixabay(
        self,
        query: str,
        orientation: str = "portrait",
        exclude_ids: Optional[Set[str]] = None,
        page: int = 1
    ) -> Optional[ClipItem]:
        url = "https://pixabay.com/api/videos/"
        params = {
            "key": self.pixabay_key,
            "q": query,
            "per_page": 15,
            "page": page
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        hits = list(data.get("hits", []))
        random.shuffle(hits)
        exclude = exclude_ids or set()

        for hit in hits:
            hit_id = str(hit.get("id"))
            # Skip if used in current video or used recently
            if hit_id in exclude or self.is_clip_recent(hit_id):
                continue

            # Brand safety check against tags and pageURL slug
            clean_url = hit.get("pageURL", "").replace("-", " ").replace("/", " ").replace("_", " ")
            meta_str = f"{clean_url} {hit.get('tags', '')}"
            if not self.is_safe_clip(meta_str):
                continue

            vids = hit.get("videos", {})
            target = vids.get("large") or vids.get("medium") or vids.get("small")
            if target and target.get("url"):
                # 9:16 Vertical Aspect Ratio Guard: reject horizontal or square clips for portrait
                if orientation == "portrait":
                    tw = target.get("width", 1080)
                    th = target.get("height", 1920)
                    if tw > 0 and (th / tw) < 1.3:
                        continue
                clip_url = target["url"]
                # Frame-brightness inspection: reject clips that appear blank/black
                if not _check_frame_brightness(clip_url):
                    continue
                return ClipItem(
                    scene_id=0,
                    query=query,
                    video_id=hit_id,
                    download_url=clip_url,
                    provider="pixabay",
                    duration=float(hit.get("duration", 5.0)),
                    width=target.get("width", 1080),
                    height=target.get("height", 1920)
                )

        if page == 1 and len(hits) >= 5:
            return self._search_pixabay(query, orientation=orientation, exclude_ids=exclude, page=2)

        return None

    def refresh_download_url(self, provider: str, video_id: str) -> Optional[str]:
        """Auto-refreshes signed CDN download link if HTTP 403 occurs."""
        print(f"🔄 [STOCK REFRESH] Refreshing expired CDN link for {provider} ID {video_id}...", flush=True)
        try:
            if provider == "pexels" and self.pexels_key:
                url = f"https://api.pexels.com/videos/videos/{video_id}"
                headers = {"Authorization": self.pexels_key}
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    files = resp.json().get("video_files", [])
                    return files[0].get("link") if files else None
            elif provider == "pixabay" and self.pixabay_key:
                url = "https://pixabay.com/api/videos/"
                params = {"key": self.pixabay_key, "id": video_id}
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    hits = resp.json().get("hits", [])
                    if hits:
                        vids = hits[0].get("videos", {})
                        target = vids.get("large") or vids.get("medium")
                        return target.get("url") if target else None
        except Exception as e:
            print(f"⚠️ [STOCK REFRESH] Refresh failed: {e}", flush=True)
        return None


def run_clips_stage() -> None:
    """Executes Stage 2: 🎬 Clip Generation with Vault Blending and 3-Layer Anti-Duplication."""
    spec_path = os.path.join("output", "spec.json")
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spec file not found at '{spec_path}'. Run Stage 1 first.")

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    orientation = "portrait" if spec.video_type == "short" else "landscape"
    stock_mgr = StockVideoManager()
    manifest_clips = []
    used_in_current_run: Set[str] = set()

    # Load visual settings from channel_config.yaml
    full_channel_cfg = {}
    try:
        import yaml as _yaml
        with open("config/channel_config.yaml", "r", encoding="utf-8") as _f:
            full_channel_cfg = _yaml.safe_load(_f) or {}
    except Exception:
        pass
    visual_cfg = full_channel_cfg.get("visual_settings", {})
    vault_blend_count = max(0, min(len(spec.scenes), visual_cfg.get("vault_blend_count", 3)))

    # Determine anchor scene indices to blend local vault clips (hook, midpoint, loop)
    vault_indices: Set[int] = set()
    if spec.video_type == "short" and vault_blend_count > 0:
        num_s = len(spec.scenes)
        if vault_blend_count == 1:
            vault_indices = {0}
        elif vault_blend_count == 2:
            vault_indices = {0, num_s - 1}
        else:
            vault_indices = {0, num_s // 2, num_s - 1}
            step = max(1, num_s // vault_blend_count)
            for i in range(0, num_s, step):
                if len(vault_indices) < vault_blend_count:
                    vault_indices.add(i)

    with StageTimer(PikaStage.CLIPS, topic=spec.topic):
        print(f"🎬 [CLIPS] Sourcing stock videos for {len(spec.scenes)} scenes ({orientation}, blending {len(vault_indices)} vault assets)...", flush=True)

        for idx, scene in enumerate(spec.scenes):
            clip = None
            query = scene.stock_video_query or (random.choice(SHORTS_VISUAL_TAXONOMY) if spec.video_type == "short" else "documentary cinematic background")

            # 1. Local Vault Blending for anchor scenes
            if idx in vault_indices:
                clip = stock_mgr.get_local_fallback(
                    query=query,
                    orientation=orientation,
                    min_duration=scene.duration_seconds or 4.0,
                    exclude_ids=used_in_current_run
                )
                if clip:
                    print(f"💎 [VAULT BLEND] Scene {scene.scene_id}: Blended curated local clip '{clip.video_id}'", flush=True)

            # 2. Online search if not a vault-blended scene or vault returned None
            if not clip:
                print(f"🔍 [CLIPS] Scene {scene.scene_id}: Querying '{query}' (excluded: {len(used_in_current_run)} clips)...", flush=True)
                clip = stock_mgr.search_video(
                    query,
                    orientation=orientation,
                    min_duration=scene.duration_seconds,
                    exclude_ids=used_in_current_run
                )

            # Resilient fallback if specific query had 0 results
            if not clip and spec.video_type == "short":
                for fb_query in ["soap carving cubes", "kinetic sand squishing", "resin lathe turning"]:
                    clip = stock_mgr.search_video(
                        fb_query,
                        orientation=orientation,
                        min_duration=scene.duration_seconds,
                        exclude_ids=used_in_current_run
                    )
                    if clip:
                        query = fb_query
                        break

            if not clip:
                print(f"📦 [CLIPS] Online search exhausted. Sourcing from local B-roll vault for '{query}'...", flush=True)
                clip = stock_mgr.get_local_fallback(
                    query=query,
                    orientation=orientation,
                    min_duration=scene.duration_seconds,
                    exclude_ids=used_in_current_run
                )

            if not clip:
                raise RuntimeError(f"Could not find any suitable stock video or local fallback for query: '{query}'")

            clip.scene_id = scene.scene_id
            manifest_clips.append(clip)
            used_in_current_run.add(clip.video_id)
            stock_mgr.record_clip_usage(clip.video_id, clip.provider, query)

            print(f"✅ [CLIPS] Scene {scene.scene_id}: Selected unique {clip.provider.upper()} ID {clip.video_id} ({clip.duration:.1f}s)", flush=True)

        manifest = ClipsManifest(
            topic=spec.topic,
            video_type=spec.video_type,
            clips=manifest_clips
        )

        manifest_path = os.path.join("output", "clips_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=2))

        print(f"📦 [CLIPS] Saved clips manifest to '{manifest_path}' with {len(manifest_clips)} unique clips.", flush=True)
