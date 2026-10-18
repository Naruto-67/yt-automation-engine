"""
tests/test_web_studio.py — Unit and Integration Tests for Private Web Studio
Using native aiohttp.test_utils TestServer and TestClient with asyncio.run.
"""

import os
import json
import asyncio
import pytest
from aiohttp.test_utils import TestServer, TestClient

from engine.web_studio.server import create_studio_app, get_studio_secret, _session


def run_async(coro):
    """Runs an async test coroutine with a clean event loop."""
    return asyncio.run(coro)


async def _make_client():
    app = create_studio_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


def test_auth_blocks_unauthorized_requests():
    async def _test():
        client = await _make_client()
        try:
            # 1. No token -> 401
            resp = await client.get("/api/schedule")
            assert resp.status == 401
            data = await resp.json()
            assert data["success"] is False
            assert "Unauthorized" in data["error"]

            # 2. Wrong token -> 401
            resp_wrong = await client.get("/api/schedule", headers={"X-Studio-Token": "invalid_token_12345"})
            assert resp_wrong.status == 401
        finally:
            await client.close()

    run_async(_test())


def test_auth_allows_authorized_requests():
    async def _test():
        secret_token = get_studio_secret()
        client = await _make_client()
        try:
            # Valid token via header
            resp = await client.get("/api/schedule", headers={"X-Studio-Token": secret_token})
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "config" in data
            assert "shorts_per_day" in data["config"]

            # Valid token via query param
            resp_param = await client.get(f"/api/schedule?token={secret_token}")
            assert resp_param.status == 200
        finally:
            await client.close()

    run_async(_test())


def test_public_index_and_static_assets_serve():
    async def _test():
        client = await _make_client()
        try:
            # Root index is accessible without auth so browser can render UI & token prompt
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "TOPATO STUDIO" in text
        finally:
            await client.close()

    run_async(_test())


def test_schedule_update_and_bounds_checking():
    async def _test():
        cfg_path = "config/channel_config.yaml"
        original_content = None
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                original_content = f.read()

        secret_token = get_studio_secret()
        client = await _make_client()
        headers = {"X-Studio-Token": secret_token}
        try:
            # Invalid shorts_per_day (>6)
            resp_bad = await client.post("/api/schedule/update", headers=headers, json={"shorts_per_day": 10})
            assert resp_bad.status == 400

            # Valid shorts_per_day
            resp_good = await client.post("/api/schedule/update", headers=headers, json={
                "shorts_per_day": 3,
                "target_peak_windows_utc": [14, 18, 22]
            })
            assert resp_good.status == 200
            data = await resp_good.json()
            assert data["success"] is True
            assert data["config"]["shorts_per_day"] == 3
        finally:
            await client.close()
            if original_content is not None:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(original_content)

    run_async(_test())


def test_studio_session_lifecycle():
    async def _test():
        secret_token = get_studio_secret()
        client = await _make_client()
        headers = {"X-Studio-Token": secret_token}
        try:
            # 1. Fetch initial session
            resp = await client.get("/api/studio/session", headers=headers)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "session" in data

            # 2. Inject mock scenes for testing scene update
            async with _session.lock:
                _session.scenes = [
                    {"scene_id": 1, "spoken_text": "Scene 1 Hook text.", "stock_video_query": "soap carving"},
                    {"scene_id": 2, "spoken_text": "Scene 2 Premise text.", "stock_video_query": "kinetic sand"}
                ]

            # 3. Update scene 1 text
            resp_update = await client.post("/api/studio/update_scene", headers=headers, json={
                "scene_id": 1,
                "spoken_text": "Updated Scene 1 Hook text here.",
                "stock_video_query": "sand slicing"
            })
            assert resp_update.status == 200
            up_data = await resp_update.json()
            assert up_data["success"] is True
            assert up_data["scene"]["spoken_text"] == "Updated Scene 1 Hook text here."

            # 4. Reject and reset
            resp_reset = await client.post("/api/studio/reject", headers=headers)
            assert resp_reset.status == 200
            async with _session.lock:
                assert len(_session.scenes) == 0
        finally:
            await client.close()

    run_async(_test())
