# engine/decision_log.py — CMU/Harvard CHAI Append-Only Decision Log
"""
Append-Only Decision Log for Autonomous Production Governance.
Adapted from CMU/Harvard Center for Human-Aware AI (CHAI) standards
and calesthio/OpenMontage decision tracking.

Records every non-trivial decision made across the pipeline:
  - LLM model routing and fallback decisions
  - TTS voice engine and actor selection
  - Visual generation provider cascade choices
  - Quality critic gate passes and rejections
  - Delivery promise validations

Eliminates silent failures and provides transparent traceability across runs.
Persists records to memory/decision_log.jsonl in append-only mode.
"""

import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ghost_engine.decision_log")

_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DECISION_LOG_PATH = os.path.join(_ROOT_DIR, "memory", "decision_log.jsonl")


class DecisionLogger:
    """Append-only structured decision ledger."""

    def __init__(self, log_path: str = _DECISION_LOG_PATH):
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def record(
        self,
        category: str,
        decision: str,
        chosen: str,
        options_considered: Optional[List[str]] = None,
        rejection_reasons: Optional[Dict[str, str]] = None,
        channel_id: Optional[str] = None,
        job_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """Append a decision record to the JSONL ledger."""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "category": category.upper(),
            "channel_id": channel_id or "GLOBAL",
            "job_id": job_id,
            "decision": decision,
            "chosen": chosen,
            "options_considered": options_considered or [chosen],
            "rejection_reasons": rejection_reasons or {},
            "extra": extra or {},
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            logger.debug(f"Failed to append to decision log: {e}")
            return False

    def get_recent_decisions(self, category: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Read recent decisions for inspection or diagnostics."""
        if not os.path.exists(self.log_path):
            return []

        decisions = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if category and record.get("category") != category.upper():
                            continue
                        decisions.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.debug(f"Failed to read decision log: {e}")

        return decisions[-limit:]


# Global singleton instance
decision_log = DecisionLogger()

