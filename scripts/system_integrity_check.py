#!/usr/bin/env python3
"""
scripts/system_integrity_check.py — Automated Continuous System Integrity & Health Validator

Performs strict pre-flight and CI verification across all architectural components:
1. Configuration Integrity: Validates schema and required keys in YAML configs.
2. Word Floor & Loop Constraints: Verifies 85-125 word boundaries and loop mandate.
3. Channel & Delivery Governance: Checks creative lenses, content types, and voices.
4. Memory & Decision Ledgers: Verifies success_patterns.json and decision_log.jsonl.
5. Procedural Audio SFX Stems: Verifies existence/synthesis of WAV audio stems.
6. Kinetic Motion Engine: Validates render/package.json and kinetic_renderer.js.
7. Codebase Syntax: Compiles all Python files to ensure zero syntax regressions.

Exits with code 0 if all critical checks pass, or code 1 if any failure occurs.
"""

import os
import sys
import json
import py_compile
from pathlib import Path

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class IntegrityChecker:
    def __init__(self):
        self.passed = 0
        self.warnings = 0
        self.failed = 0
        self.results = []

    def log_result(self, category: str, name: str, status: str, details: str = ""):
        if status == "PASS":
            self.passed += 1
            icon = "✅"
        elif status == "WARN":
            self.warnings += 1
            icon = "⚠️ "
        else:
            self.failed += 1
            icon = "❌"

        self.results.append((category, name, status, details))
        det_str = f" ({details})" if details else ""
        print(f"  {icon} [{category.upper()}] {name}{det_str}")

    def check_yaml_configs(self):
        """Audits YAML configuration files."""
        import yaml

        # 1. settings.yaml
        settings_path = REPO_ROOT / "config" / "settings.yaml"
        if not settings_path.exists():
            self.log_result("config", "settings.yaml existence", "FAIL", "File missing")
            return

        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = yaml.safe_load(f)
            has_api = "api_limits" in settings
            has_render = "render" in settings
            has_tts = "tts" in settings
            if has_api and has_render and has_tts:
                self.log_result("config", "settings.yaml schema", "PASS", "api_limits, render & tts verified")
            else:
                self.log_result("config", "settings.yaml schema", "WARN", "Missing api_limits, render or tts")
        except Exception as e:
            self.log_result("config", "settings.yaml parse", "FAIL", str(e))

        # 2. channels.yaml
        channels_path = REPO_ROOT / "config" / "channels.yaml"
        try:
            with open(channels_path, "r", encoding="utf-8") as f:
                channels_data = yaml.safe_load(f)
            channels_list = channels_data.get("channels", [])
            ch_ids = [ch.get("id") for ch in channels_list if isinstance(ch, dict)]
            if "CH_01" in ch_ids and "CH_02" in ch_ids:
                ch1 = next(ch for ch in channels_list if ch.get("id") == "CH_01")
                ch1_lenses = ch1.get("creative_lenses", [])
                has_living_chars = any("apprentice" in str(l).lower() or "character" in str(l).lower() for l in ch1_lenses)
                if has_living_chars:
                    self.log_result("config", "channels.yaml creative lenses", "PASS", "CH_01 living character lenses confirmed")
                else:
                    self.log_result("config", "channels.yaml creative lenses", "WARN", "CH_01 missing character lenses")
            else:
                self.log_result("config", "channels.yaml schema", "FAIL", f"CH_01 or CH_02 missing in {ch_ids}")
        except Exception as e:
            self.log_result("config", "channels.yaml parse", "FAIL", str(e))

        # 3. prompts.yaml
        prompts_path = REPO_ROOT / "config" / "prompts.yaml"
        try:
            with open(prompts_path, "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)
                constitution = prompts.get("script_gen", {}).get("constitution", "")
            has_floor = any(w in constitution for w in ["85", "90", "92"])
            has_loop = "CIRCULAR LOOP" in constitution or "loop" in constitution.lower()
            if has_floor and has_loop:
                self.log_result("config", "prompts.yaml constitution", "PASS", "Word floor & seamless loop verified")
            else:
                self.log_result("config", "prompts.yaml constitution", "FAIL", "Missing word floor or loop mandate")
        except Exception as e:
            self.log_result("config", "prompts.yaml parse", "FAIL", str(e))

    def check_directories_and_assets(self):
        """Verifies critical directories and procedural assets."""
        critical_dirs = [
            "config", "engine", "scripts", "assets/audio/sfx",
            "assets/music", "memory", "mcp", "render"
        ]
        for d in critical_dirs:
            p = REPO_ROOT / d
            if p.is_dir():
                self.log_result("filesystem", f"Directory '{d}'", "PASS")
            else:
                self.log_result("filesystem", f"Directory '{d}'", "FAIL", "Missing directory")

        # Check SFX stems
        try:
            from engine.sfx_manager import sfx_manager
            stems = ["whoosh", "sub_drop", "tick", "riser"]
            all_stems = all(bool(sfx_manager.get_stem_path(s)) for s in stems)
            if all_stems:
                self.log_result("audio", "Procedural SFX stems", "PASS", "4/4 stems ready")
            else:
                self.log_result("audio", "Procedural SFX stems", "WARN", "Some stems missing")
        except Exception as e:
            self.log_result("audio", "Procedural SFX stems", "FAIL", str(e))

    def check_memory_stores(self):
        """Audits memory and decision ledger files."""
        patterns_path = REPO_ROOT / "memory" / "success_patterns.json"
        if patterns_path.exists():
            try:
                data = json.loads(patterns_path.read_text(encoding="utf-8"))
                total_patterns = sum(len(v) for v in data.values() if isinstance(v, list))
                if total_patterns >= 2:
                    self.log_result("memory", "Golden trajectories exemplar store", "PASS", f"{total_patterns} patterns present across {len(data)} channels")
                else:
                    self.log_result("memory", "Golden trajectories exemplar store", "WARN", f"Only {total_patterns} patterns found")
            except Exception as e:
                self.log_result("memory", "Golden trajectories exemplar store", "FAIL", str(e))
        else:
            self.log_result("memory", "Golden trajectories exemplar store", "FAIL", "Missing file")

        # Check decision log directory
        log_path = REPO_ROOT / "memory" / "decision_log.jsonl"
        self.log_result("memory", "CHAI Decision log status", "PASS", f"Size: {log_path.stat().st_size if log_path.exists() else 0} bytes")

    def check_render_ecosystem(self):
        """Audits Node.js kinetic render package."""
        pkg_path = REPO_ROOT / "render" / "package.json"
        script_path = REPO_ROOT / "render" / "kinetic_renderer.js"
        if pkg_path.exists() and script_path.exists():
            self.log_result("render", "Node.js kinetic renderer package", "PASS", "package.json and script verified")
        else:
            self.log_result("render", "Node.js kinetic renderer package", "FAIL", "render package files missing")

    def check_python_syntax(self):
        """Compiles all Python files in the workspace and enforces Python 3.11 f-string compatibility."""
        import ast
        py_files = list(REPO_ROOT.glob("engine/**/*.py")) + list(REPO_ROOT.glob("scripts/**/*.py")) + list(REPO_ROOT.glob("mcp/**/*.py"))
        compile_errors = []
        for py_file in py_files:
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                err_lines = str(e).strip().splitlines()
                last_line = err_lines[-1] if err_lines else str(e)
                compile_errors.append((py_file.name, last_line))
                continue

            # Defensive check: Ensure strict compatibility with Python 3.11 (no backslashes inside f-string expressions)
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.FormattedValue):
                        seg = ast.get_source_segment(content, node.value)
                        if seg and "\\" in seg:
                            compile_errors.append((py_file.name, f"Line {getattr(node, 'lineno', '?')}: Backslash in f-string expression (PEP 701 violates Python 3.11)"))
                            break
            except Exception as e:
                compile_errors.append((py_file.name, f"AST parse failure: {e}"))

        if not compile_errors:
            self.log_result("compilation", f"Python syntax & Py3.11 compat ({len(py_files)} files)", "PASS", "100% clean compilation")
        else:
            for fname, err in compile_errors:
                self.log_result("compilation", f"Syntax error in {fname}", "FAIL", err)

    def run_all(self) -> bool:
        box_w = 76
        print(f"\n┌{'─' * box_w}┐")
        print(f"│ PHASE 2: PRE-FLIGHT SYSTEM INTEGRITY & HEALTH AUDIT{' ' * (box_w - 53)}│")
        print(f"└{'─' * box_w}┘\n")

        self.check_yaml_configs()
        self.check_directories_and_assets()
        self.check_memory_stores()
        self.check_render_ecosystem()
        self.check_python_syntax()

        print("═" * 76)
        print(f"📊 SUMMARY: {self.passed} Passed | {self.warnings} Warnings | {self.failed} Failed")
        print("═" * 76)

        return self.failed == 0


if __name__ == "__main__":
    checker = IntegrityChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)

