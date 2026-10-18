"""
engine/web_studio/server.py — Private Local Web Studio & Live Timeline Engine (v1.0)

Features:
- Bound exclusively to 127.0.0.1 (Localhost only) with token/secret authentication.
- Live Timeline & Schedule Hub (view queued videos, adjust shorts_per_day & peak hours).
- Interactive Manual Studio Wizard (Script review, Recreate Scene, TTS preview, Clip reroll, Render, SEO & YouTube upload).
- WebSocket Real-Time Terminal Log Streaming.
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import asyncio
import secrets
import pathlib
import shutil
import traceback
import yaml
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set

from aiohttp import web, WSMsgType

# Core engine imports
from engine.logger import logger
from engine.models import SpecOutput, ClipsManifest, ClipItem, SceneSpec
from engine.managers.iterative_script_generator import IterativeScriptGenerator, BRAINBLUD_CLOSERS, PILLARS
from engine.managers.editorial_critic import (
    audit_and_refine_spec,
    CynicalHumanAuditor,
    PureShowerThoughtAuditor,
    SemanticDeduplicationSkill,
    HookAuditorSkill,
    LoopAuditorSkill
)
from engine.managers.voice_normalizer import VoiceNormalizer
from engine.managers.stock_video_manager import StockVideoManager, SHORTS_VISUAL_TAXONOMY
from engine.managers.youtube_manager import YouTubeManager, is_test_mode

# ─── SECURITY & AUTHENTICATION ────────────────────────────────────────────────

_STUDIO_SECRET_FILE = pathlib.Path(".studio_secret")


def get_studio_secret() -> str:
    """
    Retrieves or initializes the private studio authentication secret.
    Prioritizes STUDIO_SECRET_KEY env var, then .studio_secret file,
    otherwise creates a persistent 32-character hex token in .studio_secret.
    """
    env_token = os.getenv("STUDIO_SECRET_KEY")
    if env_token and env_token.strip():
        return env_token.strip()

    if _STUDIO_SECRET_FILE.exists():
        try:
            stored = _STUDIO_SECRET_FILE.read_text(encoding="utf-8").strip()
            if stored:
                return stored
        except Exception:
            pass

    # Generate fresh secure token
    new_token = secrets.token_hex(16)
    try:
        _STUDIO_SECRET_FILE.write_text(new_token, encoding="utf-8")
    except Exception as e:
        print(f"⚠️ [STUDIO] Could not persist .studio_secret: {e}")
    return new_token


@web.middleware
async def studio_auth_middleware(request: web.Request, handler):
    """
    Protects all private API and WebSocket endpoints against unauthorized access.
    Allows static assets and the root HTML page to load so the browser can display the login modal.
    """
    path = request.path
    secret = get_studio_secret()

    # Public paths
    if path == "/" or path.startswith("/static/"):
        response = await handler(request)
        # If token was supplied in query string, set cookie for seamless persistence
        req_token = request.query.get("token", "").strip()
        if req_token and req_token == secret:
            response.set_cookie("studio_token", secret, max_age=86400 * 30, httponly=False)
        return response

    # Public login check endpoint
    if path == "/api/auth/login":
        return await handler(request)

    # Validate token for all API and WS routes
    client_token = (
        request.headers.get("X-Studio-Token")
        or request.query.get("token")
        or request.cookies.get("studio_token")
        or ""
    ).strip()

    if not client_token or client_token != secret:
        if path.startswith("/ws/"):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "error", "message": "Unauthorized"})
            await ws.close(code=4001, message=b"Unauthorized")
            return ws
        return web.json_response({"success": False, "error": "Unauthorized: Invalid or missing studio token"}, status=401)

    return await handler(request)


# ─── REAL-TIME LOG BROADCASTER ───────────────────────────────────────────────

class LogBroadcaster:
    """
    Intercepts stdout/stderr and broadcasts formatted log lines to connected WebSockets.
    Maintains a rolling 100-line memory ring buffer for new connections.
    """
    def __init__(self, max_buffer: int = 150):
        self.max_buffer = max_buffer
        self.buffer: List[Dict[str, Any]] = []
        self.active_websockets: Set[web.WebSocketResponse] = set()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

    def write_line(self, line: str, level: str = "INFO"):
        clean_text = line.rstrip("\r\n")
        if not clean_text:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": level,
            "message": clean_text
        }
        self.buffer.append(entry)
        if len(self.buffer) > self.max_buffer:
            self.buffer.pop(0)

        # Broadcast asynchronously to all active WebSockets
        dead_ws = set()
        for ws in list(self.active_websockets):
            if ws.closed:
                dead_ws.add(ws)
                continue
            try:
                asyncio.create_task(ws.send_json({"type": "log", "data": entry}))
            except Exception:
                dead_ws.add(ws)
        self.active_websockets -= dead_ws


class _StdoutTee:
    """Tees stdout/stderr to console and log broadcaster simultaneously."""
    def __init__(self, original_stream, broadcaster: LogBroadcaster, level: str = "INFO"):
        self.original_stream = original_stream
        self.broadcaster = broadcaster
        self.level = level
        self._line_buffer = ""

    def write(self, text: str):
        self.original_stream.write(text)
        self._line_buffer += text
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            self.broadcaster.write_line(line, self.level)

    def flush(self):
        self.original_stream.flush()

    def fileno(self):
        return self.original_stream.fileno()


# ─── STUDIO SESSION STATE ────────────────────────────────────────────────────

class StudioSession:
    """
    State container for the interactive 3-stage manual video studio wizard.
    Stages:
      1. 'script_review' — Inspect & tweak scenes, recreate single thoughts, preview Kokoro TTS.
      2. 'visuals_review' — Inspect matched 9:16 clips, reroll clips per scene.
      3. 'render_preview' — HTML5 video preview with burnt captions, final SEO review, 1-click YouTube release.
    """
    def __init__(self):
        self.session_id: str = secrets.token_hex(8)
        self.stage: str = "idle"  # idle | script_review | visuals_review | render_preview | completed
        self.status: str = "ready"  # ready | generating | rendering | uploading | error
        self.error_message: Optional[str] = None
        self.topic: str = ""
        self.premise_line: str = ""
        self.scenes: List[Dict[str, Any]] = []
        self.seo: Dict[str, Any] = {}
        self.clips: List[Dict[str, Any]] = []
        self.render_path: Optional[str] = None
        self.publish_result: Optional[Dict[str, Any]] = None
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.lock = asyncio.Lock()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stage": self.stage,
            "status": self.status,
            "error_message": self.error_message,
            "topic": self.topic,
            "premise_line": self.premise_line,
            "scenes": self.scenes,
            "seo": self.seo,
            "clips": self.clips,
            "has_render": bool(self.render_path and os.path.exists(self.render_path)),
            "publish_result": self.publish_result,
            "created_at": self.created_at,
        }

    def reset(self):
        self.session_id = secrets.token_hex(8)
        self.stage = "idle"
        self.status = "ready"
        self.error_message = None
        self.topic = ""
        self.premise_line = ""
        self.scenes = []
        self.seo = {}
        self.clips = []
        self.render_path = None
        self.publish_result = None
        self.created_at = datetime.now(timezone.utc).isoformat()


# Global state
_broadcaster = LogBroadcaster()
_session = StudioSession()
_pipeline_task: Optional[asyncio.Task] = None
_pipeline_status = {
    "is_running": False,
    "current_stage": "idle",
    "topic": "",
    "start_time": 0.0,
    "error": None
}


# ─── API HANDLERS: SCHEDULE & TIMELINE ───────────────────────────────────────

async def handle_get_schedule(request: web.Request) -> web.Response:
    """Returns current upload schedule settings and scheduled YouTube videos."""
    cfg_path = pathlib.Path("config/channel_config.yaml")
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    upload_settings = cfg.get("upload_settings", {
        "shorts_per_day": 2,
        "min_spacing_hours": 6.0,
        "target_peak_windows_utc": [18, 22, 14, 1],
        "privacy": "private",
    })

    # Fetch queued YouTube uploads
    scheduled_videos = []
    yt_status = "unconfigured"
    try:
        yt = YouTubeManager()
        if yt.client_id and yt.client_secret and yt.refresh_token:
            yt_status = "connected"
            client = yt.get_client()
            if client:
                # Query scheduled uploads
                ch_resp = client.channels().list(part="contentDetails", mine=True).execute()
                uploads_playlist = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                items_resp = client.playlistItems().list(
                    part="contentDetails,snippet",
                    playlistId=uploads_playlist,
                    maxResults=15
                ).execute()

                video_ids = [item["contentDetails"]["videoId"] for item in items_resp.get("items", [])]
                if video_ids:
                    vids_resp = client.videos().list(part="snippet,status", id=",".join(video_ids)).execute()
                    now_utc = datetime.now(timezone.utc)
                    for vid in vids_resp.get("items", []):
                        status = vid.get("status", {})
                        snippet = vid.get("snippet", {})
                        pub_at = status.get("publishAt")
                        if pub_at:
                            try:
                                p_dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                                if p_dt > now_utc:
                                    scheduled_videos.append({
                                        "video_id": vid.get("id"),
                                        "title": snippet.get("title", ""),
                                        "publish_at": pub_at,
                                        "status": status.get("privacyStatus", "private"),
                                        "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url")
                                    })
                            except Exception:
                                pass
                    scheduled_videos.sort(key=lambda x: x["publish_at"])
    except Exception as e:
        yt_status = f"notice: {str(e)[:100]}"

    return web.json_response({
        "success": True,
        "config": upload_settings,
        "youtube_status": yt_status,
        "scheduled_videos": scheduled_videos,
        "server_time_utc": datetime.now(timezone.utc).isoformat()
    })


async def handle_update_schedule(request: web.Request) -> web.Response:
    """Updates shorts_per_day and peak windows in config/channel_config.yaml."""
    data = await request.json()
    cfg_path = pathlib.Path("config/channel_config.yaml")
    if not cfg_path.exists():
        return web.json_response({"success": False, "error": "channel_config.yaml not found"}, status=404)

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    upload_settings = cfg.setdefault("upload_settings", {})

    if "shorts_per_day" in data:
        spd = int(data["shorts_per_day"])
        if not (1 <= spd <= 6):
            return web.json_response({"success": False, "error": "shorts_per_day must be between 1 and 6"}, status=400)
        upload_settings["shorts_per_day"] = spd

    if "target_peak_windows_utc" in data:
        windows = [int(w) for w in data["target_peak_windows_utc"] if 0 <= int(w) <= 23]
        if not windows:
            return web.json_response({"success": False, "error": "At least 1 valid UTC peak hour (0-23) required"}, status=400)
        upload_settings["target_peak_windows_utc"] = sorted(list(set(windows)))

    if "min_spacing_hours" in data:
        spacing = float(data["min_spacing_hours"])
        if spacing >= 1.0:
            upload_settings["min_spacing_hours"] = spacing

    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

    print(f"🗓️ [STUDIO] Upload schedule updated: {upload_settings.get('shorts_per_day')} shorts/day, peak windows {upload_settings.get('target_peak_windows_utc')}")
    return web.json_response({
        "success": True,
        "message": "Schedule updated successfully",
        "config": upload_settings
    })


# ─── API HANDLERS: AUTONOMOUS PIPELINE ────────────────────────────────────────

async def _run_autonomous_pipeline_task(topic: Optional[str] = None):
    global _pipeline_status
    _pipeline_status["is_running"] = True
    _pipeline_status["start_time"] = time.time()
    _pipeline_status["topic"] = topic or "Autonomous Reddit Thought"
    _pipeline_status["current_stage"] = "spec_generation"
    _pipeline_status["error"] = None

    try:
        from engine.managers.pipeline_runner import PipelineRunner
        print(f"\n🚀 [STUDIO] Launching Autonomous TOPATO Pipeline (Topic: '{_pipeline_status['topic']}')...")
        runner = PipelineRunner()
        # Run in thread pool to avoid blocking async event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, runner.run_daily_short, topic)
        _pipeline_status["current_stage"] = "completed"
        print(f"🎉 [STUDIO] Autonomous TOPATO Pipeline completed successfully!")
    except Exception as e:
        _pipeline_status["current_stage"] = "error"
        _pipeline_status["error"] = str(e)
        print(f"❌ [STUDIO] Autonomous Pipeline failed: {e}\n{traceback.format_exc()}")
    finally:
        _pipeline_status["is_running"] = False


async def handle_start_autonomous_pipeline(request: web.Request) -> web.Response:
    """Triggers an autonomous pipeline run in the background."""
    global _pipeline_task
    if _pipeline_status["is_running"]:
        return web.json_response({"success": False, "error": "A pipeline run is already in progress"}, status=409)

    data = await request.json() if request.can_read_body else {}
    custom_topic = data.get("topic", "").strip() or None

    _pipeline_task = asyncio.create_task(_run_autonomous_pipeline_task(custom_topic))
    return web.json_response({"success": True, "message": "Autonomous pipeline started"})


async def handle_get_pipeline_status(request: web.Request) -> web.Response:
    elapsed = round(time.time() - _pipeline_status["start_time"], 1) if _pipeline_status["is_running"] else 0.0
    return web.json_response({
        "success": True,
        "status": {
            **_pipeline_status,
            "elapsed_seconds": elapsed
        }
    })


# ─── API HANDLERS: INTERACTIVE STUDIO WIZARD ─────────────────────────────────

async def handle_get_studio_session(request: web.Request) -> web.Response:
    """Returns current active studio session state."""
    async with _session.lock:
        return web.json_response({"success": True, "session": _session.to_dict()})


async def handle_init_spec(request: web.Request) -> web.Response:
    """
    Stage 1 Initiation: Generates multi-scene script chain and umbrella SEO.
    Enforces BrainBlud closers, Wall Test, and Semantic Deduplication.
    """
    data = await request.json() if request.can_read_body else {}
    topic = data.get("topic", "").strip()

    if not topic:
        # Pick from curated viral shower thoughts
        curated_path = pathlib.Path("data/curated_thoughts_and_facts.json")
        if curated_path.exists():
            try:
                with open(curated_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    items = cdata.get("shower_thoughts", []) or cdata.get("items", [])
                    if items:
                        item = random.choice(items)
                        topic = item.get("text") or item.get("thought") or "perceptual glitches"
            except Exception:
                topic = "shower thoughts that mess with your head"
        else:
            topic = "mind bending shower thoughts nobody knows"

    async with _session.lock:
        _session.reset()
        _session.topic = topic
        _session.stage = "script_review"
        _session.status = "generating"

    try:
        loop = asyncio.get_event_loop()
        generator = IterativeScriptGenerator()

        print(f"🎬 [STUDIO WIZARD] Generating 12-scene BrainBlud script chain for topic: '{topic}'...")
        scenes, seo = await loop.run_in_executor(None, generator.generate_scene_chain, topic, 12)

        # Run Editorial Critic
        scenes, seo, audit_summary = audit_and_refine_spec(scenes, seo, topic)

        async with _session.lock:
            _session.scenes = scenes
            _session.seo = seo
            _session.status = "ready"
            _session.premise_line = scenes[1].get("spoken_text", "") if len(scenes) > 1 else ""

        return web.json_response({
            "success": True,
            "message": "Script generated successfully",
            "session": _session.to_dict(),
            "audit_summary": audit_summary
        })

    except Exception as e:
        async with _session.lock:
            _session.status = "error"
            _session.error_message = str(e)
        print(f"❌ [STUDIO WIZARD] Script generation error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_update_scene(request: web.Request) -> web.Response:
    """Updates spoken text or visual query for a single scene."""
    data = await request.json()
    scene_id = int(data.get("scene_id", 0))
    new_text = data.get("spoken_text", "").strip()
    new_query = data.get("stock_video_query", "").strip()

    async with _session.lock:
        target_scene = next((s for s in _session.scenes if s.get("scene_id") == scene_id), None)
        if not target_scene:
            return web.json_response({"success": False, "error": f"Scene {scene_id} not found"}, status=404)

        if new_text:
            target_scene["spoken_text"] = new_text
            target_scene["_user_edited"] = True
            # Invalidate any cached audio preview
            target_scene.pop("audio_path", None)
            target_scene.pop("duration", None)

        if new_query:
            target_scene["stock_video_query"] = new_query

        return web.json_response({
            "success": True,
            "scene": target_scene,
            "message": f"Scene {scene_id} updated successfully"
        })


async def handle_recreate_scene(request: web.Request) -> web.Response:
    """
    Recreates a single scene:
    - Scene 1: Regenerates Hook.
    - Scene 2: Regenerates Premise Card.
    - Scene 12: Regenerates BrainBlud Closer from BRAINBLUD_CLOSERS.
    - Scenes 3-11: Regenerates single thought assigned to its pillar domain,
      checking Wall Test and Semantic Deduplication against all other scenes.
    """
    data = await request.json()
    scene_id = int(data.get("scene_id", 0))

    async with _session.lock:
        target_scene = next((s for s in _session.scenes if s.get("scene_id") == scene_id), None)
        if not target_scene:
            return web.json_response({"success": False, "error": f"Scene {scene_id} not found"}, status=404)

        total_scenes = len(_session.scenes)
        other_scenes = [s for s in _session.scenes if s.get("scene_id") != scene_id]
        used_queries = [s.get("stock_video_query") for s in other_scenes if s.get("stock_video_query")]

    loop = asyncio.get_event_loop()
    generator = IterativeScriptGenerator()

    try:
        new_scene = None
        if scene_id == 1:
            # Recreate Hook
            new_scene = await loop.run_in_executor(None, generator._generate_hook, _session.topic, used_queries)
        elif scene_id == 2:
            # Recreate Premise Card
            hook_text = _session.scenes[0].get("spoken_text", "")
            new_scene = await loop.run_in_executor(None, generator._generate_premise_card, _session.topic, hook_text, used_queries)
        elif scene_id == total_scenes:
            # Recreate BrainBlud Closer
            hook_text = _session.scenes[0].get("spoken_text", "")
            new_scene = generator._generate_brainblud_closer(
                scene_num=scene_id,
                existing_scenes=other_scenes,
                used_queries=used_queries,
                hook_text=hook_text
            )
        else:
            # Recreate Body Thought
            pillar_idx = (scene_id - 3) % len(PILLARS)
            pillar = PILLARS[pillar_idx]
            new_scene = await loop.run_in_executor(
                None,
                generator._generate_single_pillar_scene,
                scene_id,
                pillar,
                _session.topic,
                other_scenes,
                used_queries
            )

        async with _session.lock:
            # Update target scene in place
            target_scene["spoken_text"] = new_scene["spoken_text"]
            target_scene["stock_video_query"] = new_scene["stock_video_query"]
            target_scene["_recreated"] = True
            target_scene.pop("audio_path", None)
            target_scene.pop("duration", None)

        print(f"✨ [STUDIO] Recreated Scene {scene_id}: '{target_scene['spoken_text'][:60]}...'")
        return web.json_response({
            "success": True,
            "scene": target_scene,
            "message": f"Scene {scene_id} recreated successfully"
        })

    except Exception as e:
        print(f"❌ [STUDIO] Failed to recreate scene {scene_id}: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_preview_tts(request: web.Request) -> web.Response:
    """Synthesizes Kokoro audio snippet for a single scene and returns playable URL."""
    data = await request.json()
    scene_id = int(data.get("scene_id", 0))

    async with _session.lock:
        target_scene = next((s for s in _session.scenes if s.get("scene_id") == scene_id), None)
        if not target_scene:
            return web.json_response({"success": False, "error": f"Scene {scene_id} not found"}, status=404)
        spoken_text = target_scene.get("spoken_text", "")

    preview_dir = pathlib.Path("output/studio_previews")
    preview_dir.mkdir(parents=True, exist_ok=True)
    out_audio = preview_dir / f"scene_{scene_id}.wav"

    try:
        norm_text = VoiceNormalizer.normalize_text(spoken_text)
        is_final = (scene_id == len(_session.scenes))
        if is_final:
            norm_text = VoiceNormalizer.enforce_terminal_silence(norm_text)

        dur, words = await VoiceNormalizer.synthesize_with_word_boundaries(
            phonetic_text=norm_text,
            output_audio_path=str(out_audio),
            voice="am_adam",
            speed=1.0
        )

        async with _session.lock:
            target_scene["duration"] = dur
            target_scene["audio_path"] = str(out_audio)

        return web.json_response({
            "success": True,
            "duration": dur,
            "audio_url": f"/api/studio/audio/scene_{scene_id}.wav?t={int(time.time() * 1000)}"
        })
    except Exception as e:
        print(f"❌ [STUDIO] TTS preview failed: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_get_audio_file(request: web.Request) -> web.Response:
    """Serves synthesized audio wav for inline audio preview player."""
    filename = request.match_info.get("filename", "")
    safe_name = pathlib.Path(filename).name
    file_path = pathlib.Path("output/studio_previews") / safe_name
    if not file_path.exists():
        return web.Response(status=404, text="Audio file not found")
    return web.FileResponse(file_path)


async def handle_approve_script(request: web.Request) -> web.Response:
    """
    Approves Stage 1 and advances to Stage 2 (Visuals Review).
    Matches 9:16 background stock clips for all scenes using StockVideoManager.
    """
    async with _session.lock:
        if not _session.scenes:
            return web.json_response({"success": False, "error": "No scenes in session to approve"}, status=400)
        _session.stage = "visuals_review"
        _session.status = "generating"

    loop = asyncio.get_event_loop()

    def _source_clips():
        svm = StockVideoManager()
        clips = []
        used_ids = set()
        preview_dir = pathlib.Path("output/studio_previews")
        preview_dir.mkdir(parents=True, exist_ok=True)

        for scene in _session.scenes:
            sid = scene["scene_id"]
            query = scene.get("stock_video_query", "soap carving ASMR")
            clip_item = svm.search_video(
                query=query,
                orientation="portrait",
                min_duration=3.0,
                exclude_ids=used_ids
            )
            if not clip_item:
                clip_item = svm.get_local_fallback(query=query, orientation="portrait", exclude_ids=used_ids)

            clip_id = clip_item.id if clip_item else f"fallback_{sid}"
            used_ids.add(clip_id)

            # Copy or reference local clip for preview
            local_preview = preview_dir / f"clip_{sid}.mp4"
            if clip_item and clip_item.file_path and os.path.exists(clip_item.file_path):
                try:
                    shutil.copyfile(clip_item.file_path, local_preview)
                except Exception:
                    pass

            clips.append({
                "scene_id": sid,
                "clip_id": clip_id,
                "query": query,
                "source": getattr(clip_item, "source", "vault") if clip_item else "vault",
                "file_path": str(local_preview) if local_preview.exists() else getattr(clip_item, "file_path", ""),
                "has_preview": local_preview.exists()
            })
        return clips

    try:
        clips = await loop.run_in_executor(None, _source_clips)
        async with _session.lock:
            _session.clips = clips
            _session.status = "ready"

        return web.json_response({
            "success": True,
            "message": "Visuals matched successfully",
            "session": _session.to_dict()
        })
    except Exception as e:
        async with _session.lock:
            _session.status = "error"
            _session.error_message = str(e)
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_reroll_clip(request: web.Request) -> web.Response:
    """Rerolls a single visual clip for a scene using StockVideoManager."""
    data = await request.json()
    scene_id = int(data.get("scene_id", 0))
    custom_query = data.get("custom_query", "").strip()

    async with _session.lock:
        clip_entry = next((c for c in _session.clips if c["scene_id"] == scene_id), None)
        scene_entry = next((s for s in _session.scenes if s["scene_id"] == scene_id), None)
        if not clip_entry:
            return web.json_response({"success": False, "error": f"Clip for scene {scene_id} not found"}, status=404)

        query = custom_query or scene_entry.get("stock_video_query") or "satisfying ASMR"
        exclude_ids = {c["clip_id"] for c in _session.clips}

    loop = asyncio.get_event_loop()

    def _fetch_alt():
        svm = StockVideoManager()
        alt = svm.search_video(query=query, orientation="portrait", min_duration=3.0, exclude_ids=exclude_ids)
        if not alt:
            alt = svm.get_local_fallback(query=query, orientation="portrait", exclude_ids=exclude_ids)
        return alt

    try:
        alt_clip = await loop.run_in_executor(None, _fetch_alt)
        preview_dir = pathlib.Path("output/studio_previews")
        local_preview = preview_dir / f"clip_{scene_id}.mp4"

        if alt_clip and alt_clip.file_path and os.path.exists(alt_clip.file_path):
            shutil.copyfile(alt_clip.file_path, local_preview)

        async with _session.lock:
            clip_entry["clip_id"] = alt_clip.id if alt_clip else f"reroll_{scene_id}_{int(time.time())}"
            clip_entry["query"] = query
            clip_entry["source"] = getattr(alt_clip, "source", "vault") if alt_clip else "vault"
            clip_entry["file_path"] = str(local_preview) if local_preview.exists() else (alt_clip.file_path if alt_clip else "")
            clip_entry["has_preview"] = local_preview.exists()

        return web.json_response({
            "success": True,
            "message": f"Clip {scene_id} rerolled successfully",
            "clip": clip_entry
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_get_clip_video(request: web.Request) -> web.Response:
    """Streams preview MP4 clip for inline video player."""
    scene_id = request.match_info.get("scene_id", "")
    preview_path = pathlib.Path("output/studio_previews") / f"clip_{scene_id}.mp4"
    if not preview_path.exists():
        return web.Response(status=404, text="Clip preview not found")
    return web.FileResponse(preview_path)


async def handle_approve_visuals_and_render(request: web.Request) -> web.Response:
    """
    Approves Stage 2 and triggers Stage 3 (Render Short).
    Generates audio for any missing scenes, builds spec.json and clips_manifest.json,
    and invokes the FFmpeg render engine.
    """
    async with _session.lock:
        if not _session.scenes or not _session.clips:
            return web.json_response({"success": False, "error": "Incomplete session data for render"}, status=400)
        _session.stage = "render_preview"
        _session.status = "rendering"

    loop = asyncio.get_event_loop()

    def _render():
        # 1. Synthesize audio for all scenes
        out_dir = pathlib.Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        rendered_scenes = []

        for i, sc in enumerate(_session.scenes):
            sid = sc["scene_id"]
            audio_path = os.path.join("output", f"audio_scene_{sid}.wav")
            norm_text = VoiceNormalizer.normalize_text(sc["spoken_text"])
            if i == len(_session.scenes) - 1:
                norm_text = VoiceNormalizer.enforce_terminal_silence(norm_text)

            dur, words = asyncio.run(VoiceNormalizer.synthesize_with_word_boundaries(
                phonetic_text=norm_text,
                output_audio_path=audio_path,
                voice="am_adam",
                speed=1.0
            ))

            rendered_scenes.append(SceneSpec(
                scene_id=sid,
                spoken_text=sc["spoken_text"],
                stock_video_query=sc["stock_video_query"],
                audio_path=audio_path,
                duration=dur,
                word_timestamps=words
            ))

        # 2. Build SpecOutput and write output/spec.json
        spec = SpecOutput(
            topic=_session.topic,
            video_type="short",
            scenes=rendered_scenes,
            seo=_session.seo
        )
        spec_file = os.path.join("output", "spec.json")
        with open(spec_file, "w", encoding="utf-8") as f:
            f.write(spec.model_dump_json(indent=2))

        # 3. Build ClipsManifest and write output/clips_manifest.json
        manifest_clips = []
        for cl in _session.clips:
            sid = cl["scene_id"]
            target_scene = next((s for s in rendered_scenes if s.scene_id == sid), None)
            dur = target_scene.duration if target_scene else 3.5
            manifest_clips.append(ClipItem(
                scene_id=sid,
                file_path=cl.get("file_path", ""),
                duration=dur,
                query=cl.get("query", ""),
                id=cl.get("clip_id", f"clip_{sid}")
            ))

        manifest = ClipsManifest(clips=manifest_clips)
        manifest_file = os.path.join("output", "clips_manifest.json")
        with open(manifest_file, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=2))

        # 4. Invoke FFmpeg render engine
        from scripts.render_video import render_video_ffmpeg
        with open("config/channel_config.yaml", "r", encoding="utf-8") as cf:
            full_cfg = yaml.safe_load(cf) or {}
            channel_cfg = full_cfg.get("channel", {})
            if "caption_settings" in full_cfg:
                channel_cfg["caption_settings"] = full_cfg["caption_settings"]
            if "branding" in full_cfg:
                channel_cfg["branding"] = full_cfg["branding"]

        with open("config/settings.yaml", "r", encoding="utf-8") as sf:
            settings_cfg = yaml.safe_load(sf)

        final_out = os.path.join("output", "final_render.mp4")
        render_video_ffmpeg(
            spec=spec,
            clips_manifest=manifest,
            output_video_path=final_out,
            channel_cfg=channel_cfg,
            settings_cfg=settings_cfg
        )
        return final_out

    try:
        render_path = await loop.run_in_executor(None, _render)
        async with _session.lock:
            _session.render_path = render_path
            _session.status = "ready"

        return web.json_response({
            "success": True,
            "message": "Render completed successfully",
            "render_url": f"/api/studio/preview_render?t={int(time.time() * 1000)}",
            "seo": _session.seo
        })
    except Exception as e:
        async with _session.lock:
            _session.status = "error"
            _session.error_message = str(e)
        print(f"❌ [STUDIO] Video rendering error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_get_render_video(request: web.Request) -> web.Response:
    """Streams rendered MP4 video with HTTP Range request support."""
    render_file = pathlib.Path("output/final_render.mp4")
    if not render_file.exists():
        return web.Response(status=404, text="Rendered video not found")
    return web.FileResponse(render_file)


async def handle_approve_upload(request: web.Request) -> web.Response:
    """
    Stage 3 Final Release: Uploads and schedules the approved Short to YouTube.
    Accepts customized SEO metadata (Title, Description, Tags, Pinned Comment).
    """
    data = await request.json()
    custom_title = data.get("title", "").strip()
    custom_desc = data.get("description", "").strip()
    custom_tags = data.get("tags", [])
    pinned_comment = data.get("pinned_comment", "").strip()

    async with _session.lock:
        if not _session.render_path or not os.path.exists(_session.render_path):
            return web.json_response({"success": False, "error": "Final render does not exist. Please render first."}, status=400)
        _session.status = "uploading"

    loop = asyncio.get_event_loop()

    def _upload():
        yt = YouTubeManager()
        video_path = _session.render_path
        title = custom_title or _session.seo.get("title", "Shower Thoughts That Blow Minds 🤯 #shorts")
        desc = custom_desc or _session.seo.get("description", "")
        tags = custom_tags or _session.seo.get("tags", [])

        # Load upload config
        with open("config/channel_config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        upload_cfg = cfg.get("upload_settings", {})

        result = yt.upload_video(
            video_path=video_path,
            title=title,
            description=desc,
            tags=tags,
            privacy_status=upload_cfg.get("privacy", "private"),
            schedule_time=None,  # Automatically calculates optimal anti-cannibalized slot
            video_type="short",
            category_id=upload_cfg.get("category_id", "24"),
            default_language=upload_cfg.get("default_language", "en-US"),
            default_audio_language=upload_cfg.get("default_audio_language", "en-US"),
            contains_synthetic_media=upload_cfg.get("contains_synthetic_media", False),
            notify_subscribers=upload_cfg.get("notify_subscribers_shorts", False),
            public_stats_viewable=upload_cfg.get("public_stats_viewable_shorts", False)
        )

        vid_id = result.get("video_id")
        if vid_id and pinned_comment:
            yt.post_creator_comment(vid_id, pinned_comment)

        return result

    try:
        pub_result = await loop.run_in_executor(None, _upload)
        async with _session.lock:
            _session.stage = "completed"
            _session.status = "ready"
            _session.publish_result = pub_result

        return web.json_response({
            "success": True,
            "message": "Video successfully uploaded and scheduled on YouTube!",
            "result": pub_result
        })
    except Exception as e:
        async with _session.lock:
            _session.status = "error"
            _session.error_message = str(e)
        print(f"❌ [STUDIO] YouTube upload failed: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_reject_studio(request: web.Request) -> web.Response:
    """Discards active wizard session and resets to empty state."""
    async with _session.lock:
        _session.reset()
    return web.json_response({"success": True, "message": "Session reset successfully"})


# ─── WEBSOCKET LOGS HANDLER ──────────────────────────────────────────────────

async def handle_ws_logs(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint streaming live terminal logs to browser drawer."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _broadcaster.active_websockets.add(ws)

    try:
        # Send backlog history on connect
        for entry in _broadcaster.buffer:
            await ws.send_json({"type": "log", "data": entry})

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("action") == "ping":
                    await ws.send_json({"type": "pong"})
            elif msg.type == WSMsgType.ERROR:
                print(f"WS error: {ws.exception()}")
    finally:
        _broadcaster.active_websockets.discard(ws)
    return ws


# ─── STATIC HTML PAGE HANDLER ────────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    """Serves index.html single page app."""
    static_file = pathlib.Path(__file__).parent / "static" / "index.html"
    if not static_file.exists():
        return web.Response(text="<h1>TOPATO Studio index.html missing</h1>", content_type="text/html")
    return web.FileResponse(static_file)


# ─── APP FACTORY & LAUNCHER ──────────────────────────────────────────────────

def create_studio_app() -> web.Application:
    """Creates configured aiohttp Application with auth middleware and routes."""
    app = web.Application(middlewares=[studio_auth_middleware])

    # Hook stdout & stderr tee to capture all engine prints in live WebSocket
    sys.stdout = _StdoutTee(sys.stdout, _broadcaster, "INFO")
    sys.stderr = _StdoutTee(sys.stderr, _broadcaster, "ERROR")

    async def _auth_verify(r):
        return web.json_response({"success": True, "valid": True})

    async def _auth_login(r):
        return web.json_response({"success": True})

    # API routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/auth/verify", _auth_verify)
    app.router.add_post("/api/auth/login", _auth_login)

    # Schedule
    app.router.add_get("/api/schedule", handle_get_schedule)
    app.router.add_post("/api/schedule/update", handle_update_schedule)

    # Autonomous Pipeline
    app.router.add_post("/api/pipeline/start_autonomous", handle_start_autonomous_pipeline)
    app.router.add_get("/api/pipeline/status", handle_get_pipeline_status)

    # Interactive Studio Wizard
    app.router.add_get("/api/studio/session", handle_get_studio_session)
    app.router.add_post("/api/studio/init_spec", handle_init_spec)
    app.router.add_post("/api/studio/update_scene", handle_update_scene)
    app.router.add_post("/api/studio/recreate_scene", handle_recreate_scene)
    app.router.add_post("/api/studio/preview_tts", handle_preview_tts)
    app.router.add_get("/api/studio/audio/{filename}", handle_get_audio_file)
    app.router.add_post("/api/studio/approve_script", handle_approve_script)
    app.router.add_post("/api/studio/reroll_clip", handle_reroll_clip)
    app.router.add_get("/api/studio/clip_video/{scene_id}", handle_get_clip_video)
    app.router.add_post("/api/studio/approve_visuals_and_render", handle_approve_visuals_and_render)
    app.router.add_get("/api/studio/preview_render", handle_get_render_video)
    app.router.add_post("/api/studio/approve_upload", handle_approve_upload)
    app.router.add_post("/api/studio/reject", handle_reject_studio)

    # Real-Time Log WebSocket
    app.router.add_get("/ws/logs", handle_ws_logs)

    # Static assets
    static_dir = pathlib.Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.router.add_static("/static/", path=str(static_dir), name="static")

    return app


def run_studio_server(host: str = "127.0.0.1", port: int = 8765):
    """Binds strictly to localhost and launches the aiohttp web server."""
    secret = get_studio_secret()
    print("=" * 72)
    print("🔒 TOPATO PRIVATE STUDIO — LOCALHOST ONLY")
    print(f"📍 URL: http://{host}:{port}/?token={secret}")
    print("🛡️  Auth: Token-protected. Zero external or local-network access.")
    print("=" * 72)
    app = create_studio_app()
    web.run_app(app, host=host, port=port, print=None)
