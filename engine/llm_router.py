# engine/llm_router.py
import os
import time
import random
import traceback
from typing import Tuple, Optional
from engine.config_manager import config_manager

class LLMRouter:
    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self._gemini_stable_chain = []
        self._gemini_preview_chain = []
        self._gemini_models_discovered = False
        self._last_llm_call_time = 0.0
        self._groq = None

    def _get_groq_client(self):
        if self._groq is None:
            from scripts.groq_client import groq_client
            self._groq = groq_client
        return self._groq

    def _discover_gemini_models(self):
        if self._gemini_models_discovered: return
        
        # Failsafe fallback if discovery endpoint goes down or changes format.
        # gemini-1.5-flash is Google's declared long-term stable tier.
        fallback_stable = ["gemini-1.5-flash"]
        fallback_preview = []

        if not self.gemini_key:
            self._gemini_models_discovered = True
            return

        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_key)
            all_models = list(client.models.list())
            model_names = [m.name.replace("models/", "") for m in all_models if hasattr(m, "name")]

            import re as _re

            def _score(name: str) -> int:
                """
                Score Gemini models by version number automatically.
                Uses dynamic version parsing so any newer model (e.g. gemini-3.0-flash,
                gemini-4.5-flash-lite) is preferred over older ones without code changes.
                """
                n = name.lower()
                # Exclude non-text models — they break the text generation chain
                if any(x in n for x in ["vision", "audio", "tts", "embedding", "imagen"]):
                    return -1

                # Extract the major.minor version number from the model name
                # e.g. "gemini-2.5-flash" → 2.5, "gemini-1.5-flash-8b" → 1.5
                m = _re.search(r"gemini[-\s]?(\d+)\.(\d+)", n)
                if not m:
                    return 0  # unknown format — rank lowest

                major = int(m.group(1))
                minor = int(m.group(2))

                # Score = (major * 100) + minor
                # This ensures: 3.0 > 2.5 > 2.0 > 1.5 > 1.0
                # So newer free models (e.g. 3.0-flash, 3.5-flash-lite) are always preferred.
                score = (major * 100) + minor
                return score

            self._gemini_stable_chain = sorted([m for m in model_names if "exp" not in m and "preview" not in m], key=_score, reverse=True)[:4]
            self._gemini_preview_chain = sorted([m for m in model_names if "exp" in m or "preview" in m], key=_score, reverse=True)[:2]
        except Exception as e:
            print(f"⚠️ [GEMINI] Model discovery failed: {e}. Using fallback stable models.")
            self._gemini_stable_chain = fallback_stable
            self._gemini_preview_chain = fallback_preview

        self._gemini_models_discovered = True

    def _enforce_rpm_throttle(self):
        elapsed = time.time() - self._last_llm_call_time
        if elapsed < 2.5: time.sleep(2.5 - elapsed)
        self._last_llm_call_time = time.time()

    def execute_generation(self, prompt: str, system_prompt: Optional[str], gemini_quota_ok: bool, task_type: str = "creative") -> Tuple[Optional[str], str, str]:
        self._discover_gemini_models()

        # ROUTING: Stable -> Groq -> Preview
        execution_plan = []
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Stable", self._gemini_stable_chain, "gemini"))
        if self.groq_key:
            # Discovered, ranked Groq text-model chain (never hardcoded single model)
            execution_plan.append(("Groq Chain", ["__groq__"], "groq"))
        if gemini_quota_ok and self.gemini_key:
            execution_plan.append(("Gemini Preview", self._gemini_preview_chain, "gemini"))

        for stage_name, models, provider_key in execution_plan:
            if "Gemini" in stage_name:
                stage_hard_failed = False
                for model in models:
                    if stage_hard_failed:
                        break
                    for attempt in range(3):
                        self._enforce_rpm_throttle()
                        try:
                            import threading
                            from google import genai
                            from google.genai import types

                            client = genai.Client(api_key=self.gemini_key)
                            cfg = {"system_instruction": system_prompt} if system_prompt else {}
                            chat = client.chats.create(model=model, config=cfg or None)
                            gen_cfg = types.GenerateContentConfig(
                                temperature=0.3, max_output_tokens=8000,
                            ) if cfg else None

                            # ── Streaming with first-token deadline ──────────────────
                            # When Gemini is overloaded it hangs for 2-3 min BEFORE
                            # returning 503 — it never starts streaming.
                            # When healthy it starts streaming within 1-5 seconds.
                            #
                            # Strategy:
                            #   first_token_event: set as soon as any chunk arrives
                            #   15s deadline for first token → fast-fail on overload
                            #   90s total deadline → safe for any length of response
                            #
                            # daemon=True: abandoned threads clean up on process exit.
                            first_token_event = threading.Event()
                            done_event        = threading.Event()
                            chunks: list      = []
                            stream_exc: list  = []

                            def _stream():
                                try:
                                    for chunk in chat.send_message_stream(
                                        message=prompt, config=gen_cfg
                                    ):
                                        if chunk.text:
                                            chunks.append(chunk.text)
                                            first_token_event.set()
                                except Exception as exc:
                                    stream_exc.append(exc)
                                finally:
                                    first_token_event.set()  # unblock waiter on error too
                                    done_event.set()

                            t = threading.Thread(target=_stream, daemon=True)
                            t.start()

                            # Wait for first token (15s) — overload hangs never get past here
                            if not first_token_event.wait(timeout=15):
                                raise TimeoutError(
                                    f"No first token from {model} within 15s — likely overloaded"
                                )
                            if stream_exc:
                                raise stream_exc[0]

                            # First token arrived — wait for full response (90s total)
                            done_event.wait(timeout=90)
                            if stream_exc:
                                raise stream_exc[0]

                            text = "".join(chunks)
                            if not text:
                                raise ValueError(f"Empty response from {model}")

                            return text, f"Gemini ({model})", provider_key

                        except Exception as e:
                            print(f"⚠️ [GEMINI] Attempt {attempt+1} failed for {model}: {e}")
                            err_str = str(e).lower()
                            if any(x in err_str for x in ["quota", "exhausted", "403"]):
                                stage_hard_failed = True
                                break
                            # 503 / UNAVAILABLE / timeout: skip to next model immediately.
                            if "503" in err_str or "unavailable" in err_str or "timeout" in err_str or "timed out" in err_str:
                                break
                            continue
            elif stage_name == "Groq Chain":
                # groq_client.generate_text already iterates the full discovered
                # model chain internally and its own API returns text.
                try:
                    res = self._get_groq_client().generate_text(prompt, system_prompt=system_prompt)
                    if res:
                        return res, "Groq (Auto Chain)", provider_key
                except Exception:
                    continue

        return None, "All Providers Exhausted", "none"

llm_router = LLMRouter()
