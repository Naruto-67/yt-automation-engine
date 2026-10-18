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


def test_studio_init_spec_and_recreate_scene(monkeypatch):
    """Verifies POST /api/studio/init_spec and POST /api/studio/recreate_scene work end-to-end."""
    class MockStudioLLM:
        _last_used_provider_id = "test_studio_model"
        def __init__(self):
            self.call_count = 0

        def generate_json(self, system_prompt, user_prompt, **kwargs):
            self.call_count += 1
            if "Scene 1:" in user_prompt:
                return {
                    "spoken_text": "The only part of your reflection you can lick is your tongue.",
                    "stock_video_query": "soap carving cubes ASMR"
                }
            return {
                "spoken_text": f"Grounded realization number {self.call_count} that is completely true.",
                "stock_video_query": "kinetic sand squishing satisfying"
            }

    import engine.web_studio.server as server_module
    monkeypatch.setattr(server_module, "LLMManager", MockStudioLLM)

    async def _test():
        secret_token = get_studio_secret()
        client = await _make_client()
        headers = {"X-Studio-Token": secret_token}
        try:
            # 1. Init spec
            resp = await client.post("/api/studio/init_spec", headers=headers, json={"topic": "Mind Bending Paradoxes"})
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "session" in data
            assert len(data["session"]["scenes"]) >= 3

            # 2. Recreate Scene 1 (Hook)
            resp_rec1 = await client.post("/api/studio/recreate_scene", headers=headers, json={"scene_id": 1})
            assert resp_rec1.status == 200
            data_rec1 = await resp_rec1.json()
            assert data_rec1["success"] is True

            # 3. Recreate Scene 2 (Premise)
            resp_rec2 = await client.post("/api/studio/recreate_scene", headers=headers, json={"scene_id": 2})
            assert resp_rec2.status == 200
            data_rec2 = await resp_rec2.json()
            assert data_rec2["success"] is True

            # 4. Recreate Scene 3 (Body Thought)
            resp_rec3 = await client.post("/api/studio/recreate_scene", headers=headers, json={"scene_id": 3})
            assert resp_rec3.status == 200
            data_rec3 = await resp_rec3.json()
            assert data_rec3["success"] is True

            # 5. Recreate Last Scene (BrainBlud Closer)
            total = len(data["session"]["scenes"])
            resp_rec_last = await client.post("/api/studio/recreate_scene", headers=headers, json={"scene_id": total})
            assert resp_rec_last.status == 200
            data_last = await resp_rec_last.json()
            assert data_last["success"] is True
            assert data_last["scene"]["spoken_text"].endswith((".", "!"))
        finally:
            await client.close()

    run_async(_test())


def test_github_status_and_settings_update(tmp_path, monkeypatch):
    """Verifies GitHub Actions status query and environment settings saving."""
    import engine.managers.github_actions_manager as gam
    monkeypatch.setattr(gam, "_ENV_FILE", tmp_path / ".env")

    async def _test():
        secret_token = get_studio_secret()
        client = await _make_client()
        headers = {"X-Studio-Token": secret_token}
        try:
            # 1. Status without token
            resp = await client.get("/api/github/status", headers=headers)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "github" in data

            # 2. Save settings
            resp_save = await client.post("/api/github/settings", headers=headers, json={
                "GITHUB_TOKEN": "ghp_mocktesttoken12345",
                "GEMINI_API_KEY": "AIzaSyMockKeyForTest"
            })
            assert resp_save.status == 200
            save_data = await resp_save.json()
            assert save_data["success"] is True
            assert "GITHUB_TOKEN" in save_data["result"]["keys"]

            # 3. Check status with mocked auth
            monkeypatch.setattr(gam.GitHubActionsManager, "get_auth_status", lambda self: {
                "authenticated": True,
                "user": "Naruto-67",
                "repo": "Naruto-67/yt-automation-engine",
                "message": "Connected as @Naruto-67"
            })
            resp_authed = await client.get("/api/github/status", headers=headers)
            data_authed = await resp_authed.json()
            assert data_authed["github"]["authenticated"] is True
            assert data_authed["github"]["user"] == "Naruto-67"
        finally:
            await client.close()

    run_async(_test())


def test_github_cloud_dispatch_and_runs_listing(monkeypatch):
    """Verifies workflow dispatch and runs listing routes."""
    import engine.managers.github_actions_manager as gam

    monkeypatch.setattr(gam.GitHubActionsManager, "is_configured", lambda self: True)
    monkeypatch.setattr(gam.GitHubActionsManager, "dispatch_master_pipeline", lambda self, *args, **kwargs: {
        "dispatched": True,
        "repo": "Naruto-67/yt-automation-engine",
        "workflow": "master_pipeline.yml"
    })
    monkeypatch.setattr(gam.GitHubActionsManager, "list_workflow_runs", lambda self, limit=10: [
        {"id": 123456, "status": "completed", "conclusion": "success", "event": "workflow_dispatch"}
    ])

    async def _test():
        secret_token = get_studio_secret()
        client = await _make_client()
        headers = {"X-Studio-Token": secret_token}
        try:
            # 1. Dispatch workflow
            resp_disp = await client.post("/api/github/dispatch", headers=headers, json={
                "video_type": "short",
                "test_mode": True,
                "custom_topic": "Testing Cloud Dispatch"
            })
            assert resp_disp.status == 200
            disp_data = await resp_disp.json()
            assert disp_data["success"] is True
            assert disp_data["dispatch"]["dispatched"] is True

            # 2. List runs
            resp_runs = await client.get("/api/github/runs", headers=headers)
            assert resp_runs.status == 200
            runs_data = await resp_runs.json()
            assert runs_data["success"] is True
            assert len(runs_data["runs"]) == 1
            assert runs_data["runs"][0]["id"] == 123456

            # 3. Autonomous pipeline dispatch
            resp_auto = await client.post("/api/pipeline/start_autonomous", headers=headers, json={
                "topic": "Brain Glitches"
            })
            assert resp_auto.status == 200
            auto_data = await resp_auto.json()
            assert auto_data["success"] is True
        finally:
            await client.close()

    run_async(_test())


def test_github_artifact_fetching(monkeypatch, tmp_path):
    """Verifies downloading and loading spec artifact from GitHub Actions run."""
    import engine.managers.github_actions_manager as gam

    # Mock artifacts list
    monkeypatch.setattr(gam.GitHubActionsManager, "list_run_artifacts", lambda self, run_id: [
        {"id": 999, "name": "spec-artifact", "size_in_bytes": 1024, "expired": False}
    ])

    # Mock extract
    def mock_extract(self, artifact_id, dest_dir):
        os.makedirs(dest_dir, exist_ok=True)
        spec_file = os.path.join(dest_dir, "spec.json")
        with open(spec_file, "w", encoding="utf-8") as f:
            json.dump({
                "topic": "Curiosity Facts",
                "scenes": [
                    {"scene_id": 1, "spoken_text": "Scene 1 Hook.", "stock_video_query": "space"},
                    {"scene_id": 2, "spoken_text": "Scene 2 Premise.", "stock_video_query": "clock"}
                ],
                "seo": {"title": "Curiosity Facts That Blow Minds 🤯 #shorts"}
            }, f)
        return [spec_file]

    monkeypatch.setattr(gam.GitHubActionsManager, "download_and_extract_artifact", mock_extract)

    async def _test():
        secret_token = get_studio_secret()
        client = await _make_client()
        headers = {"X-Studio-Token": secret_token}
        try:
            resp = await client.post("/api/github/runs/123456/fetch_spec", headers=headers)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "Loaded 2 scenes" in data["message"]
            assert data["session"]["topic"] == "Curiosity Facts"
            assert len(data["session"]["scenes"]) == 2
        finally:
            await client.close()

    run_async(_test())


