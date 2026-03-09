# scripts/quota_manager.py — Ghost Engine V6
import os
import json
import time
import traceback
from datetime import datetime, timezone
from engine.database import db
from engine.config_manager import config_manager

# ─── Quota state JSON path (committed to repo for cross-workflow awareness) ───
_QUOTA_JSON_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory", "quota_state.json"
)


class MasterQuotaManager:

    def __init__(self):
        self.root_dir   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        settings = config_manager.get_settings()
        self.LIMITS     = settings.get("api_limits", {
            "gemini": 38, "cloudflare": 90, "huggingface": 45, "youtube": 9200
        })
        # Lazy-initialised Gemini model chain (populated on first use)
        self._gemini_model_chain: list = []
        self._gemini_models_discovered = False
        # Groq client — imported lazily to avoid circular imports
        self._groq = None

    # ── INTERNAL ──────────────────────────────────────────────────────────────

    def _groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_active_state(self) -> dict:
        today = self._today()

        # 1. Try DB (persisted if ghost_engine.db is committed)
        state = db.get_quota_state(today)
        if state:
            return state

        # 2. Fall back to quota_state.json (committed JSON — cross-workflow bridge)
        try:
            if os.path.exists(_QUOTA_JSON_PATH):
                with open(_QUOTA_JSON_PATH, "r") as f:
                    saved = json.load(f)
                if saved.get("date") == today:
                    db.init_quota_state(today, today)
                    # Seed DB with values from JSON
                    for col, val in [
                        ("youtube_points", saved.get("youtube_points", 0)),
                        ("gemini_calls",   saved.get("gemini_calls", 0)),
                        ("cf_images",      saved.get("cf_images", 0)),
                        ("hf_images",      saved.get("hf_images", 0)),
                    ]:
                        if val:
                            db.update_quota(today, col, val)
                    return db.get_quota_state(today)
        except Exception:
            pass

        # 3. Fresh start for today
        db.init_quota_state(today, today)
        return db.get_quota_state(today)

    def _flush_quota_json(self):
        """Mirror current DB quota state to quota_state.json for cross-workflow persistence."""
        try:
            state = db.get_quota_state(self._today()) or {}
            os.makedirs(os.path.dirname(_QUOTA_JSON_PATH), exist_ok=True)
            with open(_QUOTA_JSON_PATH, "w") as f:
                json.dump({
                    "date":           self._today(),
                    "youtube_points": state.get("youtube_points", 0),
                    "gemini_calls":   state.get("gemini_calls", 0),
                    "cf_images":      state.get("cf_images", 0),
                    "hf_images":      state.get("hf_images", 0),
                    "updated_at":     datetime.utcnow().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️ [QUOTA] Failed to flush quota_state.json: {e}")

    # ── QUOTA OPERATIONS ──────────────────────────────────────────────────────

    def consume_points(self, provider: str, amount: int):
        today = self._today()
        col_map = {
            "youtube":     "youtube_points",
            "gemini":      "gemini_calls",
            "cloudflare":  "cf_images",
            "huggingface": "hf_images",
        }
        col = col_map.get(provider)
        if col:
            yt_update = today if provider == "youtube" else None
            db.update_quota(today, col, amount, yt_update)
            self._flush_quota_json()

    def consume_youtube_and_call(self, api_call, cost: int):
        """Execute a YouTube API call and consume quota points in one atomic step."""
        if not self.can_afford_youtube(cost):
            raise RuntimeError(f"Quota insufficient for YouTube call (cost={cost})")
        result = api_call()
        self.consume_points("youtube", cost)
        return result

    def can_afford_youtube(self, cost: int) -> bool:
        state = self._get_active_state()
        return (state.get("youtube_points", 0) + cost) <= self.LIMITS["youtube"]

    def is_provider_exhausted(self, provider: str) -> bool:
        """
        FIX: Method was called throughout generate_visuals.py but never existed.
        Returns True when a provider has hit its daily limit.
        """
        state = self._get_active_state()
        col_limit_map = {
            "cloudflare":  ("cf_images",    "cloudflare"),
            "huggingface": ("hf_images",    "huggingface"),
            "gemini":      ("gemini_calls", "gemini"),
        }
        if provider not in col_limit_map:
            return False
        col, key = col_limit_map[provider]
        used  = state.get(col, 0)
        limit = self.LIMITS.get(key, 9999)
        return used >= limit

    # ── GEMINI MODEL DISCOVERY ────────────────────────────────────────────────

    def _discover_gemini_models(self) -> list:
        """
        Auto-discovers available Gemini models from the API.
        Priority: stable > lite > experimental > preview.
        Free-tier models only (flash/lite family).
        Falls back to settings.yaml chain if discovery fails.
        """
        if self._gemini_models_discovered:
            return self._gemini_model_chain

        settings  = config_manager.get_settings()
        fallbacks = settings.get("gemini_model_fallback_chain", [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash-8b",
            "gemini-1.5-flash",
        ])

        if not self.gemini_key:
            self._gemini_model_chain = fallbacks
            self._gemini_models_discovered = True
            return self._gemini_model_chain

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key)
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models
                           if hasattr(m, "name")]

            def _score(name: str) -> int:
                n = name.lower()
                if "flash" not in n and "lite" not in n:
                    return -1  # Exclude Pro/Ultra — not free tier
                score = 0
                # Stability tier (stable > preview > experimental > lite)
                if "preview" in n or "exp" in n:
                    score -= 20
                # Version scoring (higher = better)
                if "2.0" in n:  score += 100
                elif "1.5" in n: score += 60
                elif "1.0" in n: score += 20
                # Sub-tier
                if "flash-8b" in n:  score += 10
                elif "flash-lite" in n: score += 15
                elif "flash" in n:    score += 20
                return score

            ranked = sorted(
                [m for m in model_names if _score(m) >= 0],
                key=_score, reverse=True
            )

            self._gemini_model_chain = ranked[:5] if ranked else fallbacks
            print(f"✅ [GEMINI] Discovered model chain: {self._gemini_model_chain}")

        except Exception as e:
            print(f"⚠️ [GEMINI] Model discovery failed ({e}), using fallback chain.")
            self._gemini_model_chain = fallbacks

        self._gemini_models_discovered = True
        return self._gemini_model_chain

    # ── TEXT GENERATION ───────────────────────────────────────────────────────

    def generate_text(self, prompt: str, task_type: str = "creative",
                      system_prompt: str = None) -> tuple:
        """
        Generate text using the full provider chain:
          Gemini (auto-discovered, stable free-tier first)
          → Groq Llama (auto-discovered, stable first)

        Returns (text: str | None, provider_label: str)
        """
        state  = self._get_active_state()
        chains = config_manager.get_providers().get("generation_chains", {})

        for provider in chains.get("script", ["gemini", "groq"]):

            # ── Gemini ────────────────────────────────────────────────────────
            if provider == "gemini":
                if state.get("gemini_calls", 0) >= self.LIMITS["gemini"]:
                    print("⚠️ [GEMINI] Daily limit reached — skipping.")
                    continue
                if not self.gemini_key:
                    continue

                model_chain = self._discover_gemini_models()
                for model in model_chain:
                    try:
                        from google import genai
                        client = genai.Client(api_key=self.gemini_key)
                        cfg = {"system_instruction": system_prompt} if system_prompt else {}
                        response = client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=cfg or None
                        )
                        self.consume_points("gemini", 1)
                        print(f"✅ [GEMINI] Generated via {model}")
                        return response.text, f"Gemini ({model})"
                    except Exception as e:
                        err = str(e).lower()
                        if any(x in err for x in ["quota", "429", "limit"]):
                            print(f"⚠️ [GEMINI] Quota hit on {model}: {e}")
                            break   # Stop trying Gemini — hit daily limit
                        elif any(x in err for x in ["404", "not found", "deprecated"]):
                            print(f"⚠️ [GEMINI] Model deprecated: {model}")
                            self._gemini_models_discovered = False  # Force rediscovery
                            continue
                        else:
                            print(f"⚠️ [GEMINI] Error on {model}: {e}")
                            continue

            # ── Groq ──────────────────────────────────────────────────────────
            elif provider in ("groq", "groq_orpheus"):
                try:
                    groq = self._groq_client()
                    res = groq.generate_text(prompt, system_prompt=system_prompt)
                    if res:
                        return res, f"Groq ({groq.TEXT_MODEL})"
                except Exception as e:
                    print(f"⚠️ [GROQ] Text generation failed: {e}")

        return None, "All Providers Exhausted"

    # ── ERROR HANDLING ────────────────────────────────────────────────────────

    def diagnose_fatal_error(self, module: str, exception: Exception):
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp = datetime.now().isoformat()
        trace     = traceback.format_exc()

        # Rolling log — trim at 1 MB
        try:
            if os.path.exists(error_log) and os.path.getsize(error_log) > 1_000_000:
                with open(error_log, "r") as f:
                    lines = f.readlines()
                with open(error_log, "w") as f:
                    f.writelines(lines[len(lines)//2:])  # Keep newest half
        except Exception:
            pass

        with open(error_log, "a") as f:
            f.write(f"\n[{timestamp}] [{module}] {type(exception).__name__}: {exception}\n{trace}\n{'─'*40}")

        try:
            from scripts.discord_notifier import notify_error
            notify_error(module, type(exception).__name__, str(exception))
        except Exception:
            pass


quota_manager = MasterQuotaManager()
