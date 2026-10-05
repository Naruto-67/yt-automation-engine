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
    "soap cutting grid razor ASMR",
    "kinetic sand slicing hot knife",
    "carpet cleaning foam squeegee satisfying",
    "colored pencils sharpening sander",
    "wood turning lathe chisel shavings",
    "pottery wheel clay shaping satisfying",
    "chocolate scraping curls marble spatula",
    "red jelly block slicing sharp knife",
    "honeycomb uncapping scraper golden wax",
    "wax seal stamp melting drip",
    "spool thread slicing box cutter layers",
    "play doh extrusion metal grid satisfying",
    "glitter slime scoop spoon satisfying",
    "lawn hedge trimming electric shears satisfying",
    "glass marble rolling track kinetic",
    "peeling silicone spiked mat ASMR",
    "3d printing timelapse nozzle layer",
    "thick oil paint spatula canvas sculpting",
    "ice block crushing slow motion ASMR",
    "fluid acrylic pour art colorful cells",
    "candle wax carving chisel ribbons",
    "laser rust removal clean metal beam",
    "hot wire foam cutting smooth shapes",
    "fruit slicing watermelon knife satisfying",
    "domino cascade falling smooth curve",
    "pottery glaze dipping colorful drip",
    "resin sphere polishing sandpaper lathe",
    "sand pendulum geometric drawing harmonograph",
    "bubble wrap popping satisfying slowmo"
]
# Backward-compatibility alias
SHORTS_ASMR_TAXONOMY = SHORTS_VISUAL_TAXONOMY

# Brand safety & aesthetic negative keywords (purges people, haircuts, salons, streets, buildings, latex, medical)
BANNED_STOCK_KEYWORDS: Set[str] = {
    # Inappropriate / latex / medical
    "latex", "rubber", "balloon", "medical", "surgery", "condom",
    "contraceptive", "intimate", "nude", "erotic", "blood", "flesh",
    "hospital", "doctor", "needle", "syringe", "injection", "wound",
    "fetish", "skin", "underwear", "bra", "lingerie",
    # People / faces / haircuts / lifestyle (strictly banned in BrainBlud ASMR)
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
    """Executes Stage 2: 🎬 Clip Generation with 3-Layer Anti-Duplication."""
    spec_path = os.path.join("output", "spec.json")
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spec file not found at '{spec_path}'. Run Stage 1 first.")

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    orientation = "portrait" if spec.video_type == "short" else "landscape"
    stock_mgr = StockVideoManager()
    manifest_clips = []
    used_in_current_run: Set[str] = set()

    with StageTimer(PikaStage.CLIPS, topic=spec.topic):
        print(f"🎬 [CLIPS] Sourcing stock videos for {len(spec.scenes)} scenes ({orientation})...", flush=True)

        for idx, scene in enumerate(spec.scenes):
            # For Shorts: Use the randomized ASMR & kinetic visual query assigned to this scene
            if spec.video_type == "short":
                query = scene.stock_video_query or random.choice(SHORTS_VISUAL_TAXONOMY)
            else:
                query = scene.stock_video_query or "documentary cinematic background"

            print(f"🔍 [CLIPS] Scene {scene.scene_id}: Querying '{query}' (excluded: {len(used_in_current_run)} clips)...", flush=True)
            
            clip = stock_mgr.search_video(
                query,
                orientation=orientation,
                min_duration=scene.duration_seconds,
                exclude_ids=used_in_current_run
            )
            # Resilient fallback if specific query had 0 results
            if not clip and spec.video_type == "short":
                for fb_query in ["satisfying asmr", "kinetic sand slicing", "soap carving"]:
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
