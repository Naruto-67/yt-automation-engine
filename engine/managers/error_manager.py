"""
engine/managers/error_manager.py — Centralized Error Management System (v2.0)
Single global interception, triage, and recovery hub for the automation pipeline.
"""

import sys
import time
import os
import traceback
import logging
from typing import Callable, Any, Optional, TypeVar

T = TypeVar("T")

logger = logging.getLogger("ErrorManager")


class ErrorCategory:
    RECOVERABLE = "RECOVERABLE"
    FATAL = "FATAL"


class PipelineError(Exception):
    """Base exception for pipeline errors."""
    def __init__(self, message: str, category: str = ErrorCategory.FATAL, original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.category = category
        self.original_exception = original_exception


class RecoverableError(PipelineError):
    """An error that can be resolved via backoff, retry, or provider failover."""
    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message, category=ErrorCategory.RECOVERABLE, original_exception=original_exception)


class FatalError(PipelineError):
    """An unrecoverable condition requiring immediate clean pipeline termination."""
    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message, category=ErrorCategory.FATAL, original_exception=original_exception)


class ErrorManager:
    """Centralized Error Handling Brain."""

    @staticmethod
    def classify_exception(exc: Exception) -> str:
        """Categorize an arbitrary exception into RECOVERABLE or FATAL."""
        if isinstance(exc, RecoverableError):
            return ErrorCategory.RECOVERABLE
        if isinstance(exc, FatalError):
            return ErrorCategory.FATAL

        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()

        # Rate limits, timeouts, temporary server glitches
        recoverable_signals = [
            "429", "rate limit", "too many requests", "resource exhausted",
            "500", "502", "503", "504", "bad gateway", "service unavailable",
            "timeout", "timed out", "connection reset", "connection refused",
            "temporary failure", "try again", "retry-after"
        ]

        if any(sig in msg or sig in exc_type for sig in recoverable_signals):
            return ErrorCategory.RECOVERABLE

        return ErrorCategory.FATAL

    @classmethod
    def execute_with_retry(
        cls,
        operation: Callable[..., T],
        context_name: str,
        max_retries: int = 4,
        initial_backoff: float = 2.0,
        backoff_factor: float = 2.0,
        on_fallback: Optional[Callable[[], T]] = None
    ) -> T:
        """
        Executes a callable with smart exponential backoff triage.
        If all retries fail and a fallback callable is provided, executes fallback.
        """
        attempt = 0
        backoff = initial_backoff

        while attempt < max_retries:
            try:
                return operation()
            except Exception as e:
                attempt += 1
                category = cls.classify_exception(e)

                if category == ErrorCategory.RECOVERABLE and attempt < max_retries:
                    retry_after = cls._extract_retry_after(e)
                    sleep_time = retry_after if retry_after else backoff
                    
                    print(f"⚠️ [RETRYING] {context_name} (Attempt {attempt}/{max_retries}) | Reason: {e} | Backing off {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    backoff *= backoff_factor
                else:
                    # If recoverable exhausted, try fallback if available
                    if on_fallback and category == ErrorCategory.RECOVERABLE:
                        print(f"🔄 [FAILOVER] {context_name} exhausted retries. Invoking secondary fallback...")
                        try:
                            return on_fallback()
                        except Exception as fallback_err:
                            cls.handle_fatal_error(fallback_err, context=f"{context_name} (Fallback)")
                    
                    cls.handle_fatal_error(e, context=context_name)

        raise FatalError(f"Operation {context_name} failed after {max_retries} retries.")

    @classmethod
    def handle_fatal_error(cls, exc: Exception, context: str) -> None:
        """Logs the fatal error, triggers an emergency Discord alert, and exits cleanly with code 1."""
        error_msg = f"❌ [FATAL ERROR] Stage: {context} | Error: {str(exc)}"
        print(f"\n{'='*70}\n{error_msg}\n{'='*70}", file=sys.stderr)
        
        # Write full stacktrace to output/debug.log
        os.makedirs("output", exist_ok=True)
        with open(os.path.join("output", "debug.log"), "a", encoding="utf-8") as f:
            f.write(f"\n--- FATAL ERROR in {context} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(traceback.format_exc())

        # Attempt Discord alert notification
        cls._send_discord_alert(context, str(exc))

        # Clean termination
        sys.exit(1)

    @staticmethod
    def _extract_retry_after(exc: Exception) -> Optional[float]:
        """Check if exception response contains a standard Retry-After header."""
        if hasattr(exc, "response") and exc.response is not None:
            headers = getattr(exc.response, "headers", {})
            retry_header = headers.get("Retry-After") or headers.get("retry-after")
            if retry_header:
                try:
                    return float(retry_header)
                except ValueError:
                    pass
        return None

    @staticmethod
    def _send_discord_alert(stage: str, details: str) -> None:
        """Sends an immediate error card to Discord webhook if configured."""
        webhook_url = os.environ.get("DISCORD_WEBHOOK")
        if not webhook_url:
            return

        try:
            import requests
            payload = {
                "embeds": [{
                    "title": f"🚨 Pipeline Failure in {stage}",
                    "description": f"```{details[:1000]}```",
                    "color": 15158332, # Red
                    "footer": {"text": "Ghost Engine v2.0 • Error Manager"}
                }]
            }
            requests.post(webhook_url, json=payload, timeout=5)
        except Exception:
            pass # Avoid cascading error on alert failure

