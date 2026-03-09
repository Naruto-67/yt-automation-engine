# engine/storage_manager.py — Ghost Engine V6.3
import os
from datetime import datetime
from engine.database import db
from engine.config_manager import config_manager
from engine.logger import logger
from scripts.discord_notifier import notify_storage_report

_ROOT    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MEM_DIR = os.path.join(_ROOT, "memory")

def _get_db_size_kb() -> int:
    db_path = db.db_path
    if os.path.exists(db_path):
        return int(os.path.getsize(db_path) / 1024)
    return 0

def _get_repo_size_mb() -> float:
    total = 0
    for root, _, files in os.walk(_ROOT):
        if any(x in root for x in [".git", "__pycache__", ".venv"]):
            continue
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total / (1024 * 1024)

def _trim_error_log(max_mb: float = 1.0):
    log_path = os.path.join(_MEM_DIR, "error_log.txt")
    if not os.path.exists(log_path):
        return
    if os.path.getsize(log_path) > (max_mb * 1024 * 1024):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            with open(log_path, "w", encoding="utf-8") as f:
                f.writelines(lines[len(lines) // 2:])
            logger.engine("✂️ Trimmed error_log.txt")
        except Exception as e:
            logger.error(f"Failed to trim error_log.txt: {e}")

def run_housekeeping():
    logger.engine("🧹 [STORAGE] Starting weekly housekeeping...")
    settings = config_manager.get_settings()
    stor     = settings.get("storage", {})

    prune_days    = stor.get("db_prune_after_days", 30)
    max_log_mb    = stor.get("error_log_max_mb", 1.0)

    # 1. Prune old DB records
    jobs_pruned = db.prune_old_jobs(days=prune_days)
    logger.engine(f"└ Pruned {jobs_pruned} old DB jobs.")

    # 2. Vacuum DB to reclaim space
    try:
        with db._connect() as conn:
            conn.execute("VACUUM")
        logger.engine("└ DB vacuumed.")
    except Exception as e:
        logger.error(f"DB vacuum failed: {e}")

    # 3. Trim logs
    _trim_error_log(max_mb=max_log_mb)

    # Note: topic_archive SQLite table is NEVER pruned by design 
    # to maintain perfect Jaccard deduplication across years of production.

    # 4. Measure sizes
    db_size_kb   = _get_db_size_kb()
    repo_size_mb = _get_repo_size_mb()

    logger.success(
        f"Housekeeping complete. "
        f"DB: {db_size_kb} KB | Repo: {repo_size_mb:.1f} MB | "
        f"Jobs pruned: {jobs_pruned} | Topics preserved: All Time"
    )

    # Re-use topics_trimmed=0 to not break Discord API signature
    notify_storage_report(db_size_kb, repo_size_mb, jobs_pruned, 0)

if __name__ == "__main__":
    run_housekeeping()
