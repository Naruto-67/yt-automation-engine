# engine/model_entity.py — Autonomous Namespaced Model Entity & Scarcity Waterfall Architecture
"""
Autonomous Model Entity, Dynamic Quota Tracker, and Scarcity Waterfall Resolver.
Treats all models across all free-tier providers as first-class, namespaced individual entities.
Harvests scarce premium quotas up to an 85% safety cushion (reserving 3-4 calls for emergencies)
and self-calibrates quotas via dynamic HTTP response header sniffing.
"""

import os
import json
import time
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from engine.logger import logger


@dataclass
class ModelEntity:
    entity_id: str                          # "<provider>:<model_identifier>" e.g. "google:gemini-3.8-flash"
    provider: str                           # "google", "groq", "github", "openrouter"
    model_name: str                         # "gemini-3.8-flash", "llama-3.3-70b-versatile"
    task_quality_scores: Dict[str, float] = field(default_factory=lambda: {
        "scriptwriting": 8.5,
        "seo_json": 8.0,
        "vision_audit": 8.0,
        "fact_grounding": 8.0
    })
    max_rpm: int = 15                       # Requests per minute ceiling
    max_rpd: int = 20                       # Requests per day ceiling (e.g. 20 for scarce flagships, 500 for workhorses)
    consumed_today: int = 0                 # Calls consumed in current quota window
    last_call_timestamp: float = 0.0        # Epoch seconds of last execution
    status: str = "ACTIVE"                  # "ACTIVE", "QUOTA_EXHAUSTED", "COOLDOWN", "DEPRECATED"
    reset_epoch: float = 0.0                # Epoch seconds when quota resets
    average_latency: float = 2.0            # Exponential moving average latency in seconds
    cooldown_until: float = 0.0             # Epoch seconds until transient cooldown expires

    @property
    def utilization_rate(self) -> float:
        if self.max_rpd <= 0:
            return 0.0
        return self.consumed_today / float(self.max_rpd)

    def is_under_scarcity_ceiling(self, ceiling: float = 0.85) -> bool:
        """
        Returns True if model is within the safe harvesting threshold.
        High-capacity workhorses (max_rpd >= 500) are permitted to harvest up to 95%.
        Scarce flagships (max_rpd <= 50) strictly observe the 85% ceiling (reserving 3-4 calls).
        """
        if self.max_rpd >= 500:
            return self.utilization_rate < 0.95
        return self.utilization_rate < ceiling

    def is_available(self) -> bool:
        now = time.time()
        if self.status == "DEPRECATED":
            return False

        if self.max_rpd > 0 and self.consumed_today >= self.max_rpd:
            return False

        # Check if 429 quota exhaustion reset epoch has passed
        if self.status == "QUOTA_EXHAUSTED":
            if self.reset_epoch > 0 and now >= self.reset_epoch:
                self.status = "ACTIVE"
                self.consumed_today = 0
                return True
            return False

        # Check if 503 transient cooldown has expired
        if self.status == "COOLDOWN":
            if now >= self.cooldown_until:
                self.status = "ACTIVE"
                return True
            return False

        return self.status == "ACTIVE"


class DynamicQuotaTracker:
    """
    Manages persistence of dynamic model entities, provider-aligned daily reset epochs,
    and automatic calibration from HTTP response headers.
    """
    def __init__(self, registry_path: Optional[str] = None):
        if registry_path is None:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            registry_path = os.path.join(root_dir, "memory", "dynamic_models_registry.json")
        self.registry_path = registry_path
        self.entities: Dict[str, ModelEntity] = {}
        self.last_reset_dates: Dict[str, str] = {}
        self._load_and_initialize()

    def _load_and_initialize(self):
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        data = {}
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warn(f"⚠️ [QUOTA TRACKER] Could not parse registry ({e}). Rebuilding.")

        self.last_reset_dates = data.get("provider_reset_dates", {})
        saved_entities = data.get("entities", {})

        # Default model catalog covering all active free-tier providers
        default_catalog = [
            # Google GenAI Free Tier
            {"entity_id": "google:gemini-3.8-flash", "provider": "google", "model_name": "gemini-3.8-flash",
             "max_rpm": 15, "max_rpd": 20, "task_scores": {"scriptwriting": 9.5, "seo_json": 9.0, "vision_audit": 9.0, "fact_grounding": 8.5}},
            {"entity_id": "google:gemini-3.6-flash", "provider": "google", "model_name": "gemini-3.6-flash",
             "max_rpm": 15, "max_rpd": 20, "task_scores": {"scriptwriting": 9.2, "seo_json": 8.8, "vision_audit": 8.8, "fact_grounding": 8.5}},
            {"entity_id": "google:gemini-flash-lite-latest", "provider": "google", "model_name": "gemini-flash-lite-latest",
             "max_rpm": 30, "max_rpd": 500, "task_scores": {"scriptwriting": 8.6, "seo_json": 9.4, "vision_audit": 8.5, "fact_grounding": 8.8}},
            {"entity_id": "google:gemini-3.5-flash-lite", "provider": "google", "model_name": "gemini-3.5-flash-lite",
             "max_rpm": 30, "max_rpd": 500, "task_scores": {"scriptwriting": 8.5, "seo_json": 9.3, "vision_audit": 8.3, "fact_grounding": 8.6}},

            # Groq Cloud Free Tier (Fast LPU)
            {"entity_id": "groq:llama-3.3-70b-versatile", "provider": "groq", "model_name": "llama-3.3-70b-versatile",
             "max_rpm": 30, "max_rpd": 14400, "task_scores": {"scriptwriting": 9.0, "seo_json": 8.6, "vision_audit": 6.0, "fact_grounding": 8.2}},
            {"entity_id": "groq:llama-3.1-8b-instant", "provider": "groq", "model_name": "llama-3.1-8b-instant",
             "max_rpm": 30, "max_rpd": 14400, "task_scores": {"scriptwriting": 7.8, "seo_json": 9.1, "vision_audit": 5.0, "fact_grounding": 8.0}},

            # GitHub Models Free Tier (Azure AI)
            {"entity_id": "github:gpt-4o-mini", "provider": "github", "model_name": "gpt-4o-mini",
             "max_rpm": 15, "max_rpd": 150, "task_scores": {"scriptwriting": 8.8, "seo_json": 9.2, "vision_audit": 7.5, "fact_grounding": 8.7}},
            {"entity_id": "github:meta/llama-3.3-70b-instruct", "provider": "github", "model_name": "meta/llama-3.3-70b-instruct",
             "max_rpm": 15, "max_rpd": 150, "task_scores": {"scriptwriting": 8.9, "seo_json": 8.5, "vision_audit": 6.0, "fact_grounding": 8.3}},

            # OpenRouter Free Tier Pool
            {"entity_id": "openrouter:meta-llama/llama-3.3-70b-instruct:free", "provider": "openrouter", "model_name": "meta-llama/llama-3.3-70b-instruct:free",
             "max_rpm": 20, "max_rpd": 200, "task_scores": {"scriptwriting": 8.7, "seo_json": 8.4, "vision_audit": 5.0, "fact_grounding": 8.0}},
            {"entity_id": "openrouter:qwen/qwen-2.5-72b-instruct:free", "provider": "openrouter", "model_name": "qwen/qwen-2.5-72b-instruct:free",
             "max_rpm": 20, "max_rpd": 200, "task_scores": {"scriptwriting": 8.6, "seo_json": 8.5, "vision_audit": 5.0, "fact_grounding": 8.0}}
        ]

        for item in default_catalog:
            eid = item["entity_id"]
            saved = saved_entities.get(eid, {})
            self.entities[eid] = ModelEntity(
                entity_id=eid,
                provider=item["provider"],
                model_name=item["model_name"],
                task_quality_scores=saved.get("task_quality_scores", item["task_scores"]),
                max_rpm=saved.get("max_rpm", item["max_rpm"]),
                max_rpd=saved.get("max_rpd", item["max_rpd"]),
                consumed_today=saved.get("consumed_today", 0),
                last_call_timestamp=saved.get("last_call_timestamp", 0.0),
                status=saved.get("status", "ACTIVE"),
                reset_epoch=saved.get("reset_epoch", 0.0),
                average_latency=saved.get("average_latency", 2.0),
                cooldown_until=saved.get("cooldown_until", 0.0)
            )

        self.evaluate_daily_resets()
        self.persist()

    def evaluate_daily_resets(self):
        """
        Enforces provider-aligned reset clocks:
        - google: Midnight Pacific Time (PT)
        - groq / openrouter: Midnight UTC
        - github: Midnight UTC or sliding 24-hr window
        """
        now_utc = datetime.now(timezone.utc)
        # Pacific Time approximation (UTC-8 / UTC-7 DST): UTC - 7 hours safe conservative offset
        now_pt = now_utc - timedelta(hours=7)

        today_utc_str = now_utc.strftime("%Y-%m-%d")
        today_pt_str = now_pt.strftime("%Y-%m-%d")

        # Check Google reset
        if self.last_reset_dates.get("google") != today_pt_str:
            for entity in self.entities.values():
                if entity.provider == "google":
                    entity.consumed_today = 0
                    if entity.status == "QUOTA_EXHAUSTED":
                        entity.status = "ACTIVE"
            self.last_reset_dates["google"] = today_pt_str
            logger.info("🌅 [RESET CLOCK] Google GenAI daily quota reset to 0 (Pacific Midnight reached).")

        # Check UTC providers (Groq, GitHub, OpenRouter)
        utc_providers = ["groq", "github", "openrouter"]
        for prov in utc_providers:
            if self.last_reset_dates.get(prov) != today_utc_str:
                for entity in self.entities.values():
                    if entity.provider == prov:
                        entity.consumed_today = 0
                        if entity.status == "QUOTA_EXHAUSTED":
                            entity.status = "ACTIVE"
                self.last_reset_dates[prov] = today_utc_str
                logger.info(f"🌅 [RESET CLOCK] {prov.title()} daily quota reset to 0 (UTC Midnight reached).")

    def sniff_headers(self, entity_id: str, headers: Dict[str, Any]):
        """
        Captures upstream HTTP rate limit headers dynamically on actual calls.
        Writes true upstream limits and remaining quotas directly into memory without hardcoded guesses.
        """
        if not headers or entity_id not in self.entities:
            return

        entity = self.entities[entity_id]
        normalized = {k.lower(): str(v) for k, v in headers.items()}

        # 1. RPM / TPM Sniffing
        rpm_limit = normalized.get("x-ratelimit-limit-requests") or normalized.get("x-ratelimit-limit")
        if rpm_limit and rpm_limit.isdigit():
            val = int(rpm_limit)
            if val > 0 and val != entity.max_rpm:
                logger.info(f"📡 [HEADER SNIFFER] {entity_id} RPM ceiling calibrated: {entity.max_rpm} -> {val}")
                entity.max_rpm = val

        # 2. Remaining Requests Sniffing
        remaining = normalized.get("x-ratelimit-remaining-requests") or normalized.get("x-ratelimit-remaining")
        if remaining and remaining.isdigit():
            rem_val = int(remaining)
            if entity.max_rpd > 0:
                calc_consumed = max(0, entity.max_rpd - rem_val)
                entity.consumed_today = calc_consumed

        # 3. Reset Timing / Retry-After Sniffing
        reset_time = normalized.get("x-ratelimit-reset-requests") or normalized.get("retry-after")
        if reset_time:
            try:
                if reset_time.endswith("s"):
                    secs = float(reset_time[:-1])
                elif reset_time.replace(".", "", 1).isdigit():
                    secs = float(reset_time)
                else:
                    secs = 60.0
                entity.reset_epoch = time.time() + secs
            except Exception:
                pass

        self.persist()

    update_from_headers = sniff_headers

    def record_call_success(self, entity_id: str, task_type: str, latency: float, quality_rating: float = 9.0):
        """Updates EMA quality score, EMA latency, and increments daily consumption."""
        if entity_id not in self.entities:
            return

        entity = self.entities[entity_id]
        entity.consumed_today += 1
        entity.last_call_timestamp = time.time()
        entity.status = "ACTIVE"

        # Update EMA latency
        entity.average_latency = round(0.8 * entity.average_latency + 0.2 * latency, 2)

        # Update EMA task quality score
        current_score = entity.task_quality_scores.get(task_type, 8.0)
        new_score = round(0.8 * current_score + 0.2 * quality_rating, 2)
        entity.task_quality_scores[task_type] = new_score

        self.persist()

    def record_call_error(self, entity_id: str, status_code: int, error_msg: str):
        """4-pathway circuit breaker handling based on error classification."""
        if entity_id not in self.entities:
            return

        entity = self.entities[entity_id]
        err_lower = error_msg.lower()

        # Pathway 3: 429 Quota Exhaustion / RateLimit
        if status_code == 429 or any(x in err_lower for x in ["429", "quota", "resourceexhausted", "rate limit"]):
            entity.status = "QUOTA_EXHAUSTED"
            # If reset_epoch not sniffed, default to next UTC midnight or 4 hours
            if entity.reset_epoch <= time.time():
                entity.reset_epoch = time.time() + 14400.0
            logger.warn(f"🛑 [CIRCUIT BREAKER] {entity_id} marked QUOTA_EXHAUSTED. Reset in {int((entity.reset_epoch - time.time()) / 60)}m.")

        # Pathway 2: 503 Capacity Surge / Transient High Demand
        elif status_code == 503 or any(x in err_lower for x in ["503", "unavailable", "high demand", "overloaded"]):
            entity.status = "COOLDOWN"
            entity.cooldown_until = time.time() + 300.0  # 5-minute transient cooldown
            logger.warn(f"⏳ [CAPACITY SURGE] {entity_id} transient 503. Cooldown set for 5 minutes.")

        # Pathway 4: 404 / 410 Deprecated
        elif status_code in (404, 410) or any(x in err_lower for x in ["not found", "deprecated", "no longer available"]):
            entity.status = "DEPRECATED"
            logger.error(f"💀 [DEPRECATED] {entity_id} returned {status_code}. Permanently retired.")

        self.persist()

    def get_entity(self, entity_id: str) -> Optional[ModelEntity]:
        """Returns the ModelEntity if found, else None."""
        return self.entities.get(entity_id)

    def persist(self):
        """Flushes in-memory state to dynamic_models_registry.json."""
        try:
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "provider_reset_dates": self.last_reset_dates,
                "entities": {eid: asdict(ent) for eid, ent in self.entities.items()}
            }
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.error(f"⚠️ [QUOTA TRACKER] Failed to persist registry: {e}")


class SlidingWindowRateLimiter:
    """Enforces gentle sliding-window pacing (60s / RPM) to prevent 429 spikes."""
    @staticmethod
    def calculate_pacing_delay(entity: ModelEntity) -> float:
        rpm = max(entity.max_rpm, 1)
        min_interval = 60.0 / float(rpm)
        elapsed = time.time() - entity.last_call_timestamp
        if elapsed < min_interval:
            return round(min(min_interval - elapsed, 4.0), 3)
        return 0.0

    @staticmethod
    def pace(entity: ModelEntity):
        delay = SlidingWindowRateLimiter.calculate_pacing_delay(entity)
        if delay > 0:
            time.sleep(delay)


class ScarcityWaterfallResolver:
    """
    Ranks models strictly Best -> Worst for a task.
    Harvests scarce premium quotas first under the 85% safety cushion (reserving 3-4 calls),
    then cascades gracefully to high-capacity workhorses.
    """
    @staticmethod
    def resolve_candidates(
        task_type: str,
        tracker: DynamicQuotaTracker,
        active_providers: List[str]
    ) -> List[Tuple[ModelEntity, str]]:
        """
        Returns an ordered list of (ModelEntity, tier_label) pairs for generation dispatch.
        """
        tracker.evaluate_daily_resets()
        available: List[ModelEntity] = []

        for entity in tracker.entities.values():
            if entity.provider in active_providers and entity.is_available():
                available.append(entity)

        # Sort by task quality score descending
        available.sort(
            key=lambda e: (
                e.task_quality_scores.get(task_type, 7.0),
                -e.average_latency
            ),
            reverse=True
        )

        resolved_plan: List[Tuple[ModelEntity, str]] = []

        # Partition into scarce flagships (<50 RPD) vs high-capacity workhorses (>=50 RPD)
        for entity in available:
            is_scarce = entity.max_rpd <= 50
            under_85 = entity.is_under_scarcity_ceiling(ceiling=0.85)

            if is_scarce and under_85:
                resolved_plan.append((entity, f"{entity.entity_id} (Tier 1 Flagship Canary)"))
            elif not is_scarce:
                resolved_plan.append((entity, f"{entity.entity_id} (Tier 2 High-Capacity Workhorse)"))
            else:
                # Scarce model has exhausted its 85% ceiling; place at the tail as absolute emergency backup
                resolved_plan.append((entity, f"{entity.entity_id} (Tier 3 Emergency Reserve)"))

        return resolved_plan

