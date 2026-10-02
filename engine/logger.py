# engine/logger.py — Pika Flow Unified Stopwatch Logger (v2.0)
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

_IS_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"


class PikaStage:
    SPEC = "🚀 Init & Spec Generation"
    CLIPS = "🎬 Clip Generation"
    EDITOR = "✂️ Video Editor"
    RELEASE = "📦 YouTube Release"


def format_duration(seconds: float) -> str:
    """Formats raw seconds into clean Pika Flow timing badges like [1m 42s] or [10s]."""
    total_sec = int(round(seconds))
    mins, secs = divmod(total_sec, 60)
    if mins > 0:
        return f"{mins}m {secs:02d}s"
    return f"{secs}s"


class StageTimer:
    """
    Context manager tracking wall-clock execution time per pipeline stage.
    Outputs clean Pika Flow visual milestone borders.
    """
    def __init__(self, stage_name: str, topic: Optional[str] = None):
        self.stage_name = stage_name
        self.topic = topic
        self.start_time = 0.0

    def __enter__(self):
        self.start_time = time.time()
        line_w = 80
        print(f"\n{'=' * line_w}")
        topic_suffix = f" — [{self.topic}]" if self.topic else ""
        print(f"{self.stage_name.upper()}{topic_suffix} — ⏳ STARTING")
        print(f"{'=' * line_w}\n", flush=True)

        # Notify Discord of stage start if available
        try:
            from scripts.discord_notifier import notify_pika_stage_progress
            notify_pika_stage_progress(self.stage_name, status="IN_PROGRESS", duration_str="", topic=self.topic)
        except Exception:
            pass

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        duration_str = format_duration(elapsed)
        line_w = 80

        print(f"\n{'=' * line_w}")
        if exc_type is None:
            print(f"{self.stage_name} [{duration_str}] — ✅ COMPLETED")
            status = "COMPLETED"
        else:
            print(f"{self.stage_name} [{duration_str}] — ❌ FAILED ({exc_val})")
            status = "FAILED"
        print(f"{'=' * line_w}\n", flush=True)

        # Notify Discord of stage finish if available
        try:
            from scripts.discord_notifier import notify_pika_stage_progress
            notify_pika_stage_progress(self.stage_name, status=status, duration_str=duration_str, topic=self.topic)
        except Exception:
            pass

        # Return False to let any exceptions propagate to ErrorManager
        return False


class StructuredLogger:
    """Unified system logging with zero noise."""
    @staticmethod
    def _log(tag: str, message: str, level: str = "INFO"):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_line = f"[{tag}] [{level}] {message}" if _IS_GITHUB else f"[{timestamp}] [{tag}] [{level}] {message}"
        try:
            print(log_line, flush=True)
        except UnicodeEncodeError:
            clean_line = log_line.encode("ascii", errors="replace").decode("ascii")
            print(clean_line, flush=True)

    @classmethod
    def spec(cls, msg: str): cls._log("SPEC", msg, "INFO")
    
    @classmethod
    def clips(cls, msg: str): cls._log("CLIPS", msg, "INFO")
    
    @classmethod
    def editor(cls, msg: str): cls._log("EDITOR", msg, "INFO")
    
    @classmethod
    def release(cls, msg: str): cls._log("RELEASE", msg, "INFO")
    
    @classmethod
    def info(cls, msg: str): cls._log("INFO", msg, "INFO")

    @classmethod
    def warning(cls, msg: str): cls._log("WARN", msg, "WARNING")

    @classmethod
    def warn(cls, msg: str): cls._log("WARN", msg, "WARNING")

    @classmethod
    def error(cls, msg: str): cls._log("ERROR", msg, "ERROR")

    @classmethod
    def success(cls, msg: str): cls._log("SUCCESS", msg, "SUCCESS")

    @classmethod
    def debug(cls, msg: str):
        if os.environ.get("GHOST_DEBUG", "").lower() in ("true", "1"):
            cls._log("DEBUG", msg, "DEBUG")


logger = StructuredLogger()


def print_phase_box(stage_name: str, details: str = ""):
    """Backward-compatible helper redirecting to clean banners."""
    line_w = 80
    header = f"{stage_name.upper()}"
    if details:
        header += f" — {details}"
    print(f"\n{'=' * line_w}\n{header}\n{'=' * line_w}\n", flush=True)
