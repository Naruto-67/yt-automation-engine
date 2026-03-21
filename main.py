# main.py
import os
import sys
import warnings
import traceback

# ── Suppress known harmless deprecation warnings from upstream dependencies ──
# torch.nn.utils.weight_norm is deprecated inside Kokoro's model — not fixable
# from our side without patching Kokoro source.
warnings.filterwarnings(
    "ignore",
    message=".*weight_norm.*deprecated.*",
    category=FutureWarning,
    module="torch",
)
# Kokoro LSTM uses dropout=0.2 with num_layers=1 — harmless, upstream issue.
warnings.filterwarnings(
    "ignore",
    message=".*dropout option adds dropout.*",
    category=UserWarning,
    module="torch",
)
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
