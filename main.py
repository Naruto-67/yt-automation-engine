# main.py
import os
import sys
import traceback
from engine.orchestrator import Orchestrator
from scripts.discord_notifier import notify_summary, notify_error
from scripts.quota_manager import quota_manager
from engine.logger import logger

def main():
    # ─── POINT 3: SYSTEM KILL SWITCH ──────────────────────────────────────────
    # Reads from GitHub Repo Variables (GHOST_ENGINE_ENABLED)
    _SYSTEM_ENABLED = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
    
    if _SYSTEM_ENABLED == "false":
        msg = "🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. System halted by operator."
        print(msg)
        try:
            notify_summary(False, f"**Kill Switch Active**\n{msg}\nSet to `true` to resume.")
        except: pass
        sys.exit(0)
    # ──────────────────────────────────────────────────────────────────────────

    try:
        logger.engine("☀️ System Wake. V5.0 Multi-Channel Orchestrator Booting...")
        
        # Initialize and Run
        orchestrator = Orchestrator()
        orchestrator.run_pipeline()
        
        logger.success("🌙 Pipeline Cycle Finished Successfully.")
        
    except Exception as e:
        # POINT 9: Fatal Diagnosis
        tb = traceback.format_exc()
        logger.error(f"FATAL SYSTEM CRASH: {e}")
        
        # Log to persistent error file and notify Discord
        quota_manager.diagnose_fatal_error("System Core (main.py)", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
