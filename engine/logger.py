# engine/logger.py
import os
from datetime import datetime, timezone
from engine.__version__ import __version__

_IS_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"

class StructuredLogger:
    @staticmethod
    def _log(tag: str, message: str, level: str = "INFO"):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_line = f"[{tag}] [{level}] {message}" if _IS_GITHUB else f"[{timestamp}] [{tag}] [{level}] {message}"
        try:
            print(log_line)
        except UnicodeEncodeError:
            clean_line = log_line.encode("ascii", errors="replace").decode("ascii")
            print(clean_line)

    @classmethod
    def engine(cls, msg: str, level="INFO"): cls._log("ENGINE", msg, level)
    
    @classmethod
    def research(cls, msg: str, level="INFO"): cls._log("RESEARCH", msg, level)
    
    @classmethod
    def generation(cls, msg: str, level="INFO"): cls._log("GENERATION", msg, level)
    
    @classmethod
    def render(cls, msg: str, level="INFO"): cls._log("RENDER", msg, level)
    
    @classmethod
    def publish(cls, msg: str, level="INFO"): cls._log("PUBLISH", msg, level)
    
    @classmethod
    def info(cls, msg: str): cls._log("INFO", msg, "INFO")

    @classmethod
    def warning(cls, msg: str): cls._log("WARNING", msg, "WARNING")

    @classmethod
    def warn(cls, msg: str): cls._log("WARNING", msg, "WARNING")

    @classmethod
    def error(cls, msg: str): cls._log("SYSTEM", msg, "ERROR")

    @classmethod
    def debug(cls, msg: str):
        if os.environ.get("GHOST_DEBUG", "").lower() in ("true", "1"):
            cls._log("DEBUG", msg, "DEBUG")

    @classmethod
    def success(cls, msg: str): cls._log("SYSTEM", msg, "SUCCESS")

logger = StructuredLogger()

def print_phase_box(phase_num: int, phase_title: str, details: str = ""):
    line_w = 80
    if phase_num > 0:
        header = f"PHASE {phase_num}: {phase_title.upper()}"
    else:
        header = phase_title
    if details:
        header += f" — {details}"
    print(f"\n{'=' * line_w}")
    print(header)
    print(f"{'=' * line_w}\n")


