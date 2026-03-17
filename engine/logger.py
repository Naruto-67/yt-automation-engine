# engine/logger.py
# Ghost Engine V26.0.0 — Multi-Module Structured Logging
import os
import sys
import logging
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)

class StructuredLogger:
    def __init__(self):
        self.logger = logging.getLogger("GhostEngine")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def _format_msg(self, emoji, module, msg, color=Fore.WHITE):
        ts = datetime.now().strftime("%H:%M:%S")
        return f"{color}{emoji} [{ts}] [{module}] {msg}{Style.RESET_ALL}"

    def engine(self, msg): print(self._format_msg("⚙️", "ENGINE", msg, Fore.CYAN))
    def research(self, msg): print(self._format_msg("🔍", "RESEARCH", msg, Fore.MAGENTA))
    def script(self, msg): print(self._format_msg("📝", "SCRIPT", msg, Fore.WHITE))
    def generation(self, msg): print(self._format_msg("🧠", "GEN", msg, Fore.YELLOW))
    def render(self, msg): print(self._format_msg("🎬", "RENDER", msg, Fore.BLUE))
    def upload(self, msg): print(self._format_msg("🚀", "UPLOAD", msg, Fore.GREEN))
    def success(self, msg): print(self._format_msg("✅", "SUCCESS", msg, Fore.GREEN))
    def info(self, msg): print(self._format_msg("ℹ️", "INFO", msg, Fore.WHITE))
    def warning(self, msg): print(self._format_msg("⚠️", "WARNING", msg, Fore.YELLOW))
    def error(self, msg): print(self._format_msg("🚨", "ERROR", msg, Fore.RED))

logger = StructuredLogger()
