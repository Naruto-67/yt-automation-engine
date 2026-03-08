# engine/logger.py
from datetime import datetime

class StructuredLogger:
    @staticmethod
    def _log(tag: str, message: str, level: str = "INFO"):
        timestamp = datetime.utcnow().isoformat() + "Z"
        icon = "✅" if level == "SUCCESS" else "⚠️" if level == "WARN" else "🚨" if level == "ERROR" else "⚙️"
        print(f"{icon} [{timestamp}] [{tag}] [{level}] {message}")

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
    def error(cls, msg: str): cls._log("SYSTEM", msg, "ERROR")

    @classmethod
    def success(cls, msg: str): cls._log("SYSTEM", msg, "SUCCESS")

logger = StructuredLogger()
