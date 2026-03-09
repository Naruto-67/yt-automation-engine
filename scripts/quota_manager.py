# scripts/quota_manager.py — Ghost Engine V6.2
import os
import json
import time
import traceback
from datetime import datetime, timezone
from engine.database import db
from engine.config_manager import config_manager

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
        self._gemini_model_chain: list = []
        self._gemini_models_discovered = False
        self._groq = None

    def _groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_channel_id(self) -> str:
        return os.environ.get("CURRENT_CHANNEL_ID", "default_channel")

    def _get_active_state(self) -> dict:
        """
        GOD-TIER FIX: YouTube is tracked per-channel.
        Gemini, Cloudflare, and HF are tracked GLOBALLY.
        """
        today = self._today()
        ch_id = self._get_channel_id()

        # Initialize and fetch Channel-Specific State (YouTube)
        ch_state = db.get_quota_state(today, ch_id)
        if not ch_state:
            db.init_quota_state(today, ch_id, today)
            ch_state = db.get_quota_state(today, ch_id) or {}

        # Initialize and fetch Global State (AI Providers)
        gl_state = db.get_quota_state(today, "GLOBAL")
        if not gl_state:
            db.init_quota_state(today, "GLOBAL", today)
            gl_state = db.get_quota_state(today, "GLOBAL") or {}

        return {
            "date":           today,
            "channel_id":     ch_id,
            "youtube_points": ch_state.get("youtube_points", 0),
            "gemini_calls":   gl_state.get("gemini_calls", 0),
            "cf_images":      gl_state.get("cf_images", 0),
            "hf_images":      gl_state.get("hf_images", 0)
        }

    def consume_points(self, provider: str, amount: int):
        today = self._today()
        
        # Route the cost to the correct pool
        if provider == "youtube":
            target_id = self._get_channel_id()
            col = "youtube_points"
            yt_update = today
        else:
            target_id = "GLOBAL"
            yt_update = None
            col_map = {
                "gemini":      "gemini_calls",
                "cloudflare":  "cf_images",
                "huggingface": "hf_images"
            }
            col = col_map.get(provider)

        if col:
            # Ensure the row exists before updating
            if not db.get_quota_state(today, target_id):
                db.init_quota_state(today, target_id, today)
                
            db.update_quota(today, target_id, col, amount, yt_update)
            
            # Flush a snapshot to JSON for debug logs
            try:
                state = self._get_active_state()
                os.makedirs(os.path.dirname(_QUOTA_JSON_PATH), exist_ok=True)
                with open(_QUOTA_JSON_PATH, "w") as f:
                    json.dump(state, f, indent=2)
            except Exception:
                pass

    def consume_youtube_and_call(self, api_call, cost: int):
        if not self.can_afford_youtube(cost):
            raise RuntimeError(f"Quota insufficient for YouTube call (cost={cost})")
        result = api_call()
        self.consume_points("youtube", cost)
        return result

    def can_afford_youtube(self, cost: int) -> bool:
        state = self._get_active_state()
        return (state.get("youtube_points", 0) + cost) <= self.LIMITS["youtube"]

    def is_provider_exhausted(self, provider: str) -> bool:
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

    def _discover_gemini_models(self) -> list:
        if self._gemini_models_discovered:
            return self._gemini_model_chain

        settings  = config_manager.get_settings()
        fallbacks = settings.get("gemini_model_fallback_chain", [
            "gemini-2.0-flash", "gemini-2.0-flash-lite",
            "gemini-1.5-flash-8b", "gemini-1.5-flash",
        ])

        if not self.gemini_key:
            self._gemini_model_chain = fallbacks
            self._gemini_models_discovered = True
            return self._gemini_model_chain

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key)
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models if hasattr(m, "name")]

            def _score(name: str) -> int:
                n = name.lower()
                if "flash" not in n and "lite" not in n: return -1
                score = 0
                if "preview" in n or "exp" in n: score -= 20
                if "2.0" in n:  score += 100
                elif "1.5" in n: score += 60
                elif "1.0" in n: score += 20
                if "flash-8b" in n:  score += 10
                elif "flash-lite" in n: score += 15
                elif "flash" in n:    score += 20
                return score

            ranked = sorted([m for m in model_names if _score(m) >= 0], key=_score, reverse=True)
            self._gemini_model_chain = ranked[:5] if ranked else fallbacks
            print(f"✅ [GEMINI] Discovered model chain: {self._gemini_model_chain}")

        except Exception as e:
            print(f"⚠️ [GEMINI] Model discovery failed ({e}), using fallback chain.")
            self._gemini_model_chain = fallbacks

        self._gemini_models_discovered = True
        return self._gemini_model_chain

    def generate_text(self, prompt: str, task_type: str = "creative", system_prompt: str = None) -> tuple:
        state  = self._get_active_state()
        chains = config_manager.get_providers().get("generation_chains", {})

        for provider in chains.get("script", ["gemini", "groq"]):
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
                            model=model, contents=prompt, config=cfg or None
                        )
                        self.consume_points("gemini", 1)
                        print(f"✅ [GEMINI] Generated via {model}")
                        return response.text, f"Gemini ({model})"
                    except Exception as e:
                        err = str(e).lower()
                        if any(x in err for x in ["quota", "429", "limit"]):
                            print(f"⚠️ [GEMINI] Quota hit on {model}: {e}")
                            break 
                        elif any(x in err for x in ["404", "not found", "deprecated"]):
                            print(f"⚠️ [GEMINI] Model deprecated: {model}")
                            self._gemini_models_discovered = False
                            continue
                        else:
                            print(f"⚠️ [GEMINI] Error on {model}: {e}")
                            continue

            elif provider in ("groq", "groq_orpheus"):
                try:
                    groq = self._groq_client()
                    res = groq.generate_text(prompt, system_prompt=system_prompt)
                    if res:
                        return res, f"Groq ({groq.TEXT_MODEL})"
                except Exception as e:
                    print(f"⚠️ [GROQ] Text generation failed: {e}")

        return None, "All Providers Exhausted"

    def diagnose_fatal_error(self, module: str, exception: Exception):
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp = datetime.now().isoformat()
        trace     = traceback.format_exc()

        try:
            if os.path.exists(error_log) and os.path.getsize(error_log) > 1_000_000:
                with open(error_log, "r") as f:
                    lines = f.readlines()
                with open(error_log, "w") as f:
                    f.writelines(lines[len(lines)//2:])
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
