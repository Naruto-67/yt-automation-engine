# engine/llm_router.py
import os
import time
import random
import traceback
from typing import Tuple, Optional
from engine.config_manager import config_manager

class LLMRouter:
    """
    Dedicated routing layer for LLM API calls.
    Handles model discovery, rate limiting, and fallback chains.
    """
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
        
        fallback_stable = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-8b", "gemini-1.5-flash"]
        fallback_preview = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash-lite-preview"]

        if not self.gemini_key:
            self._gemini_stable_chain = fallback_stable
            self._gemini_preview_chain = fallback_preview
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
            print(f"🔍 [LLM ROUTER] Auto-discovered {len(stable_models)} stable models.")
        except Exception as e:
            trace = traceback.format_exc()
            print(f"⚠️ [LLM ROUTER] Model discovery failed:\n{trace}\nUsing fallback chains.")
            self._gemini_stable_chain = fallback_stable
            self._gemini_preview_chain = fallback_preview

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

    def execute_generation(self, prompt: str, system_prompt: Optional[str], gemini_quota_ok: bool, task_type: str = "creative") -> Tuple[Optional[str], str, str]:
        """
        Executes the text generation.
        Returns (Generated Text, Provider Name, Provider Key Used)
        Provider Key Used is passed back so the QuotaManager knows what to deduct.

        Routing strategy (preserves Gemini quota for what matters most):
          "creative"  → Gemini first, Groq fallback   (scripts — quality critical)
          "research"  → Gemini first, Groq fallback   (topic research — quality matters)
          "strategy"  → Gemini first, Groq fallback   (performance analyst — strategic reasoning)
          "analysis"  → Groq first,   Gemini fallback  (validator, scheduler, audit — cheap tasks)
          "seo"       → Groq first,   Gemini fallback  (metadata — simple JSON, Groq handles fine)
        """
        self._discover_gemini_models()

        # Tasks that don't need the best model — send to Groq first to preserve Gemini quota
        # "strategy" intentionally excluded: performance_analyst needs Gemini's reasoning quality
        _groq_first_tasks = {"analysis", "seo"}
        groq_first = task_type in _groq_first_tasks

        execution_plan = []

        if groq_first:
            # Cheap tasks: Groq → Gemini Stable → Gemini Preview
            if self.groq_key:
                execution_plan.append(("Groq Llama 3.3", ["llama-3.3-70b-versatile"], "groq"))
            if gemini_quota_ok and self.gemini_key:
                execution_plan.append(("Gemini Stable", self._gemini_stable_chain, "gemini"))
                execution_plan.append(("Gemini Preview", self._gemini_preview_chain, "gemini"))
        else:
            # Creative/research tasks: Gemini Stable → Groq → Gemini Preview
            if gemini_quota_ok and self.gemini_key:
                execution_plan.append(("Gemini Stable", self._gemini_stable_chain, "gemini"))
            if self.groq_key:
                execution_plan.append(("Groq Llama 3.3", ["llama-3.3-70b-versatile"], "groq"))
            if gemini_quota_ok and self.gemini_key:
                execution_plan.append(("Gemini Preview", self._gemini_preview_chain, "gemini"))

        for stage_name, models, provider_key in execution_plan:
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
                            print(f"✅ [{stage_name.upper()}] Generated via {model}")
                            return response.text, f"Gemini ({model})", provider_key
                        except Exception as e:
                            err = str(e).lower()
                            print(f"⚠️ [GEMINI] Exception on {model} (Attempt {attempt+1}): {err}")
                            if any(x in err for x in ["429", "too many requests"]):
                                if attempt < 2: 
                                    self._execute_jitter_backoff(attempt, "GEMINI")
                                    continue
                                else:
                                    print(f"⚠️ [GEMINI QUOTA] Soft limit exhausted on {model}. Trying next.")
                                    break 
                            elif any(x in err for x in ["quota", "exhausted", "billing", "403"]):
                                print(f"⚠️ [GEMINI QUOTA] Hard limit hit on {model}. Breaking out of Gemini stage.")
                                stage_hard_failed = True
                                break 
                            elif any(x in err for x in ["404", "not found", "deprecated"]):
                                print(f"⚠️ [GEMINI] Model deprecated: {model}. Trying next.")
                                break
                            else: 
                                break 
                if stage_hard_failed:
                    print(f"⚠️ [{stage_name.upper()}] Stage collapsed. Moving to next provider.")

            elif stage_name == "Groq Llama 3.3":
                for attempt in range(3):
                    self._enforce_rpm_throttle()
                    try:
                        groq = self._get_groq_client()
                        res = groq.generate_text(prompt, system_prompt=system_prompt)
                        if res: 
                            return res, f"Groq ({groq.TEXT_MODEL})", provider_key
                    except Exception as e:
                        err = str(e).lower()
                        print(f"⚠️ [GROQ] Exception (Attempt {attempt+1}): {err}")
                        if any(x in err for x in ["429", "too many requests"]):
                            if attempt < 2: 
                                self._execute_jitter_backoff(attempt, "GROQ")
                                continue
                            else:
                                print(f"⚠️ [GROQ QUOTA] Soft limit exhausted. Moving to failsafe.")
                                break
                        elif any(x in err for x in ["quota", "exhausted", "billing", "403"]):
                            print(f"⚠️ [GROQ QUOTA] Hard limit hit. Moving to failsafe.")
                            break
                        break

        return None, "All Providers Exhausted", "none"

llm_router = LLMRouter()
