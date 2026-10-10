"""
scripts/benchmark_models.py — Empirical Multi-Model Benchmark CLI
Runs empirical functional schema probes against all discovered LLM providers,
evaluates JSON validity and roundtrip latency, and dynamically updates the priority chain.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from engine.discovery import run_discovery


def main():
    print("=" * 80)
    print("🚀 Running Empirical Model Benchmark & Dynamic Chain Generation")
    print("=" * 80)
    result = run_discovery(force=True)
    print(f"✅ Benchmark finished! Discovered & ranked {result.get('active_models_count', 0)} active models.")


if __name__ == "__main__":
    main()
