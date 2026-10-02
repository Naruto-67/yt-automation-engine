# main.py — Entrypoint for Autonomous YouTube Engine (v2.0)
import os
import sys
import argparse
import traceback

from engine.logger import logger, print_phase_box
from engine.managers.error_manager import ErrorManager
from engine.managers.health_manager import HealthManager


def main():
    # ── POINT 1: KILL SWITCH & RUNTIME MODE ───────────────────────────────────
    _system_enabled = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
    _event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")

    if _system_enabled == "false":
        print("🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. System halted by operator.")
        sys.exit(0)
    elif _system_enabled == "test" and _event_name == "schedule":
        print("🔴 [TEST MODE] Scheduled cron run detected while in Test Mode. Halting automatically.")
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Autonomous YouTube Engine (v2.0)")
    parser.add_argument(
        "--stage",
        default="all",
        choices=["all", "spec", "clips", "editor", "release"],
        help="Pipeline stage to execute (default: all)"
    )
    parser.add_argument(
        "--type",
        default="short",
        choices=["short", "long"],
        help="Video profile format: short (9:16) or long (16:9)"
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run in test mode (bypasses YouTube upload and database updates)"
    )
    args = parser.parse_args()

    if args.test_mode:
        os.environ["TEST_MODE"] = "true"
        print("🧪 [TEST MODE] Activated via CLI flag. Zero YouTube API / Database mutation.")

    print_phase_box(1, "Engine Boot & Pre-Flight Checks", f"Stage: {args.stage.upper()} | Type: {args.type.upper()}")

    # Preflight Environment Checks
    ok, issues = HealthManager.run_preflight_checks()
    if not ok and os.environ.get("TEST_MODE", "false").lower() != "true":
        logger.warning(f"⚠️ Pre-flight warnings detected: {issues}")

    try:
        if args.stage in ("all", "spec"):
            from engine.managers.pipeline_runner import run_spec_stage
            run_spec_stage(video_type=args.type)

        if args.stage in ("all", "clips"):
            from engine.managers.stock_video_manager import run_clips_stage
            run_clips_stage()

        if args.stage in ("all", "editor"):
            from scripts.render_video import run_editor_stage
            run_editor_stage()

        if args.stage in ("all", "release"):
            from engine.managers.youtube_manager import run_release_stage
            run_release_stage()

        logger.success(f"🌙 Pipeline Stage '{args.stage}' Completed Successfully.")

    except Exception as e:
        ErrorManager.handle_fatal_error(e, context=f"Pipeline Stage '{args.stage}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
