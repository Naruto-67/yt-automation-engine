# scripts/quota_manager.py
import os
import json
import time
import random
import traceback
import pytz
from datetime import datetime, timezone
from engine.database import db
from engine.config_manager import config_manager
from engine.context import ctx

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
_FILE_NAME = "quota_state_test.json" if TEST_MODE else "quota_state.json"
_QUOTA_JSON_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "memory", _FILE_NAME)

class MasterQuotaManager:
    def __init__(self):
        self.root_dir   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        # Ensure we securely check for the Groq key to prevent retry-loop resource leaks
        self.groq_key   = os.environ.get("GROQ_API_KEY")
        
        settings = config_manager.get_settings()
        self.LIMITS     = settings.get("api_limits", {
            "gemini": 38, "cloudflare": 90, "huggingface": 45, "youtube": 9200
        })
        self._gemini_stable_chain: list = []
        self._gemini_preview_chain: list = []
        self._gemini_models_discovered = False
        self._groq = None
        self._last_llm_call_time = 0.0

    def _groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _today_utc(self) -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    def _today_pt(self) -> str: return datetime.now(pytz.timezone('America/Los_Angeles')).strftime("%Y-%m-%d")
    def _get_channel_id(self) -> str: return ctx.get_channel_id()

    def _get_active_state(self) -> dict:
        today_utc, today_pt, ch_id = self._today_utc(), self._today_pt(), self._get_channel_id()
        ch_state = db.get_quota_state(today_pt, ch_id)
        if not ch_state:
            db.init_quota_state(today_pt, ch_id, today_pt)
            ch_state = db.get_quota_state(today_pt, ch_id) or {}
        gl_state = db.get_quota_state(today_utc, "GLOBAL")
        if not gl_state:
            db.init_quota_state(today_utc, "GLOBAL", today_utc)
            gl_state = db.get_quota_state(today_utc, "GLOBAL") or {}
        return {
            "date": today_utc, "channel_id": ch_id,
            "youtube_points": ch_state.get("youtube_points", 0), "gemini_calls": gl_state.get("gemini_calls", 0),
            "cf_images": gl_state.get("cf_images", 0), "hf_images": gl_state.get("hf_images", 0)
        }

    def consume_points(self, provider: str, amount: int):
        if TEST_MODE and provider == "youtube": return 
        if provider == "youtube":
            target_id, col, today, yt_update = self._get_channel_id(), "youtube_points", self._today_pt(), self._today_pt()
        else:
            target_id, today, yt_update = "GLOBAL", self._today_utc(), None
            col_map = {"gemini": "gemini_calls", "cloudflare": "cf_images", "huggingface": "hf_images"}
            col = col_map.get(provider)
        if col:
            if not db.get_quota_state(today, target_id): db.init_quota_state(today, target_id, today)
            db.update_quota(today, target_id, col, amount, yt_update)
            try:
                state = self._get_active_state()
                os.makedirs(os.path.dirname(_QUOTA_JSON_PATH), exist_ok=True)
                with open(_QUOTA_JSON_PATH, "w") as f: json.dump(state, f, indent=2)
            except Exception: pass

    def can_afford_youtube(self, cost: int) -> bool:
        if TEST_MODE: return True
        return (self._get_active_state().get("youtube_points", 0) + cost) <= self.LIMITS["youtube"]

    def is_provider_exhausted(self, provider: str) -> bool:
        state = self._get_active_state()
        col_limit_map = {"cloudflare": ("cf_images", "cloudflare"), "huggingface": ("hf_images", "huggingface"), "gemini": ("gemini_calls", "gemini")}
        if provider not in col_limit_map: return False
        col, key = col_limit_map[provider]
        return state.get(col, 0) >= self.LIMITS.get(key, 9999)

    def _discover_gemini_models(self):
        if self._gemini_models_discovered: return
        settings = config_manager.get_settings()
        fallback_stable = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-8b", "gemini-1.5-flash"]
        fallback_preview = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash-lite-preview"]

        if not self.gemini_key:
            self._gemini_stable_chain, self._gemini_preview_chain = fallback_stable, fallback_preview
            self._gemini_models_discovered = True
            return

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key)
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models if hasattr(m, "name")]

            def _score(name: str) -> int:
                n = name.lower()
                if any(x in n for x in ["vision", "image", "embedding", "audio", "aqa", "learn", "tts", "customtools"]): return -1
                if "flash" not in n and "lite" not in n and "pro" not in n: return -1
                score = 0
                if "3.1" in n: score += 150
                elif "3.0" in n: score += 120
                elif "2.5" in n: score += 100
                elif "2.0" in n: score += 80
                elif "1.5" in n: score += 60
                elif "1.0" in n: score += 20
                if "flash-8b" in n: score += 10
                elif "flash-lite" in n: score += 15
                elif "flash" in n: score += 20
                if "pro" in n: score -= 50 
                return score

            valid_models = [m for m in model_names if _score(m) >= 0]
            stable_models = sorted([m for m in valid_models if "preview" not in m.lower() and "exp" not in m.lower()], key=_score, reverse=True)
            preview_models = sorted([m for m in valid_models if "preview" in m.lower() or "exp" in m.lower()], key=_score, reverse=True)

            self._gemini_stable_chain = stable_models[:4] if stable_models else fallback_stable
            self._gemini_preview_chain = preview_models[:2] if preview_models else fallback_preview
            print(f"🔍 [GEMINI] Auto-discovered {len(stable_models)} stable models. Active stable queue: {self._gemini_stable_chain}")
            print(f"🔍 [GEMINI] Auto-discovered {len(preview_models)} preview models. Failsafe queue: {self._gemini_preview_chain}")
        except Exception as e:
            trace = traceback.format_exc()
            print(f"⚠️ [GEMINI] Model discovery failed:\n{trace}\nUsing fallback chains.")
            self._gemini_stable_chain, self._gemini_preview_chain = fallback_stable, fallback_preview

        self._gemini_models_discovered = True

    def _enforce_rpm_throttle(self):
        elapsed = time.time() - self._last_llm_call_time
        if elapsed < 2.5: time.sleep(2.5 - elapsed)
        self._last_llm_call_time = time.time()

    def _execute_jitter_backoff(self, attempt: int, api_name: str):
        if attempt == 0: wait_time, tier = random.uniform(5.0, 10.0), "Low"
        elif attempt == 1: wait_time, tier = random.uniform(20.0, 40.0), "Mid"
        else: wait_time, tier = random.uniform(40.0, 60.0), "High"
        print(f"⏳ [{api_name} RPM] Tier {tier} backoff. Cooling down for {wait_time:.1f}s...")
        time.sleep(wait_time)

    def generate_text(self, prompt: str, task_type: str = "creative", system_prompt: str = None) -> tuple:
        self._discover_gemini_models()
        state = self._get_active_state()
        
        execution_plan = []
        
        # STAGE 1: Stable Gemini
        if state.get("gemini_calls", 0) < self.LIMITS["gemini"] and self.gemini_key:
            execution_plan.append(("Gemini Stable", self._gemini_stable_chain))
            
        # 🚨 FIX: STAGE 2: Groq Llama 3.3 (Gated safely by API key existence)
        if self.groq_key:
            execution_plan.append(("Groq Llama 3.3", ["llama-3.3-70b-versatile"]))
        
        # STAGE 3: Gemini Preview (Failsafe)
        if state.get("gemini_calls", 0) < self.LIMITS["gemini"] and self.gemini_key:
            execution_plan.append(("Gemini Preview", self._gemini_preview_chain))

        for stage_name, models in execution_plan:
            if "Gemini" in stage_name:
                stage_hard_failed = False
                for model in models:
                    if stage_hard_failed: break
                    for attempt in range(3): 
                        self._enforce_rpm_throttle()
                        try:
                            from google import genai
                            client = genai.Client(api_key=self.gemini_key)
                            cfg = {"system_instruction": system_prompt} if system_prompt else {}
                            response = client.models.generate_content(model=model, contents=prompt, config=cfg or None)
                            self.consume_points("gemini", 1)
                            print(f"✅ [{stage_name.upper()}] Generated via {model}")
                            return response.text, f"Gemini ({model})"
                        except Exception as e:
                            err, trace = str(e).lower(), traceback.format_exc()
                            print(f"⚠️ [GEMINI] Exception on {model} (Attempt {attempt+1}):\n{trace}")
                            if any(x in err for x in ["429", "too many requests"]):
                                if attempt < 2: self._execute_jitter_backoff(attempt, "GEMINI"); continue
                                else:
                                    print(f"⚠️ [GEMINI QUOTA] Soft limit exhausted on {model}. Trying next model.")
                                    break 
                            elif any(x in err for x in ["quota", "exhausted", "billing", "403"]):
                                print(f"⚠️ [GEMINI QUOTA] Hard limit hit on {model}. Breaking out of Gemini stage.")
                                stage_hard_failed = True
                                break 
                            elif any(x in err for x in ["404", "not found", "deprecated"]):
                                print(f"⚠️ [GEMINI] Model deprecated: {model}. Trying next model.")
                                break
                            else: break 
                if stage_hard_failed:
                    print(f"⚠️ [{stage_name.upper()}] Stage collapsed. Moving to next provider fallback.")

            elif stage_name == "Groq Llama 3.3":
                for attempt in range(3):
                    self._enforce_rpm_throttle()
                    try:
                        groq = self._groq_client()
                        res = groq.generate_text(prompt, system_prompt=system_prompt)
                        if res: return res, f"Groq ({groq.TEXT_MODEL})"
                    except Exception as e:
                        err, trace = str(e).lower(), traceback.format_exc()
                        print(f"⚠️ [GROQ] Exception (Attempt {attempt+1}):\n{trace}")
                        if any(x in err for x in ["429", "too many requests"]):
                            if attempt < 2: self._execute_jitter_backoff(attempt, "GROQ"); continue
                            else:
                                print(f"⚠️ [GROQ QUOTA] Soft limit exhausted. Moving to absolute failsafe.")
                                break
                        elif any(x in err for x in ["quota", "exhausted", "billing", "403"]):
                            print(f"⚠️ [GROQ QUOTA] Hard account limit hit. Moving to absolute failsafe.")
                            break
                        break

        return None, "All Providers Exhausted"

    def diagnose_fatal_error(self, module: str, exception: Exception):
        error_log = os.path.join(self.root_dir, "memory", "error_log.txt")
        timestamp, trace = datetime.now().isoformat(), traceback.format_exc()
        try:
            if os.path.exists(error_log) and os.path.getsize(error_log) > 1_000_000:
                with open(error_log, "r") as f: lines = f.readlines()
                with open(error_log, "w") as f: f.writelines(lines[len(lines)//2:])
            with open(error_log, "a") as f: f.write(f"\n[{timestamp}] [{module}] {type(exception).__name__}: {exception}\n{trace}\n{'─'*40}")
        except: pass
        try:
            from scripts.discord_notifier import notify_error
            notify_error(module, type(exception).__name__, str(exception))
        except: pass

quota_manager = MasterQuotaManager()
