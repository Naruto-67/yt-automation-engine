"""
engine/managers/github_actions_manager.py — GitHub Actions Command-and-Control Bridge (v1.0)

Enables the Private Web Studio to talk directly to GitHub Actions:
1. Dispatch workflow runs (master_pipeline.yml) with custom inputs.
2. Monitor live status, step execution, and conclusions of active GitHub Action runs.
3. Fetch and download workflow artifacts (rendered video, thumbnail, spec).
4. Persist and reload GitHub & LLM keys into a local .env file.
"""

from __future__ import annotations

import os
import io
import json
import zipfile
import pathlib
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

_DEFAULT_REPO = "Naruto-67/yt-automation-engine"
_ENV_FILE = pathlib.Path(".env")


def get_github_repo() -> str:
    """Returns the configured GitHub repository 'owner/repo'."""
    return os.environ.get("GITHUB_REPOSITORY", _DEFAULT_REPO).strip()


def get_github_token() -> str:
    """
    Retrieves GitHub token in priority order:
    1. GITHUB_TOKEN environment variable
    2. GH_PAT environment variable
    3. Stored in .env file
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT") or ""
    if token and token.strip():
        return token.strip()

    if _ENV_FILE.exists():
        try:
            for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k in ("GITHUB_TOKEN", "GH_PAT") and v:
                    return v
        except Exception:
            pass

    # 3. Auto-discover from native Git Credential Manager (zero key saving required)
    try:
        import subprocess
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            text=True,
            capture_output=True,
            timeout=3.0
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    git_token = line.split("=", 1)[1].strip()
                    if git_token:
                        return git_token
    except Exception:
        pass

    return ""


def save_env_settings(updates: Dict[str, str]) -> Dict[str, Any]:
    """
    Saves environment variables to local .env and updates current process os.environ.
    Masks secrets in return dictionary.
    """
    current_lines = []
    if _ENV_FILE.exists():
        try:
            current_lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            current_lines = []

    env_dict: Dict[str, str] = {}
    for line in current_lines:
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("#") or "=" not in line_clean:
            continue
        k, v = line_clean.split("=", 1)
        env_dict[k.strip()] = v.strip().strip("'\"")

    # Apply updates
    for k, v in updates.items():
        k = k.strip()
        v = v.strip()
        if v:
            env_dict[k] = v
            os.environ[k] = v
        elif k in env_dict:
            # Empty value -> remove
            env_dict.pop(k, None)
            os.environ.pop(k, None)

    # Write back to .env
    lines_to_write = [f"{k}={v}" for k, v in sorted(env_dict.items())]
    _ENV_FILE.write_text("\n".join(lines_to_write) + "\n", encoding="utf-8")

    # Return masked summary
    masked = {}
    for k, v in env_dict.items():
        if len(v) > 8:
            masked[k] = f"{v[:4]}...{v[-4:]}"
        else:
            masked[k] = "***"
    return {"saved": True, "keys": list(env_dict.keys()), "masked": masked}


class GitHubActionsManager:
    """Interacts with GitHub REST API for workflows, runs, and artifacts."""

    def __init__(self, token: Optional[str] = None, repo: Optional[str] = None):
        self.token = token or get_github_token()
        self.repo = repo or get_github_repo()
        self.base_url = "https://api.github.com"

    def is_configured(self) -> bool:
        return bool(self.token)

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Any:
        url = f"{self.base_url}{endpoint}" if endpoint.startswith("/") else endpoint
        req_headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "TOPATO-Private-Studio/2.1",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if self.token:
            req_headers["Authorization"] = f"Bearer {self.token}"
        if headers:
            req_headers.update(headers)

        payload = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                resp_data = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(resp_data.decode("utf-8"))
                return resp_data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message", err_body)
            except Exception:
                msg = err_body
            raise RuntimeError(f"GitHub API HTTP {e.code}: {msg}")
        except Exception as e:
            raise RuntimeError(f"GitHub API Error: {e}")

    def get_auth_status(self) -> Dict[str, Any]:
        """Validates current token against GitHub /user endpoint."""
        if not self.token:
            return {
                "authenticated": False,
                "repo": self.repo,
                "message": "GitHub Personal Access Token (PAT) not configured."
            }
        try:
            user_data = self._request("/user")
            return {
                "authenticated": True,
                "user": user_data.get("login"),
                "repo": self.repo,
                "message": f"Connected as @{user_data.get('login')}"
            }
        except Exception as e:
            return {
                "authenticated": False,
                "repo": self.repo,
                "error": str(e),
                "message": f"Authentication check failed: {e}"
            }

    def dispatch_master_pipeline(
        self,
        video_type: str = "short",
        test_mode: bool = False,
        custom_topic: str = "",
        ref: str = "main"
    ) -> Dict[str, Any]:
        """
        Triggers workflow_dispatch on .github/workflows/master_pipeline.yml.
        All execution happens in the cloud on GitHub Actions runners.
        """
        if not self.token:
            raise RuntimeError("Cannot dispatch: GitHub Personal Access Token (PAT) is required.")

        endpoint = f"/repos/{self.repo}/actions/workflows/master_pipeline.yml/dispatches"
        inputs = {
            "video_type": video_type,
            "test_mode": bool(test_mode)
        }
        if custom_topic and custom_topic.strip():
            inputs["custom_topic"] = custom_topic.strip()

        payload = {
            "ref": ref,
            "inputs": inputs
        }
        self._request(endpoint, method="POST", data=payload)
        return {
            "dispatched": True,
            "repo": self.repo,
            "ref": ref,
            "inputs": inputs,
            "workflow": "master_pipeline.yml"
        }

    def list_workflow_runs(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Fetches recent workflow runs for master_pipeline.yml."""
        if not self.token:
            return []
        endpoint = f"/repos/{self.repo}/actions/workflows/master_pipeline.yml/runs?per_page={limit}"
        data = self._request(endpoint, method="GET")
        runs = data.get("workflow_runs", [])
        results = []
        for r in runs:
            results.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "status": r.get("status"),              # queued, in_progress, completed
                "conclusion": r.get("conclusion"),      # success, failure, cancelled
                "event": r.get("event"),                # workflow_dispatch, schedule
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
                "html_url": r.get("html_url"),
                "run_number": r.get("run_number"),
                "display_title": r.get("display_title", "Video Production Pipeline")
            })
        return results

    def get_run_details(self, run_id: int) -> Dict[str, Any]:
        """Fetches run status and its discrete jobs breakdown."""
        run_info = self._request(f"/repos/{self.repo}/actions/runs/{run_id}")
        jobs_data = self._request(f"/repos/{self.repo}/actions/runs/{run_id}/jobs")
        jobs = jobs_data.get("jobs", [])

        formatted_jobs = []
        for j in jobs:
            formatted_jobs.append({
                "id": j.get("id"),
                "name": j.get("name"),
                "status": j.get("status"),          # queued, in_progress, completed
                "conclusion": j.get("conclusion"),  # success, failure, skipped
                "started_at": j.get("started_at"),
                "completed_at": j.get("completed_at"),
                "steps": [
                    {
                        "name": s.get("name"),
                        "status": s.get("status"),
                        "conclusion": s.get("conclusion")
                    }
                    for s in j.get("steps", [])
                ]
            })

        return {
            "id": run_info.get("id"),
            "status": run_info.get("status"),
            "conclusion": run_info.get("conclusion"),
            "html_url": run_info.get("html_url"),
            "created_at": run_info.get("created_at"),
            "updated_at": run_info.get("updated_at"),
            "jobs": formatted_jobs
        }

    def list_run_artifacts(self, run_id: int) -> List[Dict[str, Any]]:
        """Lists downloadable artifacts for a given workflow run."""
        endpoint = f"/repos/{self.repo}/actions/runs/{run_id}/artifacts"
        data = self._request(endpoint)
        artifacts = data.get("artifacts", [])
        return [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "size_in_bytes": a.get("size_in_bytes"),
                "expired": a.get("expired", False),
                "created_at": a.get("created_at")
            }
            for a in artifacts
        ]

    def download_and_extract_artifact(self, artifact_id: int, dest_dir: str = "output") -> List[str]:
        """
        Downloads a zip artifact from GitHub and extracts it into dest_dir.
        Returns list of extracted file paths.
        """
        if not self.token:
            raise RuntimeError("GitHub token required to download artifacts.")

        endpoint = f"/repos/{self.repo}/actions/artifacts/{artifact_id}/zip"
        zip_bytes = self._request(endpoint, headers={"Accept": "application/vnd.github+json"})
        os.makedirs(dest_dir, exist_ok=True)

        extracted_files = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for member in z.namelist():
                z.extract(member, path=dest_dir)
                extracted_files.append(os.path.join(dest_dir, member))
        return extracted_files

