# main.py
import os
import sys
from engine.orchestrator import Orchestrator
from scripts.discord_notifier import notify_summary
from scripts.quota_manager import quota_manager

def main():
    # ─── SYSTEM KILL SWITCH ────────────────────────────────────────────────────────
    _SYSTEM_ENABLED = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
    if _SYSTEM_ENABLED == "false":
        print("🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. System is halted by operator.")
        notify_summary(False, "🔴 **Kill Switch Active**\nSystem halted. Set `GHOST_ENGINE_ENABLED=true` in repo variables to resume.")
        sys.exit(0)
    # ───────────────────────────────────────────────────────────────────────────────

    try:
        # Boot the V5.0 Multi-Channel Enterprise Orchestrator
        orchestrator = Orchestrator()
        orchestrator.run_pipeline()
        
    except Exception as e:
        quota_manager.diagnose_fatal_error("System Core (main.py)", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
