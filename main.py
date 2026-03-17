# main.py
# Ghost Engine V26.0.0 — System Entry & Safety Gateway
import os
import sys
import traceback
from engine.orchestrator import Orchestrator
from scripts.discord_notifier import notify_summary, notify_error
from scripts.quota_manager import quota_manager
from engine.logger import logger

def main():
    # ─── SYSTEM KILL SWITCH ───────────────────────────────────────────────────
    # Allows for immediate halting of all production via GitHub Repo Variables.
    # 
    _SYSTEM_ENABLED = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
    
    if _SYSTEM_ENABLED == "false":
        msg = "🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. System halted by operator."
        print(msg)
        try:
            # Notify Discord that the system has been manually disabled
            notify_summary(False, f"**Kill Switch Active**\n{msg}\nSet to `true` to resume.")
        except: 
            pass
        sys.exit(0)
    # ──────────────────────────────────────────────────────────────────────────

    try:
        logger.engine("☀️ System Wake. Ghost Engine V26.0.0 Orchestrator Booting...")
        
        # Initialize the Command Center [cite: 10]
        orchestrator = Orchestrator()
        
        # Execute the multi-channel production pipeline
        orchestrator.run_pipeline()
        
        logger.success("🌙 Pipeline Cycle Finished Successfully.")
        
    except Exception as e:
        # FATAL DIAGNOSIS 
        # In the event of a core failure, capture the traceback and notify the operator.
        tb = traceback.format_exc()
        logger.error(f"FATAL SYSTEM CRASH: {e}")
        
        # Log the incident to persistent memory and dispatch a Discord alert
        quota_manager.diagnose_fatal_error("System Core (main.py)", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
