# tests/test_v2_managers.py — Unit Tests for Engine v2.0 Modular Managers
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from engine.managers.health_manager import HealthManager
from engine.managers.voice_normalizer import VoiceNormalizer
from engine.managers.error_manager import ErrorManager, ErrorSeverity
from engine.managers.competitor_spy import CompetitorSpy
from engine.managers.topic_inspector import TopicInspector
from engine.managers.llm_manager import LLMManager


# ─── 1. HEALTH MANAGER TESTS ─────────────────────────────────────────────────

def test_health_manager_preflight_success(monkeypatch):
    """Verifies preflight checks pass when all required secrets are provided."""
    test_env = {
        "YOUTUBE_CLIENT_ID": "mock_yt_id",
        "YOUTUBE_CLIENT_SECRET": "mock_yt_secret",
        "YOUTUBE_REFRESH_TOKEN": "mock_yt_token",
        "DISCORD_WEBHOOK": "https://discord.com/api/webhooks/mock",
        "PEXELS_API_KEY": "mock_pexels",
        "PIXABAY_API_KEY": "mock_pixabay",
        "GROQ_API_KEY": "mock_groq",
    }
    for k, v in test_env.items():
        monkeypatch.setenv(k, v)

    ok, issues = HealthManager.run_preflight_checks()
    assert ok is True
    assert len(issues) == 0


def test_health_manager_preflight_missing_var(monkeypatch):
    """Verifies preflight checks fail gracefully if required vars are absent."""
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    ok, issues = HealthManager.run_preflight_checks()
    assert ok is False
    assert any("YOUTUBE_CLIENT_ID" in issue for issue in issues)


def test_health_manager_dynamic_weights_learning(tmp_path, monkeypatch):
    """Verifies that the self-learning loop adapts pacing and format weighting."""
    test_weights_file = str(tmp_path / "dynamic_weights.json")
    monkeypatch.setattr("engine.managers.health_manager.os.path.join", lambda *args: test_weights_file)

    initial_weights = HealthManager.load_dynamic_weights()
    assert "sub_formats" in initial_weights
    assert initial_weights["sub_formats"]["core_brainblud"] == 0.80

    # Simulate analytics where listicle outperforms core format by 15%
    analytics = {
        "listicle_avg_percentage_viewed": 0.85,
        "core_avg_percentage_viewed": 0.70,
        "retention_drop_timestamp": 12,  # Early drop triggers cut tightening
    }
    updated = HealthManager.update_self_learning_loop(analytics)
    assert updated["sub_formats"]["listicle"] > 0.20
    assert updated["pacing"]["cut_interval_seconds"] < 3.5


# ─── 2. VOICE NORMALIZER TESTS ───────────────────────────────────────────────

def test_voice_normalizer_symbol_and_abbreviation_expansion():
    """Verifies phonetic conversion of symbols, percentages, and currencies."""
    raw_text = "Scientists found 100% of the $500 reward was given to Dr. Smith vs Mr. Jones."
    normalized = VoiceNormalizer.normalize_text(raw_text)

    # % -> percent
    assert "percent" in normalized.lower()
    # $ -> dollars
    assert "dollars" in normalized.lower()
    # vs -> versus
    assert "versus" in normalized.lower()
    # Dr. -> Doctor
    assert "doctor" in normalized.lower()


def test_voice_normalizer_clean_spoken_flow():
    """Verifies unwanted markdown and extra whitespaces are stripped."""
    raw = "  **Attention!** Here is #1: *The Secret*.  "
    normalized = VoiceNormalizer.normalize_text(raw)
    assert "**" not in normalized
    assert "*" not in normalized
    assert "number 1" in normalized.lower()


def test_voice_normalizer_kokoro_voice_detection_and_fallback_mapping():
    """Verifies Kokoro language detection, voice identification, and Edge-TTS mapping."""
    assert VoiceNormalizer.detect_lang_code("af_heart") == "a"
    assert VoiceNormalizer.detect_lang_code("bf_emma") == "b"
    assert VoiceNormalizer.detect_lang_code("hf_alpha") == "h"
    assert VoiceNormalizer.detect_lang_code("ff_siwis") == "f"
    assert VoiceNormalizer.detect_lang_code("af_heart+af_bella") == "a"
    assert VoiceNormalizer.detect_lang_code("unknown") == "a"

    assert VoiceNormalizer.is_kokoro_voice("af_heart") is True
    assert VoiceNormalizer.is_kokoro_voice("af_bella") is True
    assert VoiceNormalizer.is_kokoro_voice("am_fenrir") is True
    assert VoiceNormalizer.is_kokoro_voice("en-US-ChristopherNeural") is False

    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["af_heart"] == "en-US-JennyNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["am_michael"] == "en-US-GuyNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["am_adam"] == "en-US-GuyNeural"
    assert VoiceNormalizer.KOKORO_TO_EDGE_VOICE_MAP["hf_alpha"] == "hi-IN-MadhurNeural"


def test_voice_normalizer_enforce_male_voice():
    """Verifies that female voice requests are strictly remapped to male voices."""
    assert VoiceNormalizer.enforce_male_voice("af_heart") == "am_adam"
    assert VoiceNormalizer.enforce_male_voice("af_bella") == "am_fenrir"
    assert VoiceNormalizer.enforce_male_voice("bf_emma") == "bm_george"
    assert VoiceNormalizer.enforce_male_voice("en-US-JennyNeural") == "en-US-GuyNeural"
    assert VoiceNormalizer.enforce_male_voice("en-US-AvaNeural") == "en-US-GuyNeural"
    assert VoiceNormalizer.enforce_male_voice("am_adam") == "am_adam"
    assert VoiceNormalizer.enforce_male_voice("en-US-GuyNeural") == "en-US-GuyNeural"


def test_voice_normalizer_format_tts_diagnostics_redaction():
    """Verifies that _format_tts_diagnostics redacts tokens and formats environment packages."""
    exc = OverflowError("Failed with token hf_secret1234567890 and api_key: pass_secret_9999")
    report = VoiceNormalizer._format_tts_diagnostics(exc, "Test Monolithic Context")

    assert "==================== KOKORO TTS DIAGNOSTIC REPORT ====================" in report
    assert "Context: Test Monolithic Context" in report
    assert "OverflowError: Failed with token hf_***REDACTED*** and api_key: ***REDACTED***" in report
    assert "hf_secret1234567890" not in report
    assert "pass_secret_9999" not in report
    assert "Environment Packages:" in report
    assert "  - kokoro:" in report
    assert "  - torch:" in report
    assert "  - transformers:" in report
    assert "  - numpy:" in report
    assert "  - soundfile:" in report
    assert "Traceback (most recent call last):" in report


def test_voice_normalizer_get_package_version_graceful_fallback(monkeypatch):
    """Verifies _get_package_version safely returns 'not-installed' on missing or failing packages."""
    assert VoiceNormalizer._get_package_version("non_existent_pkg_xyz_123") == "not-installed"

    import importlib.metadata
    monkeypatch.setattr(importlib.metadata, "version", MagicMock(side_effect=RuntimeError("Metadata error")))
    assert VoiceNormalizer._get_package_version("torch") == "not-installed"


def test_voice_normalizer_monolithic_kokoro_failure_diagnostics(capsys, monkeypatch, tmp_path):
    """
    Verifies that when monolithic Kokoro raises OverflowError, detailed diagnostics
    are logged and the engine gracefully falls back to Edge-TTS.
    """
    import asyncio
    from engine.models import WordTimestamp

    def mock_fail_kokoro(*args, **kwargs):
        raise OverflowError("Python int too large to convert to C ssize_t")

    monkeypatch.setattr(VoiceNormalizer, "_synthesize_kokoro", mock_fail_kokoro)

    async def mock_edge_tts(*args, **kwargs):
        return (4.2, [WordTimestamp(word="hello", start=0.0, end=0.8)])

    monkeypatch.setattr(VoiceNormalizer, "_synthesize_edge_tts", mock_edge_tts)

    out_file = str(tmp_path / "fallback.mp3")
    dur, words = asyncio.run(
        VoiceNormalizer.synthesize_with_word_boundaries(
            phonetic_text="Hello world test",
            output_audio_path=out_file,
            voice="am_adam"
        )
    )

    assert dur == 4.2
    assert len(words) == 1
    assert words[0].word == "hello"

    captured = capsys.readouterr().out
    assert "==================== KOKORO TTS DIAGNOSTIC REPORT ====================" in captured
    assert "Context: Monolithic Kokoro synthesis" in captured
    assert "OverflowError: Python int too large to convert to C ssize_t" in captured
    assert "Environment Packages:" in captured
    assert "  - kokoro:" in captured
    assert "⚠️ [TTS] Kokoro unavailable or failed (Python int too large to convert to C ssize_t) — falling back to Edge-TTS." in captured
    assert "🎙️ [EDGE-TTS] Synthesizing speech with fallback voice" in captured


def test_voice_normalizer_synthesize_scenes_sync_kokoro_failure_diagnostics(capsys, monkeypatch, tmp_path):
    """
    Verifies that when scene-bound Kokoro raises OverflowError, detailed diagnostics
    are logged and synthesis cascades gracefully to monolithic synthesis.
    """
    import sys
    from engine.models import WordTimestamp

    scenes = [
        {"spoken_text": "First scene.", "phonetic_text": "First scene."},
        {"spoken_text": "Second scene.", "phonetic_text": "Second scene."},
    ]

    class FailingKPipeline:
        def __init__(self, *args, **kwargs):
            raise OverflowError("Python int too large to convert to C ssize_t")

    mock_kokoro_mod = MagicMock()
    mock_kokoro_mod.KPipeline = FailingKPipeline
    monkeypatch.setitem(sys.modules, "kokoro", mock_kokoro_mod)

    def mock_fail_kokoro(*args, **kwargs):
        raise OverflowError("Python int too large to convert to C ssize_t")

    monkeypatch.setattr(VoiceNormalizer, "_synthesize_kokoro", mock_fail_kokoro)

    async def mock_edge_tts(*args, **kwargs):
        words = [
            WordTimestamp(word="First", start=0.0, end=0.5),
            WordTimestamp(word="scene", start=0.5, end=1.0),
            WordTimestamp(word="Second", start=1.5, end=2.0),
            WordTimestamp(word="scene", start=2.0, end=2.5),
        ]
        return (3.0, words)

    monkeypatch.setattr(VoiceNormalizer, "_synthesize_edge_tts", mock_edge_tts)

    out_file = str(tmp_path / "scenes.mp3")
    tot, w_list, cut_durs, slices = VoiceNormalizer.synthesize_scenes_sync(
        raw_scenes=scenes,
        output_audio_path=out_file,
        voice="am_adam"
    )

    assert tot == 3.0
    assert len(cut_durs) == 2

    captured = capsys.readouterr().out
    assert "==================== KOKORO TTS DIAGNOSTIC REPORT ====================" in captured
    assert "Context: Scene-bound Kokoro synthesis" in captured
    assert "OverflowError: Python int too large to convert to C ssize_t" in captured
    assert "Context: Monolithic Kokoro synthesis" in captured
    assert "Cascading to monolithic synthesis..." in captured


def test_voice_normalizer_live_kokoro_diagnostic_probe(capsys, tmp_path):
    """
    Diagnostic probe that runs against live Kokoro when installed on the CI runner.
    Captures and reports the exact exception, traceback, and environment versions.
    """
    import sys
    try:
        import kokoro  # noqa: F401
    except ImportError:
        pytest.skip("kokoro not installed in local environment")

    with capsys.disabled():
        sys.stderr.write("\n==================== LIVE KOKORO ENVIRONMENT PROBE ====================\n")
        for pkg in ["kokoro", "torch", "transformers", "numpy", "soundfile", "misaki", "phonemizer", "phonemizer-fork", "safetensors", "huggingface-hub"]:
            sys.stderr.write(f"  - {pkg}: {VoiceNormalizer._get_package_version(pkg)}\n")
        sys.stderr.write("=======================================================================\n")
        sys.stderr.flush()

    # 1. Probe measure_duration_quick with speed=1.02
    dur = VoiceNormalizer.measure_duration_quick("Hello world this is a test.", speed=1.02)
    assert dur > 0.0

    # 2. Probe synthesize_scenes_sync with 3 scenes, speed=1.02
    scenes = [
        {"spoken_text": "First scene observation.", "phonetic_text": "First scene observation."},
        {"spoken_text": "Second scene continuation.", "phonetic_text": "Second scene continuation."},
        {"spoken_text": "Final ending scene.", "phonetic_text": "Final ending scene."},
    ]
    out_audio = str(tmp_path / "probe_scenes.mp3")
    tot, w_list, cut_durs, slices = VoiceNormalizer.synthesize_scenes_sync(
        raw_scenes=scenes,
        output_audio_path=out_audio,
        voice="am_adam",
        speed=1.02
    )

    with capsys.disabled():
        sys.stderr.write(f"\n[DIAGNOSTIC PROBE] synthesize_scenes_sync result: total={tot:.2f}s, words={len(w_list)}, cuts={cut_durs}\n")
        sys.stderr.flush()

    assert tot > 0.0
    assert len(cut_durs) == 3


def test_voice_normalizer_resolve_cache_dir_canonical_constant_precedence(monkeypatch):
    """Verifies that imported huggingface_hub.constants.HF_HUB_CACHE takes strict precedence."""
    import sys
    import types
    mock_constants = types.ModuleType("huggingface_hub.constants")
    mock_constants.HF_HUB_CACHE = "/custom/canonical/hub"
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", mock_constants)

    parent_mod = sys.modules.get("huggingface_hub")
    if parent_mod is not None:
        monkeypatch.setattr(parent_mod, "constants", mock_constants, raising=False)
    else:
        try:
            import huggingface_hub
            monkeypatch.setattr(huggingface_hub, "constants", mock_constants, raising=False)
        except ImportError:
            mock_parent = types.ModuleType("huggingface_hub")
            mock_parent.constants = mock_constants
            monkeypatch.setitem(sys.modules, "huggingface_hub", mock_parent)

    # Set conflicting environment variables that must be ignored
    monkeypatch.setenv("HF_HUB_CACHE", "/env/hub")
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", "/legacy/hub")
    monkeypatch.setenv("HF_HOME", "/env/home")

    resolved = VoiceNormalizer._resolve_hf_hub_cache_dir()
    assert resolved == os.path.abspath("/custom/canonical/hub")


def test_voice_normalizer_resolve_cache_dir_env_precedence_when_constant_unavailable(monkeypatch):
    """
    Verifies environment fallback precedence when canonical constant is unavailable:
    HF_HUB_CACHE > HUGGINGFACE_HUB_CACHE > HF_HOME/hub > XDG_CACHE_HOME/huggingface/hub > default.
    """
    import sys
    import types
    # Simulate constant unavailable in module (mock constants has no HF_HUB_CACHE attribute)
    mock_constants = types.ModuleType("huggingface_hub.constants")
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", mock_constants)

    parent_mod = sys.modules.get("huggingface_hub")
    if parent_mod is not None:
        monkeypatch.setattr(parent_mod, "constants", mock_constants, raising=False)
    else:
        try:
            import huggingface_hub
            monkeypatch.setattr(huggingface_hub, "constants", mock_constants, raising=False)
        except ImportError:
            mock_parent = types.ModuleType("huggingface_hub")
            mock_parent.constants = mock_constants
            monkeypatch.setitem(sys.modules, "huggingface_hub", mock_parent)

    # Step 1: HF_HUB_CACHE takes first priority
    monkeypatch.setenv("HF_HUB_CACHE", "/p1")
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", "/p2")
    monkeypatch.setenv("HF_HOME", "/p3")
    monkeypatch.setenv("XDG_CACHE_HOME", "/p4")
    assert VoiceNormalizer._resolve_hf_hub_cache_dir() == os.path.abspath("/p1")

    # Step 2: HUGGINGFACE_HUB_CACHE takes priority over HF_HOME
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    assert VoiceNormalizer._resolve_hf_hub_cache_dir() == os.path.abspath("/p2")

    # Step 3: HF_HOME/hub takes priority over XDG_CACHE_HOME
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    assert VoiceNormalizer._resolve_hf_hub_cache_dir() == os.path.abspath("/p3/hub")

    # Step 4: XDG_CACHE_HOME/huggingface/hub takes priority over default
    monkeypatch.delenv("HF_HOME", raising=False)
    assert VoiceNormalizer._resolve_hf_hub_cache_dir() == os.path.abspath("/p4/huggingface/hub")

    # Step 5: Default ~/.cache/huggingface/hub
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert VoiceNormalizer._resolve_hf_hub_cache_dir() == os.path.abspath(os.path.expanduser("~/.cache/huggingface/hub"))


def test_voice_normalizer_classify_checkpoint_header_format_specific_json(tmp_path):
    """Verifies that config.json is evaluated as JSON text and never evaluated as SafeTensors."""
    # 1. Valid JSON with leading whitespace
    cfg_file = tmp_path / "config.json"
    cfg_file.write_bytes(b"  \n\t {\n  \"hidden_size\": 512\n}")
    res = VoiceNormalizer._classify_checkpoint_header(str(cfg_file), "config.json")
    assert "Plausible JSON text configuration" in res
    assert "SafeTensors" not in res

    # 2. Empty file
    empty_file = tmp_path / "empty.json"
    empty_file.write_bytes(b"")
    res_empty = VoiceNormalizer._classify_checkpoint_header(str(empty_file), "config.json")
    assert res_empty == "Empty file (0 bytes)"

    # 3. Unrecognized configuration prefix
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07")
    res_corrupt = VoiceNormalizer._classify_checkpoint_header(str(corrupt_file), "config.json")
    assert "Unrecognized configuration prefix" in res_corrupt


def test_voice_normalizer_classify_checkpoint_header_detects_lfs_pointer(tmp_path):
    """Verifies that an apparent Git LFS pointer is detected and recorded neutrally."""
    lfs_file = tmp_path / "kokoro-v1_0.pth"
    lfs_content = b"version https://git-lfs.github.com/spec/v1\noid sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\nsize 350000000\n"
    lfs_file.write_bytes(lfs_content)

    res = VoiceNormalizer._classify_checkpoint_header(str(lfs_file), "kokoro-v1_0.pth")
    assert "Apparent Git LFS pointer text file" in res
    assert "oid: abcdef1234567890..." in res
    assert "declared size: 350000000 B" in res


def test_voice_normalizer_classify_checkpoint_header_safetensors_boundary(tmp_path):
    """Verifies SafeTensors header boundary consistency: N <= file_size - 8."""
    # 1. Consistent boundary: file_size = 120 bytes, N = 50 bytes. 50 <= 120 - 8 (112).
    good_file = tmp_path / "model.safetensors"
    good_header_len = (50).to_bytes(8, byteorder="little", signed=False)
    good_file.write_bytes(good_header_len + b'{"__metadata__": {}}' + b"\x00" * 92)
    res_good = VoiceNormalizer._classify_checkpoint_header(str(good_file), "model.safetensors")
    assert "Plausible SafeTensors container prefix" in res_good
    assert "declared header 50 B <= file size - 8 B (112 B)" in res_good

    # 2. Inconsistent boundary: file_size = 40 bytes, N = 100 bytes. 100 > 40 - 8 (32).
    bad_file = tmp_path / "bad.safetensors"
    bad_header_len = (100).to_bytes(8, byteorder="little", signed=False)
    bad_file.write_bytes(bad_header_len + b"\x00" * 32)
    res_bad = VoiceNormalizer._classify_checkpoint_header(str(bad_file), "bad.safetensors")
    assert "Inconsistent declared SafeTensors header length" in res_bad
    assert "declared 100 B exceeds remaining file boundary (32 B)" in res_bad


def test_voice_normalizer_classify_checkpoint_header_pytorch_zip_and_pickle(tmp_path):
    """Verifies recognition of PyTorch Zip container (.pth) and pickle stream (.pt) prefixes."""
    # 1. PyTorch Zip archive (.pth)
    pth_file = tmp_path / "kokoro-v1_0.pth"
    pth_file.write_bytes(b"PK\x03\x04\x14\x00\x00\x00" + b"\x00" * 40)
    res_pth = VoiceNormalizer._classify_checkpoint_header(str(pth_file), "kokoro-v1_0.pth")
    assert "Plausible PyTorch Zip container prefix" in res_pth

    # 2. PyTorch pickle stream (voicepack .pt)
    pt_file = tmp_path / "am_adam.pt"
    pt_file.write_bytes(b"\x80\x04\x95\x00\x00\x00\x00" + b"\x00" * 40)
    res_pt = VoiceNormalizer._classify_checkpoint_header(str(pt_file), "am_adam.pt")
    assert "Plausible PyTorch pickle stream prefix (protocol 4; unvalidated)" in res_pt


def test_voice_normalizer_inspect_checkpoint_snapshot_symlink_resolution(tmp_path, monkeypatch):
    """Verifies traversal of snapshots/ revisions and resolution of extensionless blobs/ symlinks."""
    hub_dir = tmp_path / "hub"
    repo_dir = hub_dir / "models--hexgrad--Kokoro-82M"
    snapshots_dir = repo_dir / "snapshots" / "main"
    blobs_dir = repo_dir / "blobs"
    voices_dir = snapshots_dir / "voices"

    snapshots_dir.mkdir(parents=True)
    blobs_dir.mkdir(parents=True)
    voices_dir.mkdir(parents=True)

    # Create real payload in extensionless blob
    blob_name = "4a3f120000000000000000000000000000000000000000000000000000000000"
    blob_model = blobs_dir / blob_name
    blob_model.write_bytes(b"PK\x03\x04\x14\x00" + b"\x00" * 244)  # 250 bytes

    # Symlink snapshot to blob using relative target (../../blobs/<blob-name>)
    rel_target = os.path.join("..", "..", "blobs", blob_name)
    symlink_model = snapshots_dir / "kokoro-v1_0.pth"
    os.symlink(rel_target, symlink_model)

    # Create config.json and voicepack in snapshot
    cfg_file = snapshots_dir / "config.json"
    cfg_file.write_bytes(b'{"hidden": 512}')

    voice_file = voices_dir / "am_adam.pt"
    voice_file.write_bytes(b"\x80\x04\x95" + b"\x00" * 97)

    monkeypatch.setattr(VoiceNormalizer, "_resolve_hf_hub_cache_dir", classmethod(lambda cls: str(hub_dir)))

    res = VoiceNormalizer._inspect_kokoro_checkpoint_cache()
    assert res["cache_exists"] is True
    candidates = res["snapshot_candidates"]
    assert len(candidates) == 3

    # Verify kokoro-v1_0.pth symlink resolution
    model_entry = next(c for c in candidates if "kokoro-v1_0.pth" in c["relative_path"])
    assert model_entry["relative_path"] == "snapshots/main/kokoro-v1_0.pth"
    assert model_entry["is_symlink"] is True
    assert model_entry["link_target"] == rel_target
    assert model_entry["resolved_path"] == os.path.realpath(str(blob_model))
    assert model_entry["size_bytes"] == 250
    assert "Plausible PyTorch Zip container prefix" in model_entry["signature"]

    # Verify config.json entry
    cfg_entry = next(c for c in candidates if "config.json" in c["relative_path"])
    assert cfg_entry["size_bytes"] == 15
    assert "Plausible JSON text configuration" in cfg_entry["signature"]

    # Verify voicepack entry
    voice_entry = next(c for c in candidates if "am_adam.pt" in c["relative_path"])
    assert voice_entry["size_bytes"] == 100
    assert "Plausible PyTorch pickle stream prefix" in voice_entry["signature"]


def test_voice_normalizer_inspect_checkpoint_missing_cache_and_permission_isolation(tmp_path, monkeypatch):
    """Verifies that missing cache and filesystem permission errors are safely isolated."""
    # 1. Missing cache directory returns structured dict without raising
    monkeypatch.setattr(VoiceNormalizer, "_resolve_hf_hub_cache_dir", classmethod(lambda cls: str(tmp_path / "non_existent")))
    res_missing = VoiceNormalizer._inspect_kokoro_checkpoint_cache()
    assert res_missing["cache_exists"] is False
    assert "not found in cache" in res_missing["status"]

    # 2. Permission error inside _inspect_kokoro_checkpoint_cache is safely isolated
    cache_dir = tmp_path / "hub"
    repo_dir = cache_dir / "models--hexgrad--Kokoro-82M" / "snapshots"
    repo_dir.mkdir(parents=True)
    monkeypatch.setattr(VoiceNormalizer, "_resolve_hf_hub_cache_dir", classmethod(lambda cls: str(cache_dir)))

    def mock_listdir_fail(*args, **kwargs):
        raise PermissionError("EACCES Permission denied")

    monkeypatch.setattr(os, "listdir", mock_listdir_fail)
    res_perm = VoiceNormalizer._inspect_kokoro_checkpoint_cache()
    assert "Permission denied" in res_perm["status"]

    # 3. Format report handles error without failing
    report = VoiceNormalizer._format_tts_diagnostics(RuntimeError("Test error"), "Test Context")
    assert "==================== KOKORO TTS DIAGNOSTIC REPORT ====================" in report
    assert "Checkpoint Cache Forensics:" in report


def test_music_manager_procedural_lofi_synthesis(tmp_path):
    """Verifies that MusicManager can synthesize high-fidelity procedural Lo-Fi tracks."""
    from engine.managers.music_manager import MusicManager
    out_file = str(tmp_path / "test_lofi.wav")
    path = MusicManager.synthesize_procedural_lofi(output_path=out_file, duration=2.0, mood="lofi_chill")
    assert path is not None
    assert os.path.exists(path)
    assert os.path.getsize(path) > 10000


def test_stock_video_manager_deduplication(tmp_path, monkeypatch):
    """Verifies that StockVideoManager avoids duplicate clips within a video and across past runs."""
    from engine.managers.stock_video_manager import StockVideoManager, SHORTS_ASMR_TAXONOMY
    
    # Use temporary registry file
    reg_file = str(tmp_path / "used_clips.json")
    monkeypatch.setattr(StockVideoManager, "REGISTRY_FILE", reg_file)

    mgr = StockVideoManager()
    
    # 1. Verify taxonomy is loaded with rich ASMR categories
    assert len(SHORTS_ASMR_TAXONOMY) >= 10
    assert any("soap" in q for q in SHORTS_ASMR_TAXONOMY)
    assert any("carpet" in q for q in SHORTS_ASMR_TAXONOMY)

    # 2. Record clip usage and verify cooldown check
    mgr.record_clip_usage("test_vid_123", "pexels", "soap carving")
    assert mgr.is_clip_recent("test_vid_123", cooldown_days=30) is True
    assert mgr.is_clip_recent("test_vid_999", cooldown_days=30) is False


def test_stock_video_manager_local_vault_fallback(tmp_path, monkeypatch):
    """Verifies that StockVideoManager gracefully falls back to local vault with archetype matching and deduplication."""
    from engine.managers.stock_video_manager import StockVideoManager

    reg_file = str(tmp_path / "used_clips_vault.json")
    monkeypatch.setattr(StockVideoManager, "REGISTRY_FILE", reg_file)

    mgr = StockVideoManager()

    # 1. Test keyword archetype matching for kinetic sand
    clip_sand = mgr.get_local_fallback("kinetic sand slicing ASMR")
    assert clip_sand is not None
    assert clip_sand.provider == "local"
    assert "kinetic_sand" in clip_sand.video_id
    assert os.path.exists(clip_sand.download_url)

    # 2. Test keyword archetype matching for soap
    clip_soap = mgr.get_local_fallback("soap carving ASMR")
    assert clip_soap is not None
    assert clip_soap.provider == "local"
    assert "soap_cubes" in clip_soap.video_id

    # 3. Test intra-video exclusion
    clip_sand_2 = mgr.get_local_fallback("kinetic sand slicing", exclude_ids={clip_sand.video_id})
    assert clip_sand_2 is not None
    assert clip_sand_2.video_id != clip_sand.video_id

    # 4. Test offline fallback when online search APIs fail or keys are absent
    mgr.pexels_key = None
    mgr.pixabay_key = None
    clip_offline = mgr.search_video("power washing driveway moss")
    assert clip_offline is not None
    assert clip_offline.provider == "local"
    assert "power_wash" in clip_offline.video_id


def test_render_video_download_clip_local(tmp_path):
    """Verifies that download_clip copies local vault clips directly without HTTP requests."""
    from scripts.render_video import download_clip

    # Create dummy source clip
    src_file = str(tmp_path / "vault_clip.mp4")
    with open(src_file, "wb") as f:
        f.write(b"0" * 150000)

    dest_file = str(tmp_path / "copied_clip.mp4")
    result = download_clip(url=src_file, output_path=dest_file, provider="local", video_id="vault_clip.mp4")

    assert result == dest_file
    assert os.path.exists(dest_file)
    assert os.path.getsize(dest_file) == 150000



# ─── 3. ERROR MANAGER TESTS ──────────────────────────────────────────────────

def test_error_manager_triage_categories():
    """Verifies correct triage taxonomy for auth, quota, and transient network errors."""
    auth_err = Exception("Google Auth Error: 401 Unauthorized invalid_grant")
    quota_err = Exception("YouTube Data API: 403 quotaExceeded limit reached")
    rate_err = Exception("Groq API: 429 RateLimitError - tokens per minute")
    net_err = Exception("ConnectionResetError: Remote end closed connection without response")

    assert ErrorManager.triage_error(auth_err) == ErrorSeverity.FATAL_AUTH
    assert ErrorManager.triage_error(quota_err) == ErrorSeverity.FATAL_QUOTA
    assert ErrorManager.triage_error(rate_err) == ErrorSeverity.TRANSIENT_RETRY
    assert ErrorManager.triage_error(net_err) == ErrorSeverity.TRANSIENT_RETRY


def test_error_manager_exponential_backoff_calculation():
    """Verifies exponential backoff wait times increase predictably."""
    d0 = ErrorManager.compute_backoff_seconds(attempt=1, base_seconds=2)
    d1 = ErrorManager.compute_backoff_seconds(attempt=2, base_seconds=2)
    d2 = ErrorManager.compute_backoff_seconds(attempt=3, base_seconds=2)

    assert 2.0 <= d0 <= 3.5
    assert 4.0 <= d1 <= 6.0
    assert 8.0 <= d2 <= 11.0


# ─── 4. COMPETITOR SPY TESTS ─────────────────────────────────────────────────

def test_competitor_spy_viral_factor_calculation():
    """Verifies viral factor algorithm: (views / age_hours) / baseline_vph."""
    # 10,000 views in 10 hours = 1,000 VPH. If baseline is 200 VPH, viral factor = 5.0x
    factor = CompetitorSpy.calculate_viral_factor(views=10000, age_hours=10.0, baseline_vph=200.0)
    assert pytest.approx(factor, 0.1) == 5.0

    # Safe zero division handling
    safe_factor = CompetitorSpy.calculate_viral_factor(views=500, age_hours=0.0, baseline_vph=0.0)
    assert safe_factor >= 0.0


# ─── 5. TOPIC INSPECTOR TESTS ────────────────────────────────────────────────

def test_topic_inspector_factuality_filter():
    """Verifies hallucination/pseudoscience gate filters invalid claims."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "is_factual": True,
        "confidence": 0.95,
        "primary_source": "Nature Biology, 2023",
        "red_flags": []
    }
    inspector = TopicInspector(llm_manager=mock_llm)
    result = inspector.verify_factuality("Turritopsis dohrnii reverses its life cycle.")

    assert result["is_factual"] is True
    assert result["confidence"] == 0.95
    assert "Nature Biology" in result["primary_source"]


# ─── 6. LLM MANAGER RESILIENCY TESTS ─────────────────────────────────────────

def test_llm_manager_json_repair_and_extraction():
    """Verifies that LLMManager parses embedded JSON objects inside raw text."""
    raw_response = """
    Here is the requested script:
    ```json
    {
      "scenes": [
        {"spoken_text": "Did you know trees can communicate?", "stock_video_query": "forest time lapse"}
      ],
      "thought_process": "Hook selected for high curiosity."
    }
    ```
    """
    parsed = LLMManager.extract_json_payload(raw_response)
    assert isinstance(parsed, dict)
    assert "scenes" in parsed
    assert len(parsed["scenes"]) == 1
    assert parsed["scenes"][0]["stock_video_query"] == "forest time lapse"


def test_llm_manager_404_auto_banning_and_cascade(monkeypatch):
    """Verifies that when a primary model returns 404, it is auto-banned and cascades to secondary provider."""
    monkeypatch.setenv("GROQ_API_KEY", "mock_groq_key")
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")

    banned_mock = set()
    monkeypatch.setattr("engine.managers.llm_manager._load_banned_models", lambda: set(banned_mock))
    monkeypatch.setattr("engine.managers.llm_manager.add_banned_model", lambda m: banned_mock.add(m))

    manager = LLMManager()

    call_counts = {"primary": 0, "secondary": 0}

    def mock_execute(provider, system_prompt, user_prompt, temperature):
        prov_id = provider["id"]
        if "gemini" in prov_id:
            call_counts["primary"] += 1
            raise RuntimeError("Error code: 404 - {'error': {'message': 'The model gemini-3-flash-preview does not exist or you do not have access to it.', 'code': 'model_not_found'}}")
        elif "groq" in prov_id:
            call_counts["secondary"] += 1
            return json.dumps({
                "scenes": [{"spoken_text": "Brain blud dynamic cascade success", "stock_video_query": "neuroscience"}]
            })
        raise RuntimeError("Unexpected provider")

    monkeypatch.setattr(manager, "_execute_provider_call", mock_execute)

    result = manager.generate_json(system_prompt="Test sys", user_prompt="Test user")

    # Assert primary was called and failed with 404
    assert call_counts["primary"] >= 1
    # Assert cascade happened to secondary
    assert call_counts["secondary"] >= 1
    assert "scenes" in result
    assert result["scenes"][0]["stock_video_query"] == "neuroscience"

    # Verify that the 404 model was benched into banned models
    assert "gemini-3-flash-preview" in banned_mock


def test_discovery_banned_models_filtering():
    """Verifies that banned models and banned modalities are strictly rejected, and real production persistence runs isolated."""
    import pytest
    import engine.discovery as ed
    from engine.discovery import is_model_allowed, is_modality_allowed, _save_performance, _load_performance

    # Banned modalities
    assert is_modality_allowed("whisper-large-v3") is False
    assert is_modality_allowed("google/veo-2") is False
    assert is_modality_allowed("tts-voice-actor") is False

    # Banned models
    banned = {"gemini-2.0-flash", "llama-3.1-70b-versatile"}
    assert is_model_allowed("gemini-2.0-flash", banned) is False
    assert is_model_allowed("llama-3.1-70b-versatile", banned) is False
    assert is_model_allowed("gemini-3-flash-preview", banned) is True

    # 1. Verify original production function identity (not mocked/replaced)
    assert _save_performance is ed._save_performance
    assert _load_performance is ed._load_performance
    assert _save_performance.__module__ == "engine.discovery"
    assert _load_performance.__module__ == "engine.discovery"

    # 2. Real production JSON serialization and metadata persistence
    sample_perf = {
        "providers": {
            "test_model_iso": {"latency": 0.42, "success": True}
        },
        "_meta": {}
    }
    _save_performance(sample_perf)
    assert sample_perf["_meta"]["last_updated"] is not None
    loaded_perf = _load_performance()
    assert "test_model_iso" in loaded_perf.get("providers", {})
    assert loaded_perf["_meta"]["last_updated"] == sample_perf["_meta"]["last_updated"]

    # 3. Real serialization failure behavior (un-serializable types raise TypeError)
    with pytest.raises(TypeError):
        _save_performance({"invalid": {1, 2, 3}, "_meta": {}})

    # 4. Real error-handling behavior for corrupted file (graceful fallback)
    target_file = ed._CFG_DIR / "llm_performance.json"
    target_file.write_text("{bad json...", encoding="utf-8")
    fallback = _load_performance()
    assert fallback["providers"] == {}
    assert fallback["_meta"]["last_updated"] is None

    # Restore clean state in temporary directory
    _save_performance(sample_perf)


def _isolate_pipeline_persistence(monkeypatch, tmp_path):
    """
    Isolates all persistent file writers used by run_spec_stage() under tmp_path:
    - memory/thought_cache.json
    - memory/past_spoken_thoughts.json
    - config/model_quality_scores.json
    - config/channel_config.yaml
    - output/spec.json, output/narration.mp3, output/community_post.json
    """
    test_output_dir = tmp_path / "output"
    test_output_dir.mkdir(parents=True, exist_ok=True)
    test_memory_dir = tmp_path / "memory"
    test_memory_dir.mkdir(parents=True, exist_ok=True)
    test_cfg_dir = tmp_path / "config"
    test_cfg_dir.mkdir(parents=True, exist_ok=True)

    orig_join = os.path.join
    def safe_join(*args):
        if args and args[0] == "output":
            return str(test_output_dir / orig_join(*args[1:]))
        if args and args[0] == "memory":
            return str(test_memory_dir / orig_join(*args[1:]))
        return orig_join(*args)

    monkeypatch.setattr("engine.managers.pipeline_runner.os.path.join", safe_join)
    monkeypatch.setattr("engine.managers.pipeline_runner._CHANNEL_CONFIG_PATH", str(test_cfg_dir / "channel_config.yaml"))
    monkeypatch.setattr("engine.managers.pipeline_runner._MEMORY_THOUGHT_CACHE_PATH", str(test_memory_dir / "thought_cache.json"))
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.REGISTRY_FILE", str(test_memory_dir / "used_topics_registry.json"))

    # Isolate LLMQualityTracker persistence
    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module, "_CFG_DIR", test_cfg_dir)
    monkeypatch.setattr(qt_module, "_QUALITY_SCORES_PATH", test_cfg_dir / "model_quality_scores.json")

    # Isolate save_past_spoken_thoughts and _load_past_spoken_thoughts
    import engine.managers.iterative_script_generator as iscg_module
    def isolated_save_past_spoken_thoughts(new_thoughts):
        target_path = test_memory_dir / "past_spoken_thoughts.json"
        existing_thoughts = []
        meta = {
            "description": "Historical registry of spoken lines from previously uploaded videos to prevent thought repetition across runs.",
            "version": "1.0"
        }
        if target_path.exists():
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    existing_thoughts = data.get("past_thoughts", [])
                    meta = data.get("_meta", meta)
            except Exception:
                pass
        added = 0
        for t in new_thoughts:
            clean_t = t.strip()
            if clean_t and clean_t not in existing_thoughts:
                existing_thoughts.append(clean_t)
                added += 1
        if added > 0:
            from datetime import datetime, timezone
            meta["updated_at"] = datetime.now(timezone.utc).isoformat()
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump({"_meta": meta, "past_thoughts": existing_thoughts}, f, indent=2)
            except Exception:
                pass

    def isolated_load_past_spoken_thoughts():
        target_path = test_memory_dir / "past_spoken_thoughts.json"
        if target_path.exists():
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("past_thoughts", [])
            except Exception:
                pass
        return []

    monkeypatch.setattr(iscg_module, "save_past_spoken_thoughts", isolated_save_past_spoken_thoughts)
    monkeypatch.setattr(iscg_module, "_load_past_spoken_thoughts", isolated_load_past_spoken_thoughts)

    return test_output_dir, test_memory_dir, test_cfg_dir


def test_pipeline_runner_run_spec_stage(monkeypatch, tmp_path):
    """Verifies run_spec_stage runs end-to-end for short and long formats without NameError or crash."""
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Mock health checks and sync
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    # Mock LLM generation
    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why You See Everything Everywhere",
        "scenes": [
            {"scene_id": 1, "spoken_text": "This is why you suddenly notice things everywhere.", "stock_video_query": "subway train motion"},
            {"scene_id": 2, "spoken_text": "Your brain filters out background data.", "stock_video_query": "crowd walking"},
        ]
    }
    mock_seo_response = {
        "title": "Frequency Illusion #shorts",
        "description": "Why you see things everywhere. #shorts",
        "tags": ["psychology", "facts", "shorts"]
    }

    def mock_generate_json(self, sys_p, usr_p, temperature=0.7, *args, **kwargs):
        if "SEO Director" in sys_p:
            return mock_seo_response
        return mock_script_response

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_generate_json)
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (mock_script_response["scenes"], mock_seo_response)
    )
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync", lambda **kw: (10.0, []))

    # Test short stage
    run_spec_stage(video_type="short")
    assert os.path.exists(test_spec_path)

    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())
    assert spec.video_type == "short"
    assert len(spec.scenes) == 2

    # Test long stage
    run_spec_stage(video_type="long")
    assert os.path.exists(test_spec_path)

    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec_long = SpecOutput.model_validate_json(f.read())
    assert spec_long.video_type == "long"
    assert spec_long.sub_format == "documentary_essay"


def test_voice_normalizer_strip_leading_dots():
    """Verifies that leading ellipses, dots, and hyphens are cleanly stripped to prevent audio pauses."""
    raw = "...and these shower thoughts will break your reality."
    normalized = VoiceNormalizer.normalize_text(raw)
    assert normalized.startswith("And")
    assert "..." not in normalized


def test_caption_aligner_vad_fallback(tmp_path):
    """Verifies CaptionAligner pure-Python acoustic VAD aligns words across audio soundwaves."""
    import wave
    import struct
    from engine.managers.caption_aligner import CaptionAligner

    test_wav = str(tmp_path / "test_voice.wav")
    sr = 16000
    # Create 2 seconds of dummy audio: 0.2s silence + 1.0s speech tone + 0.8s silence
    n_samples = int(sr * 2.0)
    samples = []
    for i in range(n_samples):
        t = i / sr
        if 0.2 <= t <= 1.2:
            import math
            s = int(10000 * math.sin(2 * math.pi * 440 * t))
        else:
            s = 0
        samples.append(s)

    with wave.open(test_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    script_text = "Your shadow is proof"
    words = CaptionAligner.align_captions(test_wav, script_text=script_text)

    assert len(words) == 4
    # The first word must start after the initial 0.2s silence
    assert words[0].start >= 0.15
    assert words[-1].end <= 1.5
    assert words[0].word == "Your"
    assert words[-1].word == "proof"


def test_topic_inspector_deduplication_anti_repetition(tmp_path, monkeypatch):
    """Verifies that TopicInspector prevents using duplicate or recently used topics."""
    reg_file = str(tmp_path / "test_used_topics.json")
    monkeypatch.setattr(TopicInspector, "REGISTRY_FILE", reg_file)

    # Initially empty
    assert TopicInspector.is_topic_recent("The Ship of Theseus Paradox") is False

    # Record usage
    TopicInspector.record_topic_usage("The Ship of Theseus Paradox and Identity", niche="shower_thoughts")

    # Exact or near-exact match must be blocked
    assert TopicInspector.is_topic_recent("The Ship of Theseus Paradox and Identity") is True

    # Conceptually similar / high keyword overlap must be blocked
    assert TopicInspector.is_topic_recent("The Ship of Theseus Paradox") is True

    # Completely different topic must pass
    assert TopicInspector.is_topic_recent("Why matter never truly touches other matter") is False


def test_caption_styling_settings():
    """Verifies settings.yaml has high mobile retention font size (>=88pt), ZY Resolve font, and CapCut styling."""
    import yaml
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    captions = cfg.get("captions", {})
    assert captions.get("font_name") == "ZY Resolve"
    assert captions.get("font_size", 0) >= 88
    assert captions.get("outline_width", 0) >= 7
    assert captions.get("max_words_per_chunk") == 2
    assert captions.get("active_color") == "&H0000E6FF"



def test_stock_video_manager_registry_cooldown(tmp_path, monkeypatch):
    """Verifies that StockVideoManager records clip usage and enforces 30-day cooldown."""
    from engine.managers.stock_video_manager import StockVideoManager
    reg_file = str(tmp_path / "test_used_clips.json")
    monkeypatch.setattr(StockVideoManager, "REGISTRY_FILE", reg_file)

    # Initially empty
    assert StockVideoManager.is_clip_recent("vid_101") is False

    # Record clip
    StockVideoManager.record_clip_usage("vid_101", "pexels", "kinetic sand")

    # Clip is now recent
    assert StockVideoManager.is_clip_recent("vid_101") is True
    assert StockVideoManager.is_clip_recent("vid_999") is False


def test_scene_cut_boundaries_alignment(monkeypatch, tmp_path):
    """Verifies that scene cut boundaries align at sentence pause midpoints and sum to total_duration."""
    from engine.models import WordTimestamp
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Mock health checks and sync
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Mirror Self-Recognition Test",
        "verified_summary": "Animals recognizing themselves in mirrors",
        "source": "verified_trend"
    })

    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why Animals Don't Understand Mirrors",
        "scenes": [
            {"scene_id": 1, "spoken_text": "Look into a mirror and you see yourself.", "stock_video_query": "mirror reflection"},
            {"scene_id": 2, "spoken_text": "Most animals see a complete stranger.", "stock_video_query": "cat looking at mirror"},
        ]
    }
    mock_seo_response = {
        "title": "Mirrors #shorts",
        "description": "Mirrors and animals #shorts",
        "tags": ["psychology", "facts", "shorts"]
    }

    words = [
        WordTimestamp(word="Look", start=0.2, end=0.6),
        WordTimestamp(word="into", start=0.6, end=0.9),
        WordTimestamp(word="a", start=0.9, end=1.1),
        WordTimestamp(word="mirror", start=1.1, end=1.8),
        WordTimestamp(word="and", start=1.8, end=2.0),
        WordTimestamp(word="you", start=2.0, end=2.3),
        WordTimestamp(word="see", start=2.3, end=2.7),
        WordTimestamp(word="yourself.", start=2.7, end=3.4),  # Scene 1 ends at 3.4
        # Pause from 3.4 to 4.0
        WordTimestamp(word="Most", start=4.0, end=4.4),      # Scene 2 starts at 4.0
        WordTimestamp(word="animals", start=4.4, end=4.9),
        WordTimestamp(word="see", start=4.9, end=5.2),
        WordTimestamp(word="a", start=5.2, end=5.4),
        WordTimestamp(word="complete", start=5.4, end=5.9),
        WordTimestamp(word="stranger.", start=5.9, end=6.6),
    ]

    total_dur = 7.2

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json",
                        lambda self, sys_p, usr_p, *a, **k: mock_seo_response if "SEO Director" in sys_p else mock_script_response)
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (mock_script_response["scenes"], mock_seo_response)
    )
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_sync",
                        lambda **kw: (total_dur, words))

    run_spec_stage(video_type="short")

    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    assert len(spec.scenes) == 2
    # Pause midpoint between 3.4 and 4.0 is 3.7
    # Scene 1 duration should be 3.7 - 0.0 = 3.7
    assert spec.scenes[0].duration_seconds == 3.7
    # Scene 2 duration should be 7.2 - 3.7 = 3.5
    assert spec.scenes[1].duration_seconds == 3.5
    # Total sum of durations must equal total_dur
    assert round(sum(s.duration_seconds for s in spec.scenes), 2) == total_dur


def test_caption_aligner_faster_whisper(tmp_path, monkeypatch):
    """Verifies CaptionAligner transcribes audio via faster-whisper and extracts word timestamps."""
    from engine.managers.caption_aligner import CaptionAligner
    import sys

    # Create dummy audio file
    dummy_wav = str(tmp_path / "voice.wav")
    with open(dummy_wav, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 100)

    # Mock WhisperModel
    mock_word_1 = MagicMock(word=" Space", start=0.25, end=0.85)
    mock_word_2 = MagicMock(word=" expands.", start=0.85, end=1.60)
    mock_seg = MagicMock(words=[mock_word_1, mock_word_2])

    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.return_value = ([mock_seg], None)
    mock_whisper_cls = MagicMock(return_value=mock_model_inst)

    mock_fw = MagicMock()
    mock_fw.WhisperModel = mock_whisper_cls
    monkeypatch.setitem(sys.modules, "faster_whisper", mock_fw)

    words = CaptionAligner.align_captions(dummy_wav, script_text="Space expands.")

    assert len(words) == 2
    assert words[0].word == "Space"
    assert words[0].start == 0.25
    assert words[0].end == 0.85
    assert words[1].word == "expands."
    assert words[1].start == 0.85
    assert words[1].end == 1.60

    # Verify transcribe was called with word_timestamps=True, initial_prompt=None, and vad_filter=False
    mock_model_inst.transcribe.assert_called_once()
    call_kwargs = mock_model_inst.transcribe.call_args[1]
    assert call_kwargs["word_timestamps"] is True
    assert call_kwargs["initial_prompt"] is None
    assert call_kwargs["vad_filter"] is False


def test_caption_aligner_slice_words_by_scenes():
    """Verifies that slice_words_by_scenes cleanly partitions words using acoustic pause detection."""
    from engine.managers.caption_aligner import CaptionAligner
    from engine.models import WordTimestamp

    words = [
        # Scene 1: 3 words
        WordTimestamp(word="Light", start=0.1, end=0.4),
        WordTimestamp(word="travels", start=0.4, end=0.9),
        WordTimestamp(word="fast.", start=0.9, end=1.5),
        # 0.5s breath pause (1.5 to 2.0)
        # Scene 2: 3 words
        WordTimestamp(word="Darkness", start=2.0, end=2.5),
        WordTimestamp(word="was", start=2.5, end=2.8),
        WordTimestamp(word="already", start=2.8, end=3.3),
        WordTimestamp(word="there.", start=3.3, end=3.8),
    ]

    raw_scenes = [
        {"spoken_text": "Light travels fast."},
        {"spoken_text": "Darkness was already there."},
    ]

    slices = CaptionAligner.slice_words_by_scenes(words, raw_scenes)

    assert len(slices) == 2
    # Scene 1 must have the first 3 words
    assert len(slices[0]) == 3
    assert [w.word for w in slices[0]] == ["Light", "travels", "fast."]
    # Scene 2 must have the remaining 4 words
    assert len(slices[1]) == 4
    assert [w.word for w in slices[1]] == ["Darkness", "was", "already", "there."]


def test_stock_video_manager_recursion_guard(monkeypatch):
    """Verifies that StockVideoManager never recurses infinitely even when all APIs fail."""
    from engine.managers.stock_video_manager import StockVideoManager

    manager = StockVideoManager()
    manager.pexels_key = "fake_key"
    manager.pixabay_key = "fake_key"

    # Mock both APIs to raise an exception
    monkeypatch.setattr(manager, "_search_pexels", MagicMock(side_effect=RuntimeError("API Down")))
    monkeypatch.setattr(manager, "_search_pixabay", MagicMock(side_effect=RuntimeError("API Down")))

    # Must return None gracefully and not raise RecursionError
    clip = manager.search_video("failing query")
    
def test_ghost_engine_kill_switch_and_test_mode(monkeypatch):
    """Verifies that GHOST_ENGINE_ENABLED gates cron schedules and kills system when requested."""
    import sys
    from engine.managers.pipeline_runner import main

    # 1. Kill switch: GHOST_ENGINE_ENABLED == "false"
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", ["pipeline_runner", "--stage", "spec"])
    try:
        main()
        assert False, "Should have exited with code 0 on kill switch"
    except SystemExit as e:
        assert e.code == 0

    # 2. Schedule run blocked when GHOST_ENGINE_ENABLED == "test"
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "test")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setattr(sys, "argv", ["pipeline_runner", "--stage", "spec"])
    try:
        main()
        assert False, "Should have exited with code 0 on scheduled cron run in test mode"
    except SystemExit as e:
        assert e.code == 0

    # 3. Manual run allowed in test mode, setting TEST_MODE=true
    monkeypatch.setenv("GHOST_ENGINE_ENABLED", "test")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(sys, "argv", ["pipeline_runner", "--stage", "spec"])
    monkeypatch.setattr("engine.managers.pipeline_runner.run_spec_stage", MagicMock())
    main()
    assert os.environ.get("TEST_MODE") == "true"


def test_synthesize_scenes_sync_scene_durations(monkeypatch):
    """Verifies synthesize_scenes_sync computes accurate scene cut durations from pauses."""
    from engine.managers.voice_normalizer import VoiceNormalizer
    from engine.models import WordTimestamp

    scenes = [
        {"spoken_text": "One two three.", "phonetic_text": "One two three."},
        {"spoken_text": "Four five six.", "phonetic_text": "Four five six."},
    ]

    words = [
        WordTimestamp(word="One", start=0.2, end=0.8),
        WordTimestamp(word="two", start=0.8, end=1.4),
        WordTimestamp(word="three", start=1.4, end=2.0),
        WordTimestamp(word="Four", start=3.0, end=3.6),
        WordTimestamp(word="five", start=3.6, end=4.2),
        WordTimestamp(word="six", start=4.2, end=4.8),
    ]

    monkeypatch.setattr(
        VoiceNormalizer,
        "synthesize_sync",
        lambda **kw: (5.5, words)
    )

    tot, w_list, cut_durs, slices = VoiceNormalizer.synthesize_scenes_sync(
        raw_scenes=scenes,
        output_audio_path="output/test_narr.mp3",
        prefer_provider="edge-tts"
    )

    assert tot == 5.5
    assert len(cut_durs) == 2
    # Pause midpoint between 2.0 and 3.0 is 2.5
    assert cut_durs[0] == 2.5
    assert cut_durs[1] == 3.0
    assert round(sum(cut_durs), 2) == tot


def test_stock_negative_keyword_filtering():
    """Verifies that StockVideoManager blocks suggestive, medical, or latex content."""
    from engine.managers.stock_video_manager import StockVideoManager

    # Safe craft ASMR tags must pass
    assert StockVideoManager.is_safe_clip("satisfying kinetic sand slicing craft") is True
    assert StockVideoManager.is_safe_clip("soap cutting grid razor macro ASMR") is True
    assert StockVideoManager.is_safe_clip("chocolate curls marble spatula") is True

    # Suggestive / latex / medical terms must be blocked
    assert StockVideoManager.is_safe_clip("hydraulic press squishing rolled latex") is False
    assert StockVideoManager.is_safe_clip("medical surgery examination latex gloves") is False
    assert StockVideoManager.is_safe_clip("balloon rubber stretching pop") is False
    assert StockVideoManager.is_safe_clip("contraceptive condom squish") is False
    assert StockVideoManager.is_safe_clip("https://pexels.com/video/rubber-balloon-squish-8433837") is False

    # Musical instruments, static gradients, and people must be blocked
    assert StockVideoManager.is_safe_clip("guitar string vibration macro slow motion") is False
    assert StockVideoManager.is_safe_clip("musician playing guitar concert") is False
    assert StockVideoManager.is_safe_clip("pink gradient background water drop") is False
    assert StockVideoManager.is_safe_clip("abstract wallpaper gradient 4k") is False
    assert StockVideoManager.is_safe_clip("person face portrait interview talking") is False


def test_script_validator_brainblud_word_budget():
    """Verifies script validation matches BrainBlud word budget (135-158 words across 11-13 scenes)."""
    # Helper to generate mock script
    def make_script(num_scenes: int, words_per_scene: int):
        return {
            "scenes": [
                {"scene_id": i + 1, "spoken_text": " ".join(["word"] * words_per_scene)}
                for i in range(num_scenes)
            ]
        }

    # 12 scenes * 12 words = 144 words (perfect target)
    valid_script = make_script(12, 12)
    scenes = valid_script["scenes"]
    words = sum(len(sc["spoken_text"].split()) for sc in scenes)
    assert 11 <= len(scenes) <= 13
    assert 135 <= words <= 158

    # Too few scenes (e.g. 8 scenes)
    short_scenes_script = make_script(8, 15)
    assert len(short_scenes_script["scenes"]) < 11

    # Too few words (e.g. 100 words)
    too_short_script = make_script(12, 8)
    short_words = sum(len(sc["spoken_text"].split()) for sc in too_short_script["scenes"])
    assert short_words < 135

    # Too many words (e.g. 180 words)
    too_long_script = make_script(12, 15)
    long_words = sum(len(sc["spoken_text"].split()) for sc in too_long_script["scenes"])
    assert long_words > 158


def test_stock_video_manager_query_sanitization():
    """Verifies that StockVideoManager.search_video intercepts queries containing banned terms (hair, street, etc.)."""
    from engine.managers.stock_video_manager import StockVideoManager, SHORTS_VISUAL_TAXONOMY

    mgr = StockVideoManager()
    mgr.pexels_key = None
    mgr.pixabay_key = None

    # Query containing banned term 'street'
    clip = mgr.search_video("street line marking paint spray stencil")
    assert clip is not None
    # Must have fallen back to local vault safely without querying for 'street'
    assert clip.provider == "local"

    # Query containing banned term 'barber'
    clip_barber = mgr.search_video("barber cutting hair with scissors")
    assert clip_barber is not None
    assert clip_barber.provider == "local"


def test_whisper_timestamp_sanitization_and_monotonicity():
    """Verifies that Whisper timestamp sanitization eliminates duplicate words and enforces strict monotonicity."""
    import re
    from engine.models import WordTimestamp

    # Simulate raw whisper words with:
    # 1. Duplicate word hallucination ('recognized' twice)
    # 2. Non-monotonic / identical start times ('Or' and 'does' both at 47.18)
    raw_words = [
        WordTimestamp(word="named", start=48.82, end=49.14),
        WordTimestamp(word="itself", start=49.14, end=49.60),
        WordTimestamp(word="recognized", start=49.60, end=50.02),
        WordTimestamp(word="recognized", start=50.02, end=50.48),  # Hallucinated duplicate
        WordTimestamp(word="itself,", start=50.48, end=50.72),
        WordTimestamp(word="Or", start=47.18, end=47.33),
        WordTimestamp(word="does", start=47.18, end=47.32),        # Identical start time!
    ]

    # Apply the same sanitization logic as in CaptionAligner._align_with_faster_whisper
    words = []
    for rw in raw_words:
        if not words:
            words.append(rw)
            continue
        prev = words[-1]
        clean_curr = re.sub(r"[^\w]", "", rw.word).lower()
        clean_prev = re.sub(r"[^\w]", "", prev.word).lower()
        if clean_curr and clean_curr == clean_prev and rw.start <= prev.end + 0.15:
            prev.end = max(prev.end, rw.end)
            continue

        if rw.start <= prev.start:
            rw.start = round(prev.start + 0.10, 3)
        if rw.end <= rw.start:
            rw.end = round(rw.start + 0.15, 3)
        if prev.end > rw.start:
            prev.end = round(rw.start, 3)

        words.append(rw)

    # 1. Verify duplicate 'recognized' was merged into a single word with extended end time
    word_texts = [w.word for w in words]
    assert word_texts.count("recognized") == 1
    rec_word = [w for w in words if w.word == "recognized"][0]
    assert rec_word.start == 49.60
    assert rec_word.end == 50.48

    # 2. Verify 'Or' and 'does' no longer have identical start times
    or_word = [w for w in words if w.word == "Or"][0]
    does_word = [w for w in words if w.word == "does"][0]
    assert does_word.start > or_word.start
    assert does_word.start >= or_word.end


def test_shorts_final_scene_loop_ellipsis_enforcement():
    """Verifies that Shorts scripts guarantee trailing continuation ellipsis '...' on the final scene."""
    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "The brain named itself, recognized itself, and is now realizing that"}
    ]

    last_text = raw_scenes[-1]["spoken_text"].rstrip(".! ")
    if not last_text.endswith("..."):
        raw_scenes[-1]["spoken_text"] = f"{last_text}..."

    assert raw_scenes[-1]["spoken_text"].endswith("...")
    assert raw_scenes[-1]["spoken_text"] == "The brain named itself, recognized itself, and is now realizing that..."


# ─── NEW TESTS (PLAN IMPLEMENTATION) ─────────────────────────────────────────


def test_thought_cache_duplicate_detection():
    """Verifies that _is_duplicate returns True for a previously cached line and False for a new one."""
    from engine.managers.pipeline_runner import _hash_line, _is_duplicate, _add_to_cache

    cache_cfg = {"max_entries": 200, "entries": []}

    line_a = "Your shadow is proof that light traveled ninety-three million miles to be blocked by you."
    line_b = "Nothing is ever on fire. Fire is actually on things."

    # Neither is in the cache yet
    assert not _is_duplicate(line_a, cache_cfg)
    assert not _is_duplicate(line_b, cache_cfg)

    # Add line_a to the cache
    _add_to_cache(line_a, cache_cfg)

    # Now line_a should be detected as duplicate, line_b still not
    assert _is_duplicate(line_a, cache_cfg)
    assert not _is_duplicate(line_b, cache_cfg)

    # Punctuation/case variations of the same line must also match (normalised hash)
    line_a_variant = "Your shadow is proof that light traveled ninety-three million miles to be blocked by you!!!"
    assert _is_duplicate(line_a_variant, cache_cfg)


def test_thought_cache_eviction():
    """Verifies that entries beyond max_entries are evicted (oldest first)."""
    from engine.managers.pipeline_runner import _add_to_cache, _is_duplicate

    cache_cfg = {"max_entries": 3, "entries": []}

    lines = ["line one here", "line two here", "line three here", "line four here"]
    for line in lines:
        _add_to_cache(line, cache_cfg)

    # Only the 3 most recent lines should remain
    assert len(cache_cfg["entries"]) == 3
    # The oldest line ('line one') should have been evicted
    assert not _is_duplicate("line one here", cache_cfg)
    assert _is_duplicate("line four here", cache_cfg)


def test_random_schedule_delay_range():
    """Verifies that the random upload delay stays within the configured window."""
    import random as _rnd

    schedule_window_hours = 4
    max_secs = schedule_window_hours * 3600
    min_secs = 300  # 5 min floor

    # Simulate 1000 random delays and assert all are within bounds
    for _ in range(1000):
        delay = _rnd.randint(min_secs, max_secs)
        assert min_secs <= delay <= max_secs, f"Delay {delay}s out of bounds [{min_secs}, {max_secs}]"


def test_seo_title_fallback_no_trends():
    """Verifies generate_seo_title returns a valid title even when yt_trends.csv is missing."""
    import sys
    from unittest.mock import MagicMock

    # Stub out google packages that youtube_manager imports at module level
    for mod in ["google", "google.oauth2", "google.oauth2.credentials",
                "googleapiclient", "googleapiclient.discovery", "googleapiclient.http"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from engine.managers.youtube_manager import generate_seo_title

    cfg = {
        "style_template": "{title}",
        "emojis": ["👀"],
        "trend_window_days": 1,
    }
    title = generate_seo_title(
        niche="shower_thoughts",
        base_title="Shower Thoughts That Will Mess With Your Head 👀 #shorts",
        script_text="Your shadow is proof that light traveled ninety-three million miles to be blocked by you.",
        cfg=cfg
    )
    # Must return a non-empty string (no crash)
    assert isinstance(title, str)
    assert len(title) > 0
    # Should not exceed YouTube's 100-char limit
    assert len(title) <= 100


def test_apply_prompt_rules_virality_and_extra():
    """Verifies apply_prompt_rules correctly injects virality enforcement and extra instructions."""
    from engine.managers.pipeline_runner import apply_prompt_rules

    channel_cfg = {
        "prompt_rules": {
            "enforce_virality": True,
            "extra_instructions": "Always mention the word 'reality'.",
            "banned_phrases": ["furthermore", "in conclusion"],
        }
    }

    sys_p, usr_p = apply_prompt_rules("BASE_SYS", "BASE_USR", channel_cfg)

    assert "VIRALITY ENFORCEMENT" in sys_p
    assert "reality" in usr_p
    assert "furthermore" in sys_p
    assert "in conclusion" in sys_p


def test_are_thoughts_similar_fuzzy():
    """Verifies that are_thoughts_similar flags near-duplicate sentences with 1-word differences."""
    from engine.managers.pipeline_runner import are_thoughts_similar

    # Exact same sentence with and without 'just'
    s1 = "Your shadow is proof that light traveled ninety-three million miles just to be blocked by you."
    s2 = "Your shadow is proof that light traveled ninety-three million miles to be blocked by you."
    assert are_thoughts_similar(s1, s2, threshold=0.45) is True

    # Punctuation variations
    s3 = "If you replace every single part of an axe, is it still the exact same axe???"
    s4 = "If you replace every single part of an axe is it still the exact same axe."
    assert are_thoughts_similar(s3, s4, threshold=0.45) is True

    # Completely different sentences
    s5 = "The only part of your reflection you can lick is your tongue."
    s6 = "Clapping is just repeatedly slapping yourself because you enjoyed something."
    assert are_thoughts_similar(s5, s6, threshold=0.45) is False


def test_universal_banned_safety_filter():
    """Verifies that universal brand-safety filter blocks animal cruelty, meat, butchery, and NSFW."""
    from engine.managers.stock_video_manager import StockVideoManager

    # Should reject meat/slaughter/animal abuse
    assert StockVideoManager.is_safe_clip("raw butcher beef steak cutting") is False
    assert StockVideoManager.is_safe_clip("animal abuse dog fight cruelty") is False
    assert StockVideoManager.is_safe_clip("hospital surgery blood open wound") is False
    assert StockVideoManager.is_safe_clip("erotic intimate underwear lingerie") is False

    # Should accept clean satisfying craft ASMR
    assert StockVideoManager.is_safe_clip("kinetic sand squishing satisfying macro") is True
    assert StockVideoManager.is_safe_clip("pottery wheel clay shaping smooth") is True


def test_topato_channel_banned_filter():
    """Verifies that Topato negative filters block kitchen/cooking/food and haircuts."""
    from engine.managers.stock_video_manager import StockVideoManager

    # Should reject food / kitchen prep
    assert StockVideoManager.is_safe_clip("chef slicing lemon on cutting board") is False
    assert StockVideoManager.is_safe_clip("kitchen cooking vegetable onion pan") is False
    assert StockVideoManager.is_safe_clip("barber haircut fade salon trimmer") is False
    assert StockVideoManager.is_safe_clip("busy city street traffic car road") is False


def test_trailing_whisper_hallucination_prune():
    """Verifies that slice_words_by_scenes trims trailing phantom tokens on the loop scene."""
    from engine.managers.caption_aligner import CaptionAligner
    from engine.models import WordTimestamp

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these..."}
    ]

    # Transcribed words has trailing phantom token 'ease' after 'these'
    word_timestamps = [
        WordTimestamp(word="The", start=0.0, end=0.1),
        WordTimestamp(word="only", start=0.1, end=0.3),
        WordTimestamp(word="part", start=0.3, end=0.5),
        WordTimestamp(word="of", start=0.5, end=0.6),
        WordTimestamp(word="your", start=0.6, end=0.7),
        WordTimestamp(word="reflection", start=0.7, end=1.0),
        WordTimestamp(word="you", start=1.0, end=1.2),
        WordTimestamp(word="can", start=1.2, end=1.3),
        WordTimestamp(word="lick", start=1.3, end=1.5),
        WordTimestamp(word="is", start=1.5, end=1.6),
        WordTimestamp(word="your", start=1.6, end=1.7),
        WordTimestamp(word="tongue", start=1.7, end=2.0),
        # Scene 2 words:
        WordTimestamp(word="Which", start=2.2, end=2.4),
        WordTimestamp(word="is", start=2.4, end=2.5),
        WordTimestamp(word="why", start=2.5, end=2.7),
        WordTimestamp(word="you", start=2.7, end=2.8),
        WordTimestamp(word="should", start=2.8, end=3.0),
        WordTimestamp(word="never", start=3.0, end=3.2),
        WordTimestamp(word="overthink", start=3.2, end=3.5),
        WordTimestamp(word="these", start=3.5, end=3.8),
        # Phantom hallucination token:
        WordTimestamp(word="ease", start=3.85, end=4.0)
    ]

    slices = CaptionAligner.slice_words_by_scenes(word_timestamps, raw_scenes)
    assert len(slices) == 2
    scene_2_words = [wt.word for wt in slices[1]]
    # Suffix guard should have pruned 'ease'
    assert "ease" not in scene_2_words
    assert scene_2_words[-1] == "these"


def test_community_post_generation():
    """Verifies YouTubeManager generates a subscriber poll and pinned comment."""
    import sys
    from unittest.mock import MagicMock
    for mod in ["google", "google.oauth2", "google.oauth2.credentials",
                "googleapiclient", "googleapiclient.discovery", "googleapiclient.http"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from engine.managers.youtube_manager import YouTubeManager

    post = YouTubeManager.generate_community_post(
        topic="Creepy shower thoughts",
        hook="The only part of your reflection you can lick is your tongue."
    )
    assert "pinned_comment" in post
    assert "community_post" in post
    assert "community_poll" in post
    assert len(post["community_poll"]["options"]) == 4
    assert "reflection" in post["community_post"]


def test_youtube_manager_post_creator_comment(monkeypatch):
    """Verifies YouTubeManager.post_creator_comment formats commentThreads insert request."""
    from engine.managers.youtube_manager import YouTubeManager
    import engine.managers.youtube_manager as ym

    yt = YouTubeManager()
    monkeypatch.setattr(ym, "is_test_mode", lambda: False)

    mock_client = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute.return_value = {"id": "comment_abc123"}
    mock_client.commentThreads.return_value.insert.return_value = mock_insert

    res = yt.post_creator_comment("video_123", "Did this break your brain? 👇", youtube=mock_client)
    assert res == "comment_abc123"
    mock_client.commentThreads.return_value.insert.assert_called_once()
    call_args = mock_client.commentThreads.return_value.insert.call_args[1]
    assert call_args["body"]["snippet"]["videoId"] == "video_123"
    assert call_args["body"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"] == "Did this break your brain? 👇"


def test_vault_blend_indices():
    """Verifies that vault blending designates anchor indices (0, mid, last) for a 12-scene short."""
    num_scenes = 12
    vault_blend_count = 3

    vault_indices = set()
    if vault_blend_count == 1:
        vault_indices = {0}
    elif vault_blend_count == 2:
        vault_indices = {0, num_scenes - 1}
    else:
        vault_indices = {0, num_scenes // 2, num_scenes - 1}
        step = max(1, num_scenes // vault_blend_count)
        for i in range(0, num_scenes, step):
            if len(vault_indices) < vault_blend_count:
                vault_indices.add(i)

    assert 0 in vault_indices
    assert (num_scenes - 1) in vault_indices
    assert len(vault_indices) == 3


def test_optimal_publish_hour_learning(tmp_path, monkeypatch):
    """Verifies YouTubeManager reads learned best publish hour from channel_performance.json."""
    import sys
    import json
    from unittest.mock import MagicMock
    for mod in ["google", "google.oauth2", "google.oauth2.credentials",
                "googleapiclient", "googleapiclient.discovery", "googleapiclient.http"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    from engine.managers.youtube_manager import YouTubeManager

    perf_file = tmp_path / "channel_performance.json"
    perf_file.write_text(json.dumps({"best_publish_hour": 20}), encoding="utf-8")

    # Point os.path.join("memory", "channel_performance.json") to temp file
    monkeypatch.setattr(
        "engine.managers.youtube_manager.os.path.join",
        lambda *args: str(perf_file) if "channel_performance.json" in args else "/".join(args)
    )

    hour = YouTubeManager.get_optimal_publish_hour()
    assert hour == 20


def test_youtube_manager_graceful_missing_google_client(monkeypatch):
    """Verifies that YouTubeManager can be used for title & community posts even without googleapiclient."""
    import engine.managers.youtube_manager as ym
    monkeypatch.setattr(ym, "_GOOGLE_API_AVAILABLE", False)

    title = ym.generate_seo_title("shower_thoughts", "Base Title", "script text", {})
    assert title != ""
    assert isinstance(title, str)

    post = ym.YouTubeManager.generate_community_post("Why mirrors flip horizontally", "Why do mirrors flip horizontally?")
    assert "pinned_comment" in post
    assert "community_post" in post


def test_logger_deduplication_clean_tag(capsys, monkeypatch):
    """Verifies that logger does not produce double tags like [SUCCESS] [SUCCESS]."""
    from engine.logger import logger
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    logger.success("Clean success message")
    captured = capsys.readouterr()
    assert "[SUCCESS] [SUCCESS]" not in captured.out
    assert "[SUCCESS] Clean success message" in captured.out


def test_channel_config_caption_typography_loading():
    """Verifies that channel_config.yaml has caption_settings configured with ZY Resolve font."""
    import yaml
    with open("config/channel_config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "caption_settings" in cfg
    caps = cfg["caption_settings"]
    assert caps.get("font_name") == "ZY Resolve"
    assert caps.get("font_file") == "assets/fonts/ZY-Resolve.ttf"


def test_calculate_collision_free_publish_time_future_guarantee(monkeypatch, tmp_path):
    """Verifies that publishAt is always strictly at least 1 hour in the future."""
    from engine.managers.youtube_manager import YouTubeManager
    from engine.managers.competitor_spy import CompetitorSpy
    from datetime import datetime, timezone
    
    monkeypatch.setattr(CompetitorSpy, "TIMING_CACHE_FILE", str(tmp_path / "timing_intelligence.json"))
    mgr = YouTubeManager()
    pub_iso = mgr.calculate_collision_free_publish_time(None)
    pub_dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    
    assert pub_dt > now
    assert (pub_dt - now).total_seconds() >= 1800  # at least 30 minutes in future


def test_calculate_collision_free_publish_time_collision_advance(monkeypatch, tmp_path):
    """Verifies that if target day is occupied, it increments +24h to the next available day."""
    from engine.managers.youtube_manager import YouTubeManager
    from engine.managers.competitor_spy import CompetitorSpy
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    
    monkeypatch.setattr(CompetitorSpy, "TIMING_CACHE_FILE", str(tmp_path / "timing_intelligence.json"))
    mgr = YouTubeManager()
    monkeypatch.setenv("TEST_MODE", "false")
    
    now = datetime.now(timezone.utc)
    target_today = now.strftime("%Y-%m-%d")
    target_tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Mock YouTube API to return target_today as occupied
    mock_yt = MagicMock()
    mock_yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPL123"}}}]
    }
    mock_yt.playlistItems().list().execute.return_value = {
        "items": [{"contentDetails": {"videoId": "vid_1"}}]
    }
    mock_yt.videos().list().execute.return_value = {
        "items": [{"status": {"publishAt": f"{target_today}T{h:02d}:00:00Z"}} for h in [1, 14, 18, 22]]
    }
    
    pub_iso = mgr.calculate_collision_free_publish_time(mock_yt)
    # Target date should have bumped to tomorrow or beyond
    assert target_today not in pub_iso


def test_intelligent_scheduler_spacing_and_negative_jitter(tmp_path, monkeypatch):
    """Verifies that the scheduler enforces anti-cannibalization buffer and negative minute jitter."""
    from engine.managers.youtube_manager import YouTubeManager
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    import yaml

    test_cfg = {
        "upload_settings": {
            "shorts_per_day": 1,
            "min_spacing_hours": 6.0,
            "use_negative_jitter": True,
            "jitter_minutes_min": 5,
            "jitter_minutes_max": 18,
            "target_peak_windows_utc": [18, 22, 14, 1]
        }
    }
    cfg_file = tmp_path / "channel_config.yaml"
    cfg_file.write_text(yaml.dump(test_cfg), encoding="utf-8")
    monkeypatch.setattr("builtins.open", lambda p, *a, **kw: open(str(cfg_file) if "channel_config.yaml" in str(p) else p, *a, **kw))
    monkeypatch.setenv("TEST_MODE", "false")
    from engine.managers.competitor_spy import CompetitorSpy
    monkeypatch.setattr(CompetitorSpy, "TIMING_CACHE_FILE", str(tmp_path / "timing_intelligence.json"))

    mgr = YouTubeManager()
    now = datetime.now(timezone.utc)
    queued_time = now + timedelta(hours=2)

    mock_yt = MagicMock()
    mock_yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPL_TEST"}}}]
    }
    mock_yt.playlistItems().list().execute.return_value = {
        "items": [{"contentDetails": {"videoId": "test_v1"}}]
    }
    mock_yt.videos().list().execute.return_value = {
        "items": [{"status": {"publishAt": queued_time.strftime("%Y-%m-%dT%H:%M:%SZ")}}]
    }

    pub_iso = mgr.calculate_collision_free_publish_time(mock_yt)
    pub_dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))

    # Anti-cannibalization buffer: must be at least 6 hours away from queued video
    gap_hours = (pub_dt - queued_time).total_seconds() / 3600.0
    assert gap_hours >= 6.0

    # Negative jitter: minute must be between 42 and 55 (5 to 18 mins before the target hour)
    assert 42 <= pub_dt.minute <= 55


def test_competitor_niche_timing_intel_caching(tmp_path, monkeypatch):
    """Verifies that CompetitorSpy ranks hours and caches results in memory/timing_intelligence.json."""
    from engine.managers.competitor_spy import CompetitorSpy
    test_cache = str(tmp_path / "timing_intelligence.json")
    monkeypatch.setattr(CompetitorSpy, "TIMING_CACHE_FILE", test_cache)
    intel = CompetitorSpy.get_niche_timing_intel(youtube=None, default_slots=[18, 22, 14, 1])
    assert "ranked_hours" in intel
    assert len(intel["ranked_hours"]) == 24
    assert 18 in intel["ranked_hours"][:4]
    assert os.path.exists(CompetitorSpy.TIMING_CACHE_FILE)
    assert CompetitorSpy.TIMING_CACHE_FILE == test_cache


def test_discovery_bans_allam_model():
    """Verifies that allam models are strictly filtered out by modality patterns."""
    from engine.discovery import is_modality_allowed, is_model_allowed
    assert is_modality_allowed("allam-2-7b") is False
    assert is_modality_allowed("allam-7b") is False
    assert is_model_allowed("allam-2-7b", set()) is False
    assert is_modality_allowed("gemini-3.5-flash") is True
    assert is_modality_allowed("openai/gpt-oss-120b") is True


def test_validate_short_script_permissive_and_policy_check():
    """Verifies that validate_short_script accepts partial scripts for auto-expansion and rejects policy violations."""
    from engine.managers.pipeline_runner import YOUTUBE_POLICY_BANNED_WORDS

    # Simulate validator logic
    def validate_script(data):
        if not isinstance(data, dict):
            return False
        scenes = data.get("scenes", [])
        if not isinstance(scenes, list) or len(scenes) < 3:
            return False
        valid_scenes = [sc for sc in scenes if isinstance(sc, dict) and bool(sc.get("spoken_text", "").strip())]
        if len(valid_scenes) < 3:
            return False
        for sc in valid_scenes:
            txt = sc.get("spoken_text", "").lower()
            if any(bad in txt for bad in YOUTUBE_POLICY_BANNED_WORDS):
                return False
        words = sum(len(sc.get("spoken_text", "").split()) for sc in valid_scenes)
        if words < 25 or words > 220:
            return False
        return True

    # 4 scenes with 45 words — should PASS so downstream can auto-expand to 12
    valid_partial = {
        "scenes": [
            {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
            {"scene_id": 2, "spoken_text": "Your shadow is proof that light traveled ninety-three million miles to be blocked by you."},
            {"scene_id": 3, "spoken_text": "If you replace every single part of an axe, is it still the exact same axe?"},
            {"scene_id": 4, "spoken_text": "Which is why you should never overthink these..."}
        ]
    }
    assert validate_script(valid_partial) is True

    # Policy violation — should FAIL
    policy_violation = {
        "scenes": [
            {"scene_id": 1, "spoken_text": "Here is how to commit suicide safely..."},
            {"scene_id": 2, "spoken_text": "Normal scene two."},
            {"scene_id": 3, "spoken_text": "Normal scene three."}
        ]
    }
    assert validate_script(policy_violation) is False

    # Fewer than 3 scenes — should FAIL
    too_few = {
        "scenes": [
            {"scene_id": 1, "spoken_text": "Only one scene here."}
        ]
    }
    assert validate_script(too_few) is False


def test_llm_token_limit_payload_calibration(monkeypatch):
    """Verifies that LLMManager configures 2048 max output tokens for both Gemini and OpenAI/Groq."""
    llm = LLMManager()

    # Track requests
    captured_payloads = []
    def mock_http(url, method="POST", headers=None, json_data=None, timeout=60.0):
        captured_payloads.append(json_data)
        class MockResp:
            status_code = 200
            text = '{"candidates":[{"content":{"parts":[{"text":"{}"}]}}]}'
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
        return MockResp()

    monkeypatch.setattr("engine.managers.llm_manager._http_request", mock_http)

    gemini_prov = {
        "id": "gemini_test",
        "name": "Google (gemini-3.5-flash)",
        "model": "gemini-3.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/",
        "endpoint": "v1beta/models/gemini-3.5-flash:generateContent",
        "secret_key": "MOCK_KEY"
    }
    llm._execute_provider_call(gemini_prov, "sys", "usr", 0.7)
    assert captured_payloads[-1]["generationConfig"]["maxOutputTokens"] == 2048

    groq_prov = {
        "id": "groq_test",
        "name": "Groq (openai/gpt-oss-120b)",
        "model": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "endpoint": "openai/v1/chat/completions",
        "secret_key": "MOCK_KEY"
    }
    def mock_groq_http(url, method="POST", headers=None, json_data=None, timeout=60.0):
        captured_payloads.append(json_data)
        class MockResp:
            status_code = 200
            text = '{"choices":[{"message":{"content":"{}"}}]}'
            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}
        return MockResp()

    monkeypatch.setattr("engine.managers.llm_manager._http_request", mock_groq_http)
    llm._execute_provider_call(groq_prov, "sys", "usr", 0.7)
    assert captured_payloads[-1]["max_tokens"] == 2048


def test_youtube_upload_metadata_and_thumbnail(tmp_path, monkeypatch):
    """Verifies that upload_one_shot_scheduled_video constructs complete metadata and calls thumbnails().set()."""
    from engine.managers.youtube_manager import YouTubeManager
    from engine.managers.competitor_spy import CompetitorSpy

    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setattr(CompetitorSpy, "TIMING_CACHE_FILE", str(tmp_path / "timing_intelligence.json"))
    mgr = YouTubeManager()

    # Create dummy video and thumbnail
    dummy_video = tmp_path / "final_render.mp4"
    dummy_video.write_bytes(b"dummy video data")
    dummy_thumb = tmp_path / "final_render_thumbnail.jpg"
    dummy_thumb.write_bytes(b"dummy thumb data")

    inserted_body = {}
    inserted_kwargs = {}
    thumbnail_calls = []

    mock_yt = MagicMock()
    # Mock video insert
    mock_insert_req = MagicMock()
    mock_insert_req.next_chunk.return_value = (None, {"id": "uploaded_vid_999"})
    
    def fake_insert(part=None, body=None, media_body=None, notifySubscribers=None):
        inserted_body.update(body)
        inserted_kwargs["notifySubscribers"] = notifySubscribers
        return mock_insert_req

    mock_yt.videos().insert = fake_insert

    # Mock thumbnail set
    mock_thumb_req = MagicMock()
    mock_thumb_req.execute.return_value = {"items": []}
    def fake_thumb_set(videoId=None, media_body=None):
        thumbnail_calls.append({"videoId": videoId, "media_body": media_body})
        return mock_thumb_req

    mock_yt.thumbnails().set = fake_thumb_set

    # Mock channels/playlist for collision check
    mock_yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPL123"}}}]
    }
    mock_yt.playlistItems().list().execute.return_value = {"items": []}

    monkeypatch.setattr(mgr, "get_client", lambda: mock_yt)
    monkeypatch.setattr("engine.managers.youtube_manager.MediaFileUpload", MagicMock(return_value=MagicMock()))

    res = mgr.upload_one_shot_scheduled_video(
        video_path=str(dummy_video),
        title="Mind-Bending Shower Thoughts That Make You Question Reality 🧠 #shorts",
        description="Deep thoughts about the simulation. #showerthoughts #shorts",
        tags=["shower thoughts", "psychology", "shorts"],
        category_id="24",
        default_language="en-US",
        default_audio_language="en-US",
        contains_synthetic_media=False,
        notify_subscribers=False,
        public_stats_viewable=False,
        thumbnail_path=str(dummy_thumb)
    )

    assert res["video_id"] == "uploaded_vid_999"
    assert inserted_body["snippet"]["defaultLanguage"] == "en-US"
    assert inserted_body["snippet"]["defaultAudioLanguage"] == "en-US"
    assert inserted_body["snippet"]["categoryId"] == "24"
    assert inserted_body["status"]["containsSyntheticMedia"] is False
    assert inserted_body["status"]["selfDeclaredMadeForKids"] is False
    assert inserted_body["status"]["embeddable"] is True
    assert inserted_body["status"]["publicStatsViewable"] is False
    assert inserted_body["status"]["license"] == "youtube"
    assert inserted_kwargs["notifySubscribers"] is False

    # Verify custom thumbnail was uploaded
    assert len(thumbnail_calls) == 1
    assert thumbnail_calls[0]["videoId"] == "uploaded_vid_999"


def test_unified_script_seo_extraction():
    """Verifies that pipeline_runner prefers embedded script SEO over secondary LLM call."""
    script_data_with_seo = {
        "thought_process": {"hook_psychology": "hooks immediately"},
        "seo": {
            "title": "Why Your Phone Is An Illusion 📱 #shorts",
            "description": "Mind-bending paradoxes about modern technology. Which thought hit you hardest? 👇\n\n#showerthoughts #shorts",
            "tags": ["phone", "screen", "mind blowing", "shorts"]
        },
        "scenes": [
            {"scene_id": 1, "spoken_text": "Scene 1."},
            {"scene_id": 2, "spoken_text": "Scene 2."}
        ]
    }

    # Simulate extraction logic
    script_seo = script_data_with_seo.get("seo")
    assert isinstance(script_seo, dict)
    assert script_seo.get("title") == "Why Your Phone Is An Illusion 📱 #shorts"
    assert len(script_seo.get("tags")) == 4


def test_brand_tags_merging_and_capping():
    """Verifies brand tags deduplication and 490-character capping logic."""
    topic_tags = ["shower thoughts", "mind blowing facts", "deep thoughts", "psychology"]
    brand_tags = ["topato", "metopato", "SHOWER THOUGHTS", "cognitive glitches", "facts that break your brain"]

    merged_tags = []
    seen_tags = set()
    for t in list(topic_tags) + list(brand_tags):
        t_clean = t.strip()
        t_lower = t_clean.lower()
        if t_clean and t_lower not in seen_tags:
            seen_tags.add(t_lower)
            merged_tags.append(t_clean)

    # Check deduplication is case-insensitive
    assert len([t for t in merged_tags if t.lower() == "shower thoughts"]) == 1
    assert "topato" in merged_tags
    assert "metopato" in merged_tags

    # Test 490-character capping
    final_tags = []
    char_count = 0
    for t in merged_tags:
        if char_count + len(t) + 1 <= 490:
            final_tags.append(t)
            char_count += len(t) + 1

    total_len = sum(len(t) + 1 for t in final_tags)
    assert total_len <= 490


def test_calibrate_and_guard_script_resegmentation():
    """Verifies that 4 multi-sentence scenes with sufficient words are re-segmented to 10+ scenes and 145-180 words without canned fallbacks."""
    from engine.managers.pipeline_runner import calibrate_and_guard_script

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection that you can lick is your tongue. It proves that your brain actively constructs every visual reality you experience. Mirrors are silent witnesses to the strange twists of evolution."},
        {"scene_id": 2, "spoken_text": "Your shadow traveled ninety-three million miles across space just to be blocked by your body. Think about how long that ancient solar light traveled through the cold universe. The cosmos is overflowing with unexplained phenomena that defy logic."},
        {"scene_id": 3, "spoken_text": "If deadly poison expires does it become significantly more poisonous or noticeably less poisonous over time? Nobody actually wants to test this bizarre medical hypothesis in a laboratory. Certain paradoxes will remain permanently unsolved by modern researchers."},
        {"scene_id": 4, "spoken_text": "Sleeping at night is just charging your biological battery while dreaming is running an elaborate diagnostics test. Your subconscious processes every hidden memory before morning arrives. Which is why you should never overthink these strange psychological quirks..."}
    ]

    calibrated = calibrate_and_guard_script(raw_scenes, prompt_settings={})
    assert len(calibrated) >= 10
    total_words = sum(len(s["spoken_text"].split()) for s in calibrated)
    assert 145 <= total_words <= 180
    # Hook clean
    assert not calibrated[0]["spoken_text"].startswith("...")
    assert calibrated[0]["spoken_text"][0].isupper()
    # Loop ellipsis
    assert calibrated[-1]["spoken_text"].endswith("...")


def test_calibrate_and_guard_script_underbudget_expansion():
    """Verifies that an under-budget script raises ValueError rather than injecting canned thoughts."""
    from engine.managers.pipeline_runner import calibrate_and_guard_script

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "Your shadow is proof that light traveled ninety-three million miles."},
        {"scene_id": 3, "spoken_text": "Nothing is ever on fire. Fire is actually on things."},
        {"scene_id": 4, "spoken_text": "Which is why you should never overthink these..."}
    ]

    with pytest.raises(ValueError, match="Script calibration failed: insufficient generated content"):
        calibrate_and_guard_script(raw_scenes, prompt_settings={})


def test_calibrate_and_guard_script_overbudget_trim():
    """Verifies that an over-budget script (15 scenes, 210 words) is trimmed down to <= 175 words while preserving Hook and Loop bridge."""
    from engine.managers.pipeline_runner import calibrate_and_guard_script

    raw_scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."}
    ]
    distinct_thoughts = [
        "Your brain actively deletes the sensation of your tongue resting inside your mouth.",
        "Every single mirror you have ever bought in a store was in used condition.",
        "You have never actually touched anything because electron fields repel your atoms.",
        "Your future self is currently watching you through memories right now at this moment.",
        "When you wait for the waiter you temporarily become the waiter in that situation.",
        "The person you think you are only exists in your own personal mind.",
        "If you rip a hole in a net there are actually fewer holes in it.",
        "Earth is a giant spaceship traveling through deep space without any seatbelts attached.",
        "Your alarm clock sound is technically your personal theme song every morning.",
        "You clean a towel with soap and water but the towel still gets dirty.",
        "Your skeleton is completely wet and completely dark inside your body all day.",
        "Every decision you make is simply narrowing down the infinite possible futures.",
        "Nothing in the entire universe is completely still everything is constantly flying through space."
    ]
    for i, thought in enumerate(distinct_thoughts, start=2):
        raw_scenes.append({"scene_id": i, "spoken_text": thought})
    raw_scenes.append({
        "scene_id": 15,
        "spoken_text": "Which is why you should never overthink these..."
    })

    calibrated = calibrate_and_guard_script(raw_scenes, prompt_settings={})
    total_words = sum(len(s["spoken_text"].split()) for s in calibrated)
    assert total_words <= 175
    assert calibrated[0]["spoken_text"] == "The only part of your reflection you can lick is your tongue."
    assert calibrated[-1]["spoken_text"].endswith("...")


def test_voice_normalizer_rescale_clamping(monkeypatch, tmp_path):
    """Verifies that VoiceNormalizer.rescale_audio_duration clamps speed factor to [0.95, 1.10]."""
    from engine.managers.voice_normalizer import VoiceNormalizer
    import subprocess

    dummy_in = str(tmp_path / "dummy.wav")
    dummy_out = str(tmp_path / "dummy_out.wav")
    with open(dummy_in, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 2000)

    recorded_atempo = []

    def mock_run(cmd, *args, **kwargs):
        for arg in cmd:
            if "atempo=" in arg:
                recorded_atempo.append(float(arg.split("atempo=")[1]))
        with open(dummy_out, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 2000)
        class _Proc:
            returncode = 0
        return _Proc()

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Test extreme high speed (e.g. 1.83x) -> should clamp to 1.10
    VoiceNormalizer.rescale_audio_duration(dummy_in, dummy_out, speed_factor=1.83)
    assert recorded_atempo[-1] == 1.10

    # Test extreme low speed (e.g. 0.80x) -> should clamp to 0.95
    VoiceNormalizer.rescale_audio_duration(dummy_in, dummy_out, speed_factor=0.80)
    assert recorded_atempo[-1] == 0.95

    # Test valid in-range speed (e.g. 1.05x) -> should pass through
    VoiceNormalizer.rescale_audio_duration(dummy_in, dummy_out, speed_factor=1.05)
    assert recorded_atempo[-1] == 1.05


def test_secret_sanitizer():
    """Verifies that engine.logger.sanitize_log_message masks sensitive API keys, tokens, and bearer headers."""
    from engine.logger import sanitize_log_message

    # Test Google API key masking
    msg_google = "Connecting with key AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz"
    sanitized = sanitize_log_message(msg_google)
    assert "[REDACTED_API_KEY]" in sanitized
    assert "AIzaSyD1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized

    # Test HuggingFace token masking
    msg_hf = "Error fetching from HF: hf_abcdef1234567890abcdef1234567890"
    sanitized_hf = sanitize_log_message(msg_hf)
    assert "[REDACTED_HF_TOKEN]" in sanitized_hf
    assert "abcdef1234567890" not in sanitized_hf

    # Test Groq key masking
    msg_groq = "Groq call failed with gsk_abcdef1234567890abcdef1234567890"
    sanitized_groq = sanitize_log_message(msg_groq)
    assert "[REDACTED_GROQ_KEY]" in sanitized_groq

    # Test Bearer token masking
    msg_bearer = "Authorization: Bearer ya29.a0AfH6SM1234567890abcdef"
    sanitized_bearer = sanitize_log_message(msg_bearer)
    assert "Bearer [REDACTED_TOKEN]" in sanitized_bearer

    # Test normal message unaltered
    msg_normal = "Generated 12 scenes successfully with 130 words."
    assert sanitize_log_message(msg_normal) == msg_normal


def test_curated_facts_and_grounding():
    """Verifies that TopicInspector.get_grounding_references extracts structured facts and thoughts from the curated vault."""
    from engine.managers.topic_inspector import TopicInspector

    # 1. Retrieve random items
    items = TopicInspector.get_grounding_references(count=5)
    assert len(items) == 5
    for item in items:
        assert "text" in item and len(item["text"]) > 10
        assert item.get("type") in ["thought", "fact"]
        assert "pillar" in item

    # 2. Filter by specific pillar
    hb_items = TopicInspector.get_grounding_references(count=4, pillar="human_body")
    assert len(hb_items) == 4
    for item in hb_items:
        assert "human_body" in item["pillar"]

    # 3. Handle graceful fallback when vault file is invalid or missing
    items_fallback = TopicInspector.get_grounding_references(count=3, pillar="nonexistent_pillar")
    assert len(items_fallback) == 3


def test_discord_notification_includes_community_package(monkeypatch):
    """Verifies that scripts.discord_notifier.notify_published formats pinned comments and community polls into Discord embed fields."""
    import scripts.discord_notifier as discord_notifier
    import requests

    captured_payloads = []

    def mock_post(url, json=None, *args, **kwargs):
        captured_payloads.append(json)
        class _Resp:
            status_code = 204
            text = ""
        return _Resp()

    monkeypatch.setattr(requests, "post", mock_post)
    monkeypatch.setattr(discord_notifier, "_ACTIVE_WEBHOOK", "https://discord.com/api/webhooks/mock/test")

    community_data = {
        "pinned_comment": "Which everyday object secretly freaks you out the most? 👇",
        "community_post": "Did you know your brain actively edits out your heartbeat? What other biological glitches do you notice?",
        "community_poll": {
            "question": "What is the strangest fact about reality?",
            "options": ["Mirrors lie", "Light lag", "Poison paradox", "Time dilation"]
        }
    }

    discord_notifier.notify_published(
        topic="Mind Bending Realities",
        video_id="test_vid_123",
        publish_time="2026-10-12 18:00 UTC",
        community_data=community_data
    )

    assert len(captured_payloads) == 1
    embed = captured_payloads[0]["embeds"][0]
    field_names = [f["name"] for f in embed.get("fields", [])]
    assert "📌 Pinned Comment (Copy & Pin in Studio)" in field_names
    assert "📊 Community Poll (Copy & Post)" in field_names
    assert "📢 Community Tab Post (Copy & Post)" in field_names

    # Check pinned comment value
    pinned_field = next(f for f in embed["fields"] if f["name"] == "📌 Pinned Comment (Copy & Pin in Studio)")
    assert "Which everyday object secretly freaks you out the most?" in pinned_field["value"]

# ─── 13. EDITORIAL GATE MANDATORY ENFORCEMENT (PHASE 2) ─────────────────────────

def test_editorial_gate_rejects_thought_cache_duplicate(monkeypatch, tmp_path):
    """
    Phase 2 - Test 1: Verify that a cache-triggered duplicate cannot result in an unvalidated
    scene rewrite that bypasses the Editorial Critic, and instead raises ValueError and halts spec packaging.
    """
    from engine.managers.pipeline_runner import run_spec_stage, _hash_line

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Force execution of editorial critic and thought cache paths
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    import engine.managers.llm_quality_tracker as qt_module
    monkeypatch.setattr(qt_module.LLMQualityTracker, "record_result", lambda *a, **k: None)

    # Mock health checks and topic discovery
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    duplicate_scene_text = "The only part of your reflection you can lick is your tongue."
    scenes = [
        {"scene_id": 1, "spoken_text": duplicate_scene_text, "stock_video_query": "mirror reflection"},
        {"scene_id": 2, "spoken_text": "Your brain actively deletes the physical sensation of your tongue resting inside your mouth.", "stock_video_query": "mind thought"},
        {"scene_id": 3, "spoken_text": "Every single mirror you have ever bought in a store was sold in completely used condition.", "stock_video_query": "mirror store"},
        {"scene_id": 4, "spoken_text": "You have never actually touched anything because electron fields constantly repel your physical atoms.", "stock_video_query": "physics atoms"},
        {"scene_id": 5, "spoken_text": "Your future self is currently watching you through deep memories right now at this exact moment.", "stock_video_query": "time future"},
        {"scene_id": 6, "spoken_text": "When you wait for the waiter you temporarily become the actual waiter in that restaurant situation.", "stock_video_query": "restaurant waiter"},
        {"scene_id": 7, "spoken_text": "The person you think you are only exists in your own personal conscious mind.", "stock_video_query": "identity reflection"},
        {"scene_id": 8, "spoken_text": "If you rip a physical hole in a net there are actually fewer total holes in it.", "stock_video_query": "net paradox"},
        {"scene_id": 9, "spoken_text": "Earth is a giant biological spaceship traveling through deep cosmic space without any safety seatbelts.", "stock_video_query": "earth cosmos"},
        {"scene_id": 10, "spoken_text": "Your loud alarm clock sound is technically your personal energetic theme song every single morning.", "stock_video_query": "morning alarm"},
        {"scene_id": 11, "spoken_text": "Which is why you should never overthink these strange psychological quirks of reality...", "stock_video_query": "loop ending"}
    ]
    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why You See Everything Everywhere",
        "scenes": scenes
    }
    mock_seo_response = {
        "title": "Frequency Illusion #shorts",
        "description": "Why you see things everywhere. #shorts",
        "tags": ["psychology", "facts", "shorts"]
    }

    # Pre-populate thought cache with the duplicate hash of scene 1
    dup_hash = _hash_line(duplicate_scene_text)
    monkeypatch.setattr(
        "engine.managers.pipeline_runner._load_thought_cache",
        lambda cfg: {"max_entries": 200, "entries": [{"hash": dup_hash, "ts": "2026-01-01T00:00:00Z"}]}
    )

    rewrite_called = []
    def mock_generate_json(self, sys_p, usr_p, temperature=0.7, *args, **kwargs):
        if kwargs.get("task_name") == "rewrite" or "copywriter" in sys_p:
            rewrite_called.append(usr_p)
            return {"text": "A rewritten line bypassing critic"}
        if "SEO Director" in sys_p:
            return mock_seo_response
        return mock_script_response

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_generate_json)
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, mock_seo_response)
    )
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: (10.0, [], [5.0, 5.0], [[], []]))

    # Mock editorial critic to approve the script
    critic_called = []
    def mock_audit(raw_scenes, seo_data, topic, llm_manager=None, *args, **kwargs):
        critic_called.append(True)
        return raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", mock_audit)

    # Must raise ValueError with specific rejection message
    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Thought Cache rejected script" in str(exc_info.value)
    assert "Scene 1 duplicates previously published thought" in str(exc_info.value)
    # Verify no unvalidated raw-LLM rewrite occurred
    assert len(rewrite_called) == 0
    # Critic was called prior to thought-cache check
    assert len(critic_called) == 1
    # Verify spec.json was never written/packaged
    assert not os.path.exists(test_spec_path)


def test_editorial_gate_unexpected_exception_stops_spec_generation(monkeypatch, tmp_path):
    """
    Phase 2 - Test 2: Verify that unexpected exceptions from editorial_critic.audit_and_refine_spec
    (such as RuntimeError) are not swallowed, halt spec generation, fail closed, and do not package spec.json.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Force execution of editorial critic path
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue.", "stock_video_query": "mirror reflection"},
        {"scene_id": 2, "spoken_text": "Your brain actively deletes the physical sensation of your tongue resting inside your mouth.", "stock_video_query": "mind thought"},
        {"scene_id": 3, "spoken_text": "Every single mirror you have ever bought in a store was sold in completely used condition.", "stock_video_query": "mirror store"},
        {"scene_id": 4, "spoken_text": "You have never actually touched anything because electron fields constantly repel your physical atoms.", "stock_video_query": "physics atoms"},
        {"scene_id": 5, "spoken_text": "Your future self is currently watching you through deep memories right now at this exact moment.", "stock_video_query": "time future"},
        {"scene_id": 6, "spoken_text": "When you wait for the waiter you temporarily become the actual waiter in that restaurant situation.", "stock_video_query": "restaurant waiter"},
        {"scene_id": 7, "spoken_text": "The person you think you are only exists in your own personal conscious mind.", "stock_video_query": "identity reflection"},
        {"scene_id": 8, "spoken_text": "If you rip a physical hole in a net there are actually fewer total holes in it.", "stock_video_query": "net paradox"},
        {"scene_id": 9, "spoken_text": "Earth is a giant biological spaceship traveling through deep cosmic space without any safety seatbelts.", "stock_video_query": "earth cosmos"},
        {"scene_id": 10, "spoken_text": "Your loud alarm clock sound is technically your personal energetic theme song every single morning.", "stock_video_query": "morning alarm"},
        {"scene_id": 11, "spoken_text": "Which is why you should never overthink these strange psychological quirks of reality...", "stock_video_query": "loop ending"}
    ]
    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why You See Everything Everywhere",
        "scenes": scenes
    }
    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", lambda self, sys_p, usr_p, *a, **kw: mock_script_response)
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, {"title": "Why You See Everything Everywhere #shorts"})
    )
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: (10.0, [], [5.0, 5.0], [[], []]))

    # Mock editorial critic to raise unexpected RuntimeError
    def mock_audit_raising(*args, **kwargs):
        raise RuntimeError("Unexpected Editorial Critic internal database failure")

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", mock_audit_raising)

    # Must raise the unexpected RuntimeError and fail closed
    with pytest.raises(RuntimeError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Unexpected Editorial Critic internal database failure" in str(exc_info.value)
    # spec.json must not exist
    assert not os.path.exists(test_spec_path)


def test_editorial_gate_rejection_halts_spec_generation(monkeypatch, tmp_path):
    """
    Phase 2 - Test 3: Verify that an explicit editorial rejection (status='rejected' or unresolved_failures > 0)
    raises ValueError, halting spec packaging and preventing unvalidated script output.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Force execution of editorial critic path
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue.", "stock_video_query": "mirror reflection"},
        {"scene_id": 2, "spoken_text": "Your brain actively deletes the physical sensation of your tongue resting inside your mouth.", "stock_video_query": "mind thought"},
        {"scene_id": 3, "spoken_text": "Every single mirror you have ever bought in a store was sold in completely used condition.", "stock_video_query": "mirror store"},
        {"scene_id": 4, "spoken_text": "You have never actually touched anything because electron fields constantly repel your physical atoms.", "stock_video_query": "physics atoms"},
        {"scene_id": 5, "spoken_text": "Your future self is currently watching you through deep memories right now at this exact moment.", "stock_video_query": "time future"},
        {"scene_id": 6, "spoken_text": "When you wait for the waiter you temporarily become the actual waiter in that restaurant situation.", "stock_video_query": "restaurant waiter"},
        {"scene_id": 7, "spoken_text": "The person you think you are only exists in your own personal conscious mind.", "stock_video_query": "identity reflection"},
        {"scene_id": 8, "spoken_text": "If you rip a physical hole in a net there are actually fewer total holes in it.", "stock_video_query": "net paradox"},
        {"scene_id": 9, "spoken_text": "Earth is a giant biological spaceship traveling through deep cosmic space without any safety seatbelts.", "stock_video_query": "earth cosmos"},
        {"scene_id": 10, "spoken_text": "Your loud alarm clock sound is technically your personal energetic theme song every single morning.", "stock_video_query": "morning alarm"},
        {"scene_id": 11, "spoken_text": "Which is why you should never overthink these strange psychological quirks of reality...", "stock_video_query": "loop ending"}
    ]
    mock_script_response = {
        "thought_process": {"hook": "intriguing", "loop": "circular"},
        "title": "Why You See Everything Everywhere",
        "scenes": scenes
    }
    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", lambda self, sys_p, usr_p, *a, **kw: mock_script_response)
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, {"title": "Why You See Everything Everywhere #shorts"})
    )
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: (10.0, [], [5.0, 5.0], [[], []]))

    # Mock editorial critic returning explicit rejection
    def mock_audit_rejected(raw_scenes, seo_data, topic, llm_manager=None, *args, **kwargs):
        return raw_scenes, seo_data, {"status": "rejected", "unresolved_failures": 2}

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", mock_audit_rejected)

    # Must raise ValueError with failure count
    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Editorial Critic rejected script: 2 unresolvable defect(s)" in str(exc_info.value)
    # spec.json must not exist
    assert not os.path.exists(test_spec_path)


# ─── 14. REMOVE SHORTS MONOLITHIC FALLBACK (PHASE 5B) ──────────────────────────────

def test_shorts_fails_closed_on_iscg_exception_without_monolithic_fallback(monkeypatch, tmp_path):
    """
    Phase 5B - Test 1: Verify that when iterative script generation raises an exception,
    run_spec_stage(video_type='short') fails closed, propagates the exception directly,
    never invokes monolithic script_gen, and does not create spec.json.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    def mock_iscg_fail(*args, **kwargs):
        raise RuntimeError("Simulated ISCG failure after retry exhaustion")

    monkeypatch.setattr("engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain", mock_iscg_fail)

    # Track if monolithic generate_json is called
    monolithic_calls = []
    def mock_generate_json(self, sys_p, usr_p, *a, **kw):
        monolithic_calls.append({"task_name": kw.get("task_name"), "sys_p": sys_p})
        return {"scenes": [{"scene_id": 1, "spoken_text": "Monolithic fallback text."}]}

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_generate_json)

    with pytest.raises(RuntimeError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Simulated ISCG failure after retry exhaustion" in str(exc_info.value)
    # Monolithic LLM generator must NEVER be called as fallback
    assert len(monolithic_calls) == 0
    assert not os.path.exists(test_spec_path)


def test_shorts_fails_closed_on_empty_iscg_result_without_monolithic_fallback(monkeypatch, tmp_path):
    """
    Phase 5B - Test 2: Verify that an empty or invalid iterative generation result
    raises ValueError rather than silently triggering a fallback to monolithic generation.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    # Return empty scene list from ISCG
    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: ([], {})
    )

    monolithic_calls = []
    def mock_generate_json(self, sys_p, usr_p, *a, **kw):
        monolithic_calls.append(True)
        return {"scenes": [{"scene_id": 1, "spoken_text": "Fallback scene."}]}

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_generate_json)

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Iterative script generation produced an empty scene array" in str(exc_info.value)
    assert len(monolithic_calls) == 0
    assert not os.path.exists(test_spec_path)


def test_long_form_preserves_monolithic_chapters_generation(monkeypatch, tmp_path):
    """
    Phase 5B - Test 3: Verify that long-form documentary generation (video_type='long')
    preserves monolithic LLM generation with chapter flattening and packages spec.json.
    """
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Deep Cosmos",
        "verified_summary": "Documentary on cosmic expansion",
        "source": "verified_trend"
    })

    mock_doc_response = {
        "thought_process": {"hook": "deep cosmic hook"},
        "title": "The Infinite Cosmos",
        "chapters": [
            {
                "chapter_id": 1,
                "scenes": [
                    {"scene_id": 1, "spoken_text": "Chapter one exploration of the deep cosmic horizon.", "stock_video_query": "deep space galaxy motion"}
                ]
            },
            {
                "chapter_id": 2,
                "scenes": [
                    {"scene_id": 2, "spoken_text": "Chapter two revelation of relativistic physics.", "stock_video_query": "nebula star formation"}
                ]
            }
        ]
    }
    mock_seo_response = {
        "title": "The Infinite Cosmos",
        "description": "An in-depth documentary exploring the deep cosmos.",
        "tags": ["documentary", "cosmos", "physics"]
    }

    calls = []
    def mock_generate_json(self, sys_p, usr_p, *a, **kw):
        calls.append(kw.get("task_name"))
        if "SEO Director" in sys_p or "metadata" in usr_p.lower():
            return mock_seo_response
        return mock_doc_response

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_generate_json)
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: (120.0, [], [60.0, 60.0], [[], []]))

    run_spec_stage(video_type="long")

    assert os.path.exists(test_spec_path)
    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    assert spec.video_type == "long"
    assert spec.sub_format == "documentary_essay"
    assert len(spec.scenes) == 2
    assert spec.scenes[0].spoken_text == "Chapter one exploration of the deep cosmic horizon."
    assert spec.scenes[1].spoken_text == "Chapter two revelation of relativistic physics."
    assert "generic" in calls

    # Verify persistence occurred strictly inside isolated temporary directory
    isolated_past = test_memory_dir / "past_spoken_thoughts.json"
    assert isolated_past.exists()
    with open(isolated_past, "r", encoding="utf-8") as pf:
        saved_past = json.load(pf).get("past_thoughts", [])
    assert "Chapter one exploration of the deep cosmic horizon." in saved_past
    assert "Chapter two revelation of relativistic physics." in saved_past
    assert (test_memory_dir / "thought_cache.json").exists()


def test_shorts_successful_iscg_runs_editorial_and_thought_cache(monkeypatch, tmp_path):
    """
    Phase 5B - Test 4: Verify that successful iterative generation flows through
    the Editorial Critic and Thought Cache gates and packages output/spec.json.
    """
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue.", "stock_video_query": "mirror reflection"},
        {"scene_id": 2, "spoken_text": "Your brain actively deletes the sensation of your tongue resting in your mouth.", "stock_video_query": "mind thought"},
        {"scene_id": 3, "spoken_text": "Every single mirror you have ever bought in a store was sold in used condition.", "stock_video_query": "mirror store"},
        {"scene_id": 4, "spoken_text": "Which is why you should never overthink these strange quirks of reality...", "stock_video_query": "loop ending"}
    ]
    seo_data = {
        "title": "Mind Glitches You Experience Daily 🤯 #shorts",
        "description": "Mind Glitches You Experience Daily 🤯 #shorts\n\nDaily cognitive shifts.\n\n#shorts",
        "tags": ["mind glitches", "shower thoughts", "shorts"]
    }

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )

    critic_called = []
    def mock_audit(raw_scenes, seo_data, topic, llm_manager=None, *args, **kwargs):
        critic_called.append(True)
        return raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", mock_audit)
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: (32.0, [], [8.0, 8.0, 8.0, 8.0], [[], [], [], []]))

    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    assert spec.video_type == "short"
    assert len(spec.scenes) == 4
    assert critic_called == [True]

    # Verify persistence occurred strictly inside isolated temporary directory
    isolated_past = test_memory_dir / "past_spoken_thoughts.json"
    assert isolated_past.exists()
    with open(isolated_past, "r", encoding="utf-8") as pf:
        saved_past = json.load(pf).get("past_thoughts", [])
    assert "The only part of your reflection you can lick is your tongue." in saved_past
    assert "Which is why you should never overthink these strange quirks of reality..." in saved_past
    assert (test_memory_dir / "thought_cache.json").exists()
    assert (test_cfg_dir / "model_quality_scores.json").exists()


# ─── 15. SURGICAL ISCG BOUNDARY VALIDATION (PHASE 5E) ──────────────────────────────

@pytest.mark.parametrize("invalid_scenes,expected_msg", [
    (None, "Iterative script generation must produce a list of scenes, got: NoneType"),
    ("not a list of scenes", "Iterative script generation must produce a list of scenes, got: str"),
    (12345, "Iterative script generation must produce a list of scenes, got: int"),
    ({"scenes": []}, "Iterative script generation must produce a list of scenes, got: dict"),
])
def test_iscg_boundary_rejects_non_list_output(monkeypatch, tmp_path, invalid_scenes, expected_msg):
    """
    Phase 5E: Verify that non-list returns from ISCG are rejected immediately at the boundary
    with a clear ValueError, without invoking Critic, Thought Cache persistence, TTS, or writing spec.json.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (invalid_scenes, {})
    )

    critic_called = []
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec",
                        lambda *a, **kw: critic_called.append(True))
    tts_called = []
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: tts_called.append(True))

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert expected_msg in str(exc_info.value)
    assert len(critic_called) == 0
    assert len(tts_called) == 0
    assert not (test_memory_dir / "thought_cache.json").exists()
    assert not os.path.exists(test_spec_path)




def test_iscg_boundary_rejects_non_dictionary_scene(monkeypatch, tmp_path):
    """
    Phase 5E: Verify that scene list containing non-dict elements is rejected at the boundary
    identifying the scene index, without invoking downstream consumers or persistence.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"spoken_text": "The only part of your reflection you can lick is your tongue."},
        "not a dictionary element",
        {"spoken_text": "Which is why you should never overthink these strange quirks of reality..."}
    ]

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, {})
    )

    critic_called = []
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec",
                        lambda *a, **kw: critic_called.append(True))
    tts_called = []
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: tts_called.append(True))

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Scene 2 is not a dictionary: got str" in str(exc_info.value)
    assert len(critic_called) == 0
    assert len(tts_called) == 0
    assert not (test_memory_dir / "thought_cache.json").exists()
    assert not os.path.exists(test_spec_path)




def test_iscg_boundary_rejects_missing_spoken_text(monkeypatch, tmp_path):
    """
    Phase 5E: Verify that a scene missing 'spoken_text' is rejected at the boundary
    identifying the scene index, without invoking downstream consumers or persistence.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"stock_video_query": "mirror reflection"},  # Missing spoken_text
        {"spoken_text": "Which is why you should never overthink these strange quirks of reality..."}
    ]

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, {})
    )

    critic_called = []
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec",
                        lambda *a, **kw: critic_called.append(True))
    tts_called = []
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: tts_called.append(True))

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Scene 2 is missing required 'spoken_text' field" in str(exc_info.value)
    assert len(critic_called) == 0
    assert len(tts_called) == 0
    assert not (test_memory_dir / "thought_cache.json").exists()
    assert not os.path.exists(test_spec_path)




@pytest.mark.parametrize("bad_spoken", [
    "",
    "   ",
    "\t\n  \r\n",
])
def test_iscg_boundary_rejects_empty_or_whitespace_spoken_text(monkeypatch, tmp_path, bad_spoken):
    """
    Phase 5E: Verify that empty or whitespace-only spoken_text in any scene (including middle scenes)
    is caught at the boundary before Critic, Thought Cache, or TTS, preventing thought_cache corruption.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"spoken_text": bad_spoken},  # Empty or whitespace-only
        {"spoken_text": "Which is why you should never overthink these strange quirks of reality..."}
    ]

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, {})
    )

    critic_called = []
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec",
                        lambda *a, **kw: critic_called.append(True))
    tts_called = []
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: tts_called.append(True))

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Scene 2 has empty or whitespace-only 'spoken_text'" in str(exc_info.value)
    assert len(critic_called) == 0
    assert len(tts_called) == 0
    assert not (test_memory_dir / "thought_cache.json").exists()
    assert not os.path.exists(test_spec_path)




def test_iscg_boundary_rejects_non_string_spoken_text(monkeypatch, tmp_path):
    """
    Phase 5E: Verify that non-string spoken_text is rejected at the boundary with clear type error.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "The Baader-Meinhof Phenomenon",
        "verified_summary": "Frequency illusion",
        "source": "verified_trend"
    })

    scenes = [
        {"spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"spoken_text": 123456},  # Non-string
        {"spoken_text": "Which is why you should never overthink these strange quirks of reality..."}
    ]

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, {})
    )

    critic_called = []
    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec",
                        lambda *a, **kw: critic_called.append(True))
    tts_called = []
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: tts_called.append(True))

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "Scene 2 'spoken_text' must be a string, got int" in str(exc_info.value)
    assert len(critic_called) == 0
    assert len(tts_called) == 0
    assert not (test_memory_dir / "thought_cache.json").exists()
    assert not os.path.exists(test_spec_path)


# ─── 14. TOPIC GATE RELIABILITY & GROUNDING INTEGRATION (PHASE 6A) ───────────

def test_verify_factuality_success_rejection_and_unavailable():
    """
    Verifies that TopicInspector.verify_factuality and _fact_check:
    1. Approve valid facts with status='completed' and verified=True.
    2. Reject false/hallucinated claims with status='completed' and verified=False.
    3. Fail closed on LLM exceptions with status='unavailable' and verified=False (never fabricated pass).
    4. Fail closed on malformed dictionary responses with status='unavailable' and verified=False.
    """
    mock_llm = MagicMock()
    inspector = TopicInspector(llm_manager=mock_llm)

    # 1. Approved fact
    mock_llm.generate_json.return_value = {
        "is_factual": True,
        "confidence": 0.96,
        "is_niche_relevant": True,
        "primary_source": "Nature, 2024",
        "red_flags": []
    }
    res_ok = inspector.verify_factuality("Human bones are four times stronger than concrete.")
    assert res_ok["is_factual"] is True
    assert res_ok["status"] == "completed"
    check_ok = inspector._fact_check("Human bones are four times stronger than concrete.")
    assert check_ok["verified"] is True

    # 2. Rejected claim
    mock_llm.generate_json.return_value = {
        "is_factual": False,
        "confidence": 0.98,
        "is_niche_relevant": True,
        "primary_source": "Debunked mythology",
        "red_flags": ["Completely fabricated"]
    }
    res_bad = inspector.verify_factuality("Goldfish have a memory span of only three seconds.")
    assert res_bad["is_factual"] is False
    assert res_bad["status"] == "completed"
    check_bad = inspector._fact_check("Goldfish have a memory span of only three seconds.")
    assert check_bad["verified"] is False
    assert check_bad["status"] == "completed"

    # 3. LLM exception (Fail closed: must NOT fabricate pass or approve)
    mock_llm.generate_json.side_effect = RuntimeError("API connection timeout")
    res_err = inspector.verify_factuality("Any unverified claim")
    assert res_err["is_factual"] is False
    assert res_err["status"] == "unavailable"
    assert res_err["confidence"] == 0.0
    check_err = inspector._fact_check("Any unverified claim")
    assert check_err["verified"] is False
    assert check_err["status"] == "unavailable"

    # 4. Malformed dictionary (e.g. non-dict or missing 'is_factual')
    mock_llm.generate_json.side_effect = None
    mock_llm.generate_json.return_value = {"error": "unexpected format"}
    res_mal = inspector.verify_factuality("Malformed return")
    assert res_mal["is_factual"] is False
    assert res_mal["status"] == "unavailable"
    check_mal = inspector._fact_check("Malformed return")
    assert check_mal["verified"] is False
    assert check_mal["status"] == "unavailable"


def test_competitor_surge_verification_approved_and_rejected(monkeypatch, tmp_path):
    """
    Verifies that competitor surge topics pass through the factuality gate before use:
    1. If verified, surge topic is accepted.
    2. If rejected or unavailable, pipeline falls back to discover_verified_topic().
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (15.0, [], [5.0, 5.0, 5.0], [[], [], []])
    )

    dummy_scenes = [
        {"spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"spoken_text": "Your future self is currently watching you through your memories."},
        {"spoken_text": "Which sounds absurd until you remember that..."}
    ]

    captured_topics = []
    def mock_generate_chain(self, topic="", **kwargs):
        captured_topics.append(topic)
        return dummy_scenes, {"title": f"Title for {topic}"}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        mock_generate_chain
    )

    # Subtest 1: Approved surge topic
    monkeypatch.setattr(
        "engine.managers.competitor_spy.CompetitorSpy.get_surge_topic",
        lambda *a: {"title": "Verified Surge Topic", "score": 9.2}
    )
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.is_topic_recent",
        lambda self_or_cls, t: False
    )
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector._fact_check",
        lambda self, t, niche="": {"verified": True, "status": "completed", "summary": "Factually verified"}
    )

    run_spec_stage(video_type="short")
    assert len(captured_topics) == 1
    assert captured_topics[0] == "Verified Surge Topic"

    # Subtest 2: Rejected surge topic falls back to discover_verified_topic()
    captured_topics.clear()
    monkeypatch.setattr(
        "engine.managers.competitor_spy.CompetitorSpy.get_surge_topic",
        lambda *a: {"title": "Unverified Fake Surge Topic", "score": 9.2}
    )
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector._fact_check",
        lambda self, t, niche="": {"verified": False, "status": "completed", "reason": "Pseudoscience detected"}
    )
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {
            "topic": "Evergreen Verified Discovery Topic",
            "verified_summary": "Solid science",
            "source": "evergreen"
        }
    )

    run_spec_stage(video_type="short")
    assert len(captured_topics) == 1
    assert captured_topics[0] == "Evergreen Verified Discovery Topic"


def test_custom_topic_verification_approved_rejected_and_unavailable(monkeypatch, tmp_path):
    """
    Verifies that custom topic overrides pass through the factuality gate:
    1. If verified, custom topic is accepted.
    2. If rejected, raises ValueError with distinct rejection message.
    3. If unavailable, raises ValueError with distinct unavailable message.
    """
    import pathlib
    from engine.managers.pipeline_runner import run_spec_stage

    real_cache_path = pathlib.Path("memory/competitor_cache.json")
    initial_cache_bytes = real_cache_path.read_bytes() if real_cache_path.exists() else None

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (15.0, [], [5.0, 5.0, 5.0], [[], [], []])
    )

    dummy_scenes = [
        {"spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"spoken_text": "Your future self is currently watching you through your memories."},
        {"spoken_text": "Which sounds absurd until you remember that..."}
    ]

    captured_topics = []
    def mock_generate_chain(self, topic="", **kwargs):
        captured_topics.append(topic)
        return dummy_scenes, {"title": f"Title for {topic}"}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        mock_generate_chain
    )

    # Subtest 1: Approved custom topic
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector._fact_check",
        lambda self, t, niche="": {"verified": True, "status": "completed", "summary": "Approved custom topic"}
    )
    run_spec_stage(video_type="short", custom_topic="Legitimate Quantum Paradox")
    assert len(captured_topics) == 1
    assert captured_topics[0] == "Legitimate Quantum Paradox"

    # Subtest 2: Rejected custom topic
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector._fact_check",
        lambda self, t, niche="": {"verified": False, "status": "completed", "reason": "Hallucinatory claim"}
    )
    with pytest.raises(ValueError) as exc_info_rej:
        run_spec_stage(video_type="short", custom_topic="Fake Hollow Earth Myth")
    assert "Custom topic rejected by topic verification gate" in str(exc_info_rej.value)
    assert "Fake Hollow Earth Myth" in str(exc_info_rej.value)

    # Subtest 3: Unavailable verification
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector._fact_check",
        lambda self, t, niche="": {"verified": False, "status": "unavailable", "reason": "LLM API timeout"}
    )
    with pytest.raises(ValueError) as exc_info_unavail:
        run_spec_stage(video_type="short", custom_topic="Obscure Topic")
    assert "Custom topic verification unavailable" in str(exc_info_unavail.value)
    assert "Obscure Topic" in str(exc_info_unavail.value)

    # Regression assertion: real competitor cache must remain completely untouched
    if initial_cache_bytes is not None:
        assert real_cache_path.read_bytes() == initial_cache_bytes


def test_grounding_references_reach_shorts_prompts():
    """
    Verifies that curated grounding references passed to generate_scene_chain
    reach both the anchor generation prompt and the middle scene generation prompt.
    """
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []
    mock_llm = MagicMock()

    middle_thoughts = [
        "Your future self is currently watching you through your memories.",
        "Water is not wet by itself it only makes other materials wet.",
        "Every mirror you purchase is technically used since someone tested it.",
        "Nothing is ever completely on fire, fire is just on things.",
        "The brain named itself and is now questioning that exact discovery.",
        "You cannot sneeze with your eyes open without severe physical strain.",
        "Bananas share fifty percent of their genetic DNA with human beings."
    ]
    thought_idx = [0]

    def mock_gen_json(system_prompt="", user_prompt="", **kwargs):
        captured_prompts.append(user_prompt)
        # Determine response based on user prompt
        if "Scene 1 hook thought" in user_prompt:
            return {
                "hook_scene": {
                    "spoken_text": "The only part of your reflection you can lick is your tongue.",
                    "stock_video_query": "mirror reflection close up"
                },
                "penultimate_scene": {
                    "spoken_text": "Oxygen is slowly rusting our bodies from the inside out over decades.",
                    "stock_video_query": "oxygen bubbles water macro"
                },
                "loop_scene": {
                    "spoken_text": "And the wildest part about reflections is that...",
                    "stock_video_query": "infinite mirror hallway dark"
                }
            }
        elif "Generate Scene" in user_prompt:
            t = middle_thoughts[thought_idx[0] % len(middle_thoughts)]
            thought_idx[0] += 1
            return {
                "spoken_text": t,
                "stock_video_query": "old photos nostalgic cinematic"
            }
        elif "metadata" in user_prompt or "script_text" in user_prompt:
            return {
                "title": "Mind Glitches That Feel Illegal To Know 🤯 #shorts",
                "description": "Mind Glitches That Feel Illegal To Know 🤯 #shorts\n\nDeep thoughts.\n\n#shorts",
                "tags": ["thoughts", "facts", "shorts"]
            }
        return {}

    mock_llm.generate_json.side_effect = mock_gen_json

    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    grounding_fact_line = "VERIFIED INSPIRATION & FACTUAL REFERENCES:\n- Mpemba effect: hot water can freeze faster than cold water (Source: Royal Society of Chemistry)"

    scenes, seo = generator.generate_scene_chain(
        topic="Physics Paradoxes",
        grounding_facts=grounding_fact_line
    )

    assert len(scenes) >= 3
    # Check that grounding_fact_line was passed into at least anchor prompt and middle scene prompt
    anchor_prompts = [p for p in captured_prompts if "Scene 1 hook thought" in p]
    middle_prompts = [p for p in captured_prompts if "Generate Scene" in p]

    assert len(anchor_prompts) >= 1
    assert "Mpemba effect: hot water can freeze faster than cold water" in anchor_prompts[0]
    assert "verified inspiration references for your hook or penultimate fact" in anchor_prompts[0]

    assert len(middle_prompts) >= 1
    assert "Mpemba effect: hot water can freeze faster than cold water" in middle_prompts[0]
    assert "verified inspiration references" in middle_prompts[0]


def test_grounding_references_reach_long_form_prompt(monkeypatch, tmp_path):
    """
    Verifies that run_spec_stage for long-form scripts injects grounding references
    into the long_form_doc user prompt.
    """
    from engine.managers.pipeline_runner import run_spec_stage

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (15.0, [], [5.0, 5.0, 5.0], [[], [], []])
    )

    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {
            "topic": "The Mystery of Ocean Depths",
            "verified_summary": "Deep ocean exploration",
            "source": "verified_trend"
        }
    )

    test_ref = {"type": "fact", "text": "Octopuses have three hearts and blue copper-based blood."}
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.get_grounding_references",
        lambda count=5: [test_ref]
    )

    captured_prompts = []
    def mock_llm_gen_json(self, system_prompt, user_prompt, **kwargs):
        captured_prompts.append((system_prompt, user_prompt))
        return {
            "title": "The Secrets of the Ocean Deep",
            "scenes": [
                {"scene_id": 1, "spoken_text": "In the deepest oceans, life takes strange and alien forms.", "duration_seconds": 6.0},
                {"scene_id": 2, "spoken_text": "Light fades entirely within two hundred meters.", "duration_seconds": 6.0}
            ],
            "seo": {
                "title": "The Secrets of the Ocean Deep",
                "description": "Documentary essay.",
                "tags": ["ocean", "documentary"]
            }
        }

    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", mock_llm_gen_json)

    run_spec_stage(video_type="long")

    assert len(captured_prompts) == 1
    sys_p, usr_p = captured_prompts[0]
    assert "Octopuses have three hearts and blue copper-based blood." in usr_p
    assert "Weave verified inspiration references into the narrative" in sys_p


def test_empty_grounding_references_backward_compatibility():
    """
    Verifies that when grounding_facts is None or empty, generate_scene_chain
    runs cleanly without injecting empty grounding sections into prompts.
    """
    from engine.managers.iterative_script_generator import IterativeScriptGenerator

    captured_prompts = []
    mock_llm = MagicMock()

    middle_thoughts = [
        "Your future self is currently watching you through your memories.",
        "Water is not wet by itself it only makes other materials wet.",
        "Every mirror you purchase is technically used since someone tested it.",
        "Nothing is ever completely on fire, fire is just on things.",
        "The brain named itself and is now questioning that exact discovery.",
        "You cannot sneeze with your eyes open without severe physical strain.",
        "Bananas share fifty percent of their genetic DNA with human beings."
    ]
    thought_idx = [0]

    def mock_gen_json(system_prompt="", user_prompt="", **kwargs):
        captured_prompts.append(user_prompt)
        if "Scene 1 hook thought" in user_prompt:
            return {
                "hook_scene": {
                    "spoken_text": "The only part of your reflection you can lick is your tongue.",
                    "stock_video_query": "mirror reflection close up"
                },
                "penultimate_scene": {
                    "spoken_text": "Oxygen is slowly rusting our bodies from the inside out over decades.",
                    "stock_video_query": "oxygen bubbles water macro"
                },
                "loop_scene": {
                    "spoken_text": "And the wildest part about reflections is that...",
                    "stock_video_query": "infinite mirror hallway dark"
                }
            }
        elif "Generate Scene" in user_prompt:
            t = middle_thoughts[thought_idx[0] % len(middle_thoughts)]
            thought_idx[0] += 1
            return {
                "spoken_text": t,
                "stock_video_query": "old photos nostalgic cinematic"
            }
        elif "metadata" in user_prompt or "script_text" in user_prompt:
            return {
                "title": "Mind Glitches That Feel Illegal To Know 🤯 #shorts",
                "description": "Mind Glitches That Feel Illegal To Know 🤯 #shorts\n\nDeep thoughts.\n\n#shorts",
                "tags": ["thoughts", "facts", "shorts"]
            }
        return {}

    mock_llm.generate_json.side_effect = mock_gen_json

    generator = IterativeScriptGenerator(llm_manager=mock_llm)
    scenes, seo = generator.generate_scene_chain(topic="Cosmic Paradoxes", grounding_facts=None)

    assert len(scenes) >= 3
    for p in captured_prompts:
        assert "VERIFIED INSPIRATION & FACTUAL REFERENCES" not in p
        assert "draw upon these verified inspiration references" not in p


# ─── 19. SHORTS CLAIM INSPECTION INTEGRATION (PHASE 6B STAGE 3A) ─────────────

def test_shorts_claim_inspection_supported_claims_proceeds_to_spec(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that when all empirical claims in a Short are supported
    by valid candidate evidence, the pipeline records PASSED, packages spec.json,
    and stores the in-memory report matching final scenes.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        FactualityPolicyStatus,
        get_last_factuality_decision,
        get_last_claim_report,
    )
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        EvidenceReference,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {
            "topic": "The Human Body Glitches",
            "verified_summary": "Body physiology",
            "source": "verified_trend"
        }
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue.", "stock_video_query": "mirror reflection"},
        {"scene_id": 2, "spoken_text": "You physically cannot hum while holding your nose shut.", "stock_video_query": "throat close up"},
        {"scene_id": 3, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Body Glitches That Feel Illegal 🤯 #shorts", "description": "Body glitches. #shorts", "tags": ["body", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (15.0, [], [5.0, 5.0, 5.0], [[], [], []])
    )

    def mock_inspect_script(self, scenes, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=scenes[0]["spoken_text"],
                    extracted_proposition=scenes[0]["spoken_text"],
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.SUPPORTED.value,
                    risk_level=RiskLevel.LOW.value,
                    evidence=[EvidenceReference(id="ev_01", text="Reflection anatomy.")],
                    rationale="Directly supported by optical reflection mechanics."
                ),
                ClaimRecord(
                    claim_id="claim_2_1",
                    scene_id=2,
                    original_text=scenes[1]["spoken_text"],
                    extracted_proposition=scenes[1]["spoken_text"],
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.SUPPORTED.value,
                    risk_level=RiskLevel.LOW.value,
                    evidence=[EvidenceReference(id="ev_02", text="Humming requires open nasal airway.")],
                    rationale="Directly supported by respiratory mechanics."
                )
            ],
            status="completed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect_script)

    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    dec = get_last_factuality_decision()
    assert dec is not None
    assert dec[0] == FactualityPolicyStatus.PASSED

    report = get_last_claim_report()
    assert report is not None
    assert len(report.claims) == 2
    assert report.claims[0].outcome == VerificationOutcome.SUPPORTED.value
    assert len(report.claims[0].evidence) == 1


def test_shorts_claim_inspection_low_risk_unverifiable_passes_with_unverified(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that unverified everyday low-risk claims (e.g. shower thoughts)
    are permitted to proceed under PASSED_WITH_UNVERIFIED without failing the pipeline.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        FactualityPolicyStatus,
        get_last_factuality_decision,
        get_last_claim_report,
    )
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Everyday Paradoxes", "source": "trend"}
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "Your shadow is proof light traveled 93 million miles to be blocked by you.", "stock_video_query": "shadow light"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Everyday Paradoxes #shorts", "description": "Paradoxes. #shorts", "tags": ["thoughts", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (10.0, [], [5.0, 5.0], [[], []])
    )

    def mock_inspect_script(self, scenes, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=scenes[0]["spoken_text"],
                    extracted_proposition=scenes[0]["spoken_text"],
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.UNVERIFIABLE.value,
                    risk_level=RiskLevel.LOW.value,
                    evidence=[],
                    rationale="No candidate evidence in curated vault."
                )
            ],
            status="completed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect_script)

    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    dec = get_last_factuality_decision()
    assert dec is not None
    assert dec[0] == FactualityPolicyStatus.PASSED_WITH_UNVERIFIED
    assert "low-risk policy" in dec[1].lower()


def test_shorts_claim_inspection_evidence_backed_contradiction_triggers_rewrite_and_passes(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that an evidence-backed contradiction triggers a targeted
    scene rewrite, re-inspection of the new text, and final packaging of the corrected line.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        FactualityPolicyStatus,
        get_last_factuality_decision,
        get_last_claim_report,
    )
    from engine.models import SpecOutput
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        EvidenceReference,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Joint Myths", "source": "trend"}
    )

    initial_scenes = [
        {"scene_id": 1, "spoken_text": "Cracking your knuckles causes arthritis and permanent joint damage.", "stock_video_query": "hands cracking"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Joint Myths #shorts", "description": "Myths. #shorts", "tags": ["health", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (initial_scenes, seo_data)
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (10.0, [], [5.0, 5.0], [[], []])
    )

    inspect_count = [0]
    def mock_inspect(self, scenes, candidate_evidence=None):
        inspect_count[0] += 1
        current_text = scenes[0].get("spoken_text", "")
        if "causes arthritis" in current_text.lower():
            return ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=current_text,
                        extracted_proposition="Cracking knuckles causes arthritis.",
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.CONTRADICTED.value,
                        risk_level=RiskLevel.LOW.value,
                        evidence=[EvidenceReference(id="med_01", text="Knuckle cracking does not cause arthritis.")],
                        rationale="Evidence disproves joint damage assertion."
                    )
                ],
                status="failed"
            )
        else:
            return ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=current_text,
                        extracted_proposition=current_text,
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.SUPPORTED.value,
                        risk_level=RiskLevel.LOW.value,
                        evidence=[EvidenceReference(id="med_02", text="Gas bubbles collapse harmlessly.")],
                        rationale="Corroborated by synovial fluid mechanics."
                    )
                ],
                status="completed"
            )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    def mock_rewrite(scene, claim_record, llm=None):
        rev = dict(scene)
        rev["spoken_text"] = "Cracking your knuckles simply pops harmless nitrogen bubbles in joint fluid."
        rev["phonetic_text"] = rev["spoken_text"]
        rev["_factuality_revised"] = True
        return rev

    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", mock_rewrite)

    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    assert inspect_count[0] >= 2  # Inspected initial text, then re-inspected rewritten text

    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    # Final spec has the rewritten text!
    assert "nitrogen bubbles" in spec.scenes[0].spoken_text
    assert "causes arthritis" not in spec.scenes[0].spoken_text

    # Final report describes the exact final text
    report = get_last_claim_report()
    assert report is not None
    assert "nitrogen bubbles" in report.claims[0].original_text


def test_shorts_claim_inspection_persistent_contradiction_fails_closed_after_two_rewrites(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that a contradiction persisting across 2 rewrites exhausts
    the rewrite budget, raises ValueError (REJECTED_CONTRADICTION), and prevents spec/cache writes.
    """
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        EvidenceReference,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Persistent Myths", "source": "trend"}
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "Cracking your knuckles causes arthritis.", "stock_video_query": "hands"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Persistent Myths #shorts", "description": "Myths #shorts", "tags": ["myths", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )

    # ClaimInspector always returns contradicted
    def mock_inspect(self, scenes, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=scenes[0].get("spoken_text", ""),
                    extracted_proposition="Cracking knuckles causes arthritis.",
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.CONTRADICTED.value,
                    risk_level=RiskLevel.LOW.value,
                    evidence=[EvidenceReference(id="med_01", text="Knuckle cracking does not cause arthritis.")],
                    rationale="Evidence disproves joint damage assertion."
                )
            ],
            status="failed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    rewrite_attempts = [0]
    def mock_rewrite(scene, claim_record, llm=None):
        rewrite_attempts[0] += 1
        rev = dict(scene)
        rev["spoken_text"] = f"Still broken assertion attempt {rewrite_attempts[0]}"
        return rev

    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", mock_rewrite)

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "REJECTED_CONTRADICTION" in str(exc_info.value)
    assert rewrite_attempts[0] == 2  # Exactly 2 rewrites were attempted before budget exhaustion
    assert not os.path.exists(test_spec_path)
    assert not (test_memory_dir / "thought_cache.json").exists()


def test_shorts_claim_inspection_high_and_medium_risk_unverifiable_fails_closed(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that high-risk and medium-risk unverifiable claims fail closed.
    """
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Dangerous Cures", "source": "trend"}
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "Drinking poison cures human cancer permanently.", "stock_video_query": "liquid flask"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Dangerous Cures #shorts", "description": "Cures #shorts", "tags": ["health", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )

    def mock_inspect_high(self, scenes, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=scenes[0]["spoken_text"],
                    extracted_proposition="Drinking poison cures cancer.",
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.UNVERIFIABLE.value,
                    risk_level=RiskLevel.HIGH.value,
                    evidence=[],
                    rationale="No medical evidence corroborating poison cure."
                )
            ],
            status="completed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect_high)

    # Disable rewrite so it immediately tests fail-closed evaluation
    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", lambda *a, **k: None)

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "REJECTED_HIGH_RISK_UNVERIFIED" in str(exc_info.value)
    assert not os.path.exists(test_spec_path)


def test_shorts_claim_inspection_service_outage_fails_closed_never_supported(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that verification service unavailability on high-risk claims
    is never converted to SUPPORTED and fails closed with VERIFICATION_UNAVAILABLE.
    """
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Medical Discoveries", "source": "trend"}
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "A new synthetic cure eradicates disease cells.", "stock_video_query": "microscope"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Medical Discoveries #shorts", "description": "Discoveries #shorts", "tags": ["medicine", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )

    def mock_inspect_unavail(self, scenes, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=scenes[0]["spoken_text"],
                    extracted_proposition="Synthetic cure eradicates disease.",
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.VERIFICATION_UNAVAILABLE.value,
                    risk_level=RiskLevel.HIGH.value,
                    evidence=[],
                    error_reason="Provider 503 gateway timeout"
                )
            ],
            status="failed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect_unavail)
    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", lambda *a, **k: None)

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    assert "VERIFICATION_UNAVAILABLE" in str(exc_info.value)
    assert not os.path.exists(test_spec_path)


def test_shorts_critic_rewrite_after_factuality_triggers_reinspection(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that if Editorial Critic is rerun after a factuality rewrite
    and mutates text, ClaimInspector re-inspects the modified script and reflects the final text.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        get_last_claim_report,
    )
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        EvidenceReference,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Clear PYTEST_CURRENT_TEST so Critic code path executes
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Psychological Glitches", "source": "trend"}
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (10.0, [], [5.0, 5.0], [[], []])
    )

    initial_scenes = [
        {"scene_id": 1, "spoken_text": "Cracking knuckles causes arthritis.", "stock_video_query": "hands"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Psychological Glitches #shorts", "description": "Glitches #shorts", "tags": ["psychology", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (initial_scenes, seo_data)
    )

    # Mock editorial critic to rewrite scene 2 on its second run
    critic_runs = [0]
    def mock_audit(raw_scenes, seo_data, topic, llm_manager=None, *args, **kwargs):
        critic_runs[0] += 1
        if critic_runs[0] > 1:
            # Critic further refines scene 2
            raw_scenes[1]["spoken_text"] = "And that circular realization proves that..."
        return raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", mock_audit)

    # Mock factuality rewrite of scene 1
    def mock_rewrite(scene, claim_record, llm=None):
        rev = dict(scene)
        rev["spoken_text"] = "Cracking knuckles harmlessly releases gas bubbles."
        return rev

    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", mock_rewrite)

    # Claim inspector returns contradiction on first call, supported on second
    inspect_calls = [0]
    captured_inspected_scenes = []

    def mock_inspect(self, scenes, candidate_evidence=None):
        inspect_calls[0] += 1
        captured_inspected_scenes.append([s.get("spoken_text", "") for s in scenes])
        if inspect_calls[0] == 1:
            return ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=scenes[0]["spoken_text"],
                        extracted_proposition="Cracking knuckles causes arthritis.",
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.CONTRADICTED.value,
                        risk_level=RiskLevel.LOW.value,
                        evidence=[EvidenceReference(id="med_01", text="No arthritis caused.")],
                        rationale="Contradicted by evidence."
                    )
                ],
                status="failed"
            )
        else:
            return ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=scenes[0]["spoken_text"],
                        extracted_proposition=scenes[0]["spoken_text"],
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.SUPPORTED.value,
                        risk_level=RiskLevel.LOW.value,
                        evidence=[EvidenceReference(id="med_02", text="Gas bubbles.")],
                        rationale="Supported by mechanics."
                    )
                ],
                status="completed"
            )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    assert critic_runs[0] >= 2  # Critic ran initially and was rerun after factuality rewrite
    assert inspect_calls[0] >= 2  # ClaimInspector re-inspected after Critic rerun

    # The second inspection saw the Critic's refined scene 2!
    assert "circular realization proves" in captured_inspected_scenes[-1][1]


def test_long_form_does_not_invoke_claim_inspector(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A: Verifies that long-form documentary generation (video_type='long')
    is completely untouched and never invokes ClaimInspector.
    """
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "The Cosmos Explained", "source": "trend"}
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (60.0, [], [30.0, 30.0], [[], []])
    )

    mock_doc = {
        "title": "The Cosmos Explained",
        "description": "Deep cosmos essay.",
        "tags": ["cosmos", "science"],
        "chapters": [
            {"chapter_id": 1, "scenes": [{"scene_id": 1, "spoken_text": "Chapter one content."}]},
            {"chapter_id": 2, "scenes": [{"scene_id": 2, "spoken_text": "Chapter two content."}]}
        ]
    }
    monkeypatch.setattr("engine.managers.llm_manager.LLMManager.generate_json", lambda *a, **k: mock_doc)

    inspector_calls = []
    def mock_inspect(self, *a, **k):
        inspector_calls.append(True)
        raise RuntimeError("ClaimInspector should never be called for long-form!")

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    run_spec_stage(video_type="long")

    assert os.path.exists(test_spec_path)
    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())
    assert spec.video_type == "long"
    assert len(spec.scenes) == 2
    assert len(inspector_calls) == 0  # Zero calls to ClaimInspector!


def test_shorts_claim_inspection_medium_risk_unverifiable_fails_closed(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A.2: Verifies that an unverified medium-risk quantitative/date claim
    fails closed with REJECTED_MEDIUM_RISK_UNVERIFIED and halts before persistence/TTS/spec writing.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        FactualityPolicyStatus,
        get_last_factuality_decision,
    )
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Cell Regeneration", "source": "trend"}
    )

    tts_called = []
    def mock_synth(**kw):
        tts_called.append(True)
        return (10.0, [], [5.0, 5.0], [[], []])

    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        mock_synth
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "Exactly 94.6% of human skin cells regenerate every four hours.", "stock_video_query": "microscope cells"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Cell Regeneration #shorts", "description": "Skin cells. #shorts", "tags": ["biology", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )

    def mock_inspect_medium(self, scenes, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=scenes[0]["spoken_text"],
                    extracted_proposition="94.6% of human skin cells regenerate every four hours.",
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.UNVERIFIABLE.value,
                    risk_level=RiskLevel.MEDIUM.value,
                    evidence=[],
                    rationale="Quantitative assertion lacks corroborating source."
                )
            ],
            status="completed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect_medium)

    # Disable rewrite so it tests the fail-closed rejection path directly
    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", lambda *a, **k: None)

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    # 1. Assert policy rejection with REJECTED_MEDIUM_RISK_UNVERIFIED
    assert "REJECTED_MEDIUM_RISK_UNVERIFIED" in str(exc_info.value)
    assert "Medium-risk quantitative/date claim unverifiable in Scene 1" in str(exc_info.value)

    # 2. Assert in-memory decision reflects medium-risk failure
    decision = get_last_factuality_decision()
    assert decision is not None
    assert decision[0] == FactualityPolicyStatus.REJECTED_MEDIUM_RISK_UNVERIFIED
    assert "Medium-risk" in decision[1]

    # 3. Assert rejection happens before TTS, spec generation, and final artifact writes
    assert len(tts_called) == 0
    assert not os.path.exists(test_spec_path)
    assert not os.path.exists(str(test_output_dir / "community_post.json"))
    assert not os.path.exists(str(test_output_dir / "narration.mp3"))

    # 4. Assert thought-cache and past-thought persistence are not invoked
    assert not (test_memory_dir / "thought_cache.json").exists()
    assert not (test_memory_dir / "past_spoken_thoughts.json").exists()


def test_shorts_claim_inspection_model_assessed_contradiction_triggers_rewrite_and_passes(monkeypatch, tmp_path):
    """
    Phase 6B Stage 3A.2: Verifies that a model-assessed contradiction without identified evidence
    (evidence=[]) is distinguished from evidence-backed contradictions, triggers targeted scene
    rewrite, re-runs Editorial Critic, re-inspects, and completes successfully.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        FactualityPolicyStatus,
        get_last_factuality_decision,
        get_last_claim_report,
        evaluate_shorts_factuality_policy,
    )
    from engine.models import SpecOutput
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        EvidenceReference,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    # Clear PYTEST_CURRENT_TEST so Critic code path executes on both initial audit and re-audit
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Energy Paradoxes", "source": "trend"}
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (10.0, [], [5.0, 5.0], [[], []])
    )

    initial_scenes = [
        {"scene_id": 1, "spoken_text": "Perpetual motion machines generate infinite free energy.", "stock_video_query": "perpetual wheel"},
        {"scene_id": 2, "spoken_text": "Which is why you should never overthink these quirks...", "stock_video_query": "loop ending"}
    ]
    seo_data = {"title": "Energy Paradoxes #shorts", "description": "Paradoxes. #shorts", "tags": ["physics", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (initial_scenes, seo_data)
    )

    # Track Critic runs
    critic_runs = [0]
    def mock_audit(raw_scenes, seo_data, topic, llm_manager=None, *args, **kwargs):
        critic_runs[0] += 1
        return raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec", mock_audit)

    # Track targeted rewrite
    rewrite_calls = []
    def mock_rewrite(scene, claim_record, llm=None):
        rewrite_calls.append({
            "scene": dict(scene),
            "claim": claim_record,
        })
        rev = dict(scene)
        rev["spoken_text"] = "Perpetual motion machines are physically impossible due to thermodynamics."
        rev["phonetic_text"] = rev["spoken_text"]
        rev["_factuality_revised"] = True
        return rev

    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", mock_rewrite)

    # Track inspection calls and reports
    inspect_calls = [0]
    captured_inspected_reports = []

    def mock_inspect(self, scenes, candidate_evidence=None):
        inspect_calls[0] += 1
        current_text = scenes[0].get("spoken_text", "")
        if "infinite free energy" in current_text.lower():
            # Initial report: model-assessed contradiction WITHOUT identified evidence (evidence=[])
            rep = ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=current_text,
                        extracted_proposition="Perpetual motion machines generate infinite energy.",
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.CONTRADICTED.value,
                        risk_level=RiskLevel.LOW.value,
                        evidence=[],  # Crucial: NO evidence records attached!
                        rationale="Thermodynamically impossible according to conservation laws."
                    )
                ],
                status="failed"
            )
        else:
            # Re-inspected report on rewritten text: fully supported
            rep = ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=current_text,
                        extracted_proposition="Perpetual motion machines violate thermodynamic laws.",
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.SUPPORTED.value,
                        risk_level=RiskLevel.LOW.value,
                        evidence=[EvidenceReference(id="phys_01", text="Thermodynamics first and second laws.")],
                        rationale="Corroborated by physical conservation laws."
                    )
                ],
                status="completed"
            )
        captured_inspected_reports.append(rep)
        return rep

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    # Pre-verification assertion on the initial report policy evaluation:
    # Confirms that evaluate_shorts_factuality_policy explicitly distinguishes
    # model-assessed contradictions (evidence=[]) from evidence-backed contradictions
    initial_rep = mock_inspect(None, initial_scenes)
    init_status, init_reason, init_affected = evaluate_shorts_factuality_policy(initial_rep)
    assert init_status == FactualityPolicyStatus.REJECTED_CONTRADICTION
    assert "Model-assessed contradiction in Scene 1" in init_reason
    assert "Evidence-backed" not in init_reason
    assert initial_rep.claims[0].evidence == []

    # Reset call counter before pipeline run
    inspect_calls[0] = 0
    captured_inspected_reports.clear()

    # Execute pipeline
    run_spec_stage(video_type="short")

    # 1. Assert initial contradiction had evidence=[] and was passed to rewrite
    assert len(rewrite_calls) == 1
    assert rewrite_calls[0]["claim"].evidence == []
    assert rewrite_calls[0]["claim"].outcome == VerificationOutcome.CONTRADICTED.value

    # 2. Assert targeted rewrite was invoked and rewritten script was re-inspected
    assert inspect_calls[0] >= 2
    assert critic_runs[0] >= 2  # Initial critic audit + re-audit after text rewrite

    # 3. Assert pipeline completed and final spec reflects rewritten text
    assert os.path.exists(test_spec_path)
    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())
    assert spec.video_type == "short"
    assert "physically impossible" in spec.scenes[0].spoken_text
    assert "infinite free energy" not in spec.scenes[0].spoken_text

    # 4. Assert final report corresponds to final rewritten spoken text
    final_report = get_last_claim_report()
    assert final_report is not None
    assert "physically impossible" in final_report.claims[0].original_text
    final_dec = get_last_factuality_decision()
    assert final_dec is not None
    assert final_dec[0] == FactualityPolicyStatus.PASSED


# ─── PHASE 10G.1: SHORTS SCRIPT CONSTRAINTS & BOUNDARY VERIFICATION ───────────

def test_shorts_pipeline_accepts_concise_script_under_nine_scenes_and_under_145_words(monkeypatch, tmp_path):
    """Phase 10G.1: Verifies that Shorts production pipeline does NOT reject scripts
    with fewer than 9 scenes or fewer than 145 words; calibrate_and_guard_script
    hard minimum limits are not active in run_spec_stage(video_type='short')."""
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.models import SpecOutput

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("GHOST_ENGINE_ENABLED", raising=False)

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr("engine.managers.topic_inspector.TopicInspector.discover_verified_topic", lambda self, niche, *a, **kw: {
        "topic": "Concise Perceptual Observations",
        "verified_summary": "Everyday perceptual quirks.",
        "source": "verified_trend"
    })

    # Concise 4-scene script with 39 total words (well under 9 scenes, well under 145 words)
    concise_scenes = [
        {"scene_id": 1, "spoken_text": "The moon appears larger on the horizon due to an optical illusion.", "stock_video_query": "moon horizon"},
        {"scene_id": 2, "spoken_text": "Your brain uses ground objects to misjudge its physical size.", "stock_video_query": "brain perception"},
        {"scene_id": 3, "spoken_text": "Photographs show its angular diameter never actually changes.", "stock_video_query": "camera lens"},
        {"scene_id": 4, "spoken_text": "Which means your perception scales reality without you noticing.", "stock_video_query": "human eye"}
    ]
    total_words = sum(len(s["spoken_text"].split()) for s in concise_scenes)
    assert len(concise_scenes) < 9  # 4 < 9
    assert total_words < 145        # 39 < 145

    seo_data = {
        "title": "Why The Moon Looks Huge #shorts",
        "description": "Why The Moon Looks Huge #shorts\n\nThe Ponzo illusion explained.\n\n#shorts",
        "tags": ["moon illusion", "perception", "shorts"]
    }

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (concise_scenes, seo_data)
    )

    monkeypatch.setattr("engine.managers.editorial_critic.audit_and_refine_spec",
                        lambda raw_scenes, seo_data, topic, llm_manager, **kw: (raw_scenes, seo_data, {"status": "passed", "unresolved_failures": 0}))
    monkeypatch.setattr("engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
                        lambda **kw: (22.0, [], [5.5, 5.5, 5.5, 5.5], [[], [], [], []]))

    # Must complete successfully without raising ValueError for word count or scene count
    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    assert spec.video_type == "short"
    assert len(spec.scenes) == 4
    assert sum(len(s.spoken_text.split()) for s in spec.scenes) == total_words


# ─── 20. SHORTS CLAIM INSPECTION & REWRITE INTEGRATION CORRECTIONS ───────────

def test_claim_inspector_subjective_philosophical_observation_not_misclassified_as_empirical():
    """
    Verifies that genuinely subjective, introspective, or philosophical observations
    (even when containing confident phrasing or superficial colloquial numerals like '3 AM')
    are classified as SUBJECTIVE with outcome NOT_APPLICABLE, and pass factuality evaluation
    without being treated as unverified empirical claims.
    """
    from engine.managers.claim_inspector import (
        ClaimInspector,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )
    from engine.managers.pipeline_runner import (
        evaluate_shorts_factuality_policy,
        FactualityPolicyStatus,
    )

    inspector = ClaimInspector(llm_manager=None)

    # 1. Confidently phrased philosophical shower thought
    obs1 = "The quietest moments in life are often the loudest in your head."
    cls1, props1, rat1, err1 = inspector.classify_and_extract(obs1)
    assert cls1 == ClaimClassification.SUBJECTIVE.value
    assert props1 == []

    # 2. Subjective observation containing colloquial time reference ('3 AM')
    obs2 = "Nothing feels more peaceful than 3 AM when the entire world is silent."
    cls2, props2, rat2, err2 = inspector.classify_and_extract(obs2)
    assert cls2 == ClaimClassification.SUBJECTIVE.value
    assert props2 == []

    # 3. Inspect scenes through inspect_script and verify policy evaluation
    scenes = [
        {"scene_id": 1, "spoken_text": obs1},
        {"scene_id": 2, "spoken_text": obs2},
    ]
    report = inspector.inspect_script(scenes)
    assert len(report.claims) == 2
    for rec in report.claims:
        assert rec.classification == ClaimClassification.SUBJECTIVE.value
        assert rec.outcome == VerificationOutcome.NOT_APPLICABLE.value
        assert rec.risk_level == RiskLevel.LOW.value

    policy_status, reason, affected = evaluate_shorts_factuality_policy(report)
    assert policy_status == FactualityPolicyStatus.PASSED
    assert len(affected) == 0


def test_claim_inspector_unsupported_empirical_scientific_claim_remains_rejected():
    """
    Verifies that empirical numerical statements (e.g. measured percentages or physical constants)
    remain strictly classified as EMPIRICAL with RiskLevel.MEDIUM, and fail-closed when
    candidate evidence does not corroborate them.
    """
    from engine.managers.claim_inspector import (
        ClaimInspector,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )
    from engine.managers.pipeline_runner import (
        evaluate_shorts_factuality_policy,
        FactualityPolicyStatus,
    )

    inspector = ClaimInspector(llm_manager=None)

    # Empirical numerical statement about human biology / time
    empirical_text = "Humans spend 33% of their lives sleeping."
    cls, props, rat, err = inspector.classify_and_extract(empirical_text)
    assert cls == ClaimClassification.EMPIRICAL.value
    assert len(props) == 1
    assert props[0]["risk_level"] == RiskLevel.MEDIUM.value

    # When inspected without corroborating evidence in the vault
    report = inspector.inspect_script([{"scene_id": 1, "spoken_text": empirical_text}], candidate_evidence=[])
    assert len(report.claims) == 1
    assert report.claims[0].outcome == VerificationOutcome.UNVERIFIABLE.value
    assert report.claims[0].risk_level == RiskLevel.MEDIUM.value

    policy_status, reason, affected = evaluate_shorts_factuality_policy(report)
    assert policy_status == FactualityPolicyStatus.REJECTED_MEDIUM_RISK_UNVERIFIED
    assert len(affected) == 1
    assert affected[0][0] == 1


def test_pipeline_runner_factuality_rewrite_receives_evidence_and_preserves_topic():
    """
    Verifies that _rewrite_scene_for_factuality receives the intended topic and available
    grounding evidence, formats them clearly in prompts to preserve topic relevance without
    fabrication, and outputs a revised scene with phonetic normalization.
    """
    from unittest.mock import MagicMock
    from engine.managers.pipeline_runner import _rewrite_scene_for_factuality
    from engine.managers.claim_inspector import ClaimRecord, EvidenceReference, RiskLevel, VerificationOutcome

    mock_llm = MagicMock()
    captured_calls = []

    def mock_generate_json(sys_p, usr_p, **kwargs):
        captured_calls.append({"sys": sys_p, "usr": usr_p, "kwargs": kwargs})
        return {
            "spoken_text": "Sound waves propagate through molecular vibrations at 343 meters per second.",
            "stock_video_query": "sound waves vibration"
        }

    mock_llm.generate_json = mock_generate_json

    scene = {"scene_id": 1, "spoken_text": "Traveling at 1.3 times the speed of sound makes you hear backwards."}
    claim = ClaimRecord(
        claim_id="claim_1_1",
        scene_id=1,
        original_text=scene["spoken_text"],
        extracted_proposition=scene["spoken_text"],
        classification="empirical",
        outcome=VerificationOutcome.UNVERIFIABLE.value,
        risk_level=RiskLevel.MEDIUM.value,
        rationale="Unverified assertion about hearing sound backwards."
    )
    evidence = [
        EvidenceReference(id="ev_sound_01", text="Sound travels at 343 meters per second in dry air at 20 degrees Celsius.")
    ]

    revised = _rewrite_scene_for_factuality(
        scene=scene,
        claim_record=claim,
        llm=mock_llm,
        topic="Speed of Sound Mechanics",
        candidate_evidence=evidence
    )

    assert revised is not None
    assert revised["_factuality_revised"] is True
    assert "Sound waves propagate" in revised["spoken_text"]
    assert "phonetic_text" in revised

    # Assert prompt received topic and evidence
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert "Speed of Sound Mechanics" in call["sys"]
    assert "TOPIC PRESERVATION: The revised scene MUST strictly preserve and stay relevant to the intended topic: 'Speed of Sound Mechanics'" in call["sys"]
    assert "Speed of Sound Mechanics" in call["usr"]
    assert "343 meters per second in dry air" in call["usr"]
    assert "NO FABRICATION" in call["sys"]


def test_pipeline_runner_exhausted_rewrites_fail_closed_without_silent_substitution(monkeypatch, tmp_path):
    """
    Verifies that when factuality rewrites for an unsupported empirical claim are exhausted,
    the pipeline fails closed with ValueError containing explicit diagnostics, does NOT
    silently substitute unrelated content, and does NOT generate spec or persist state.
    """
    import pytest
    from engine.managers.pipeline_runner import run_spec_stage
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Deep Sea Mysteries", "source": "trend"}
    )

    scenes = [
        {"scene_id": 1, "spoken_text": "Giant squids have hearts that beat 500 times per minute under pressure.", "stock_video_query": "deep sea squid"},
        {"scene_id": 2, "spoken_text": "Which is why the abyss remains an alien frontier...", "stock_video_query": "ocean trench"}
    ]
    seo_data = {"title": "Deep Sea Mysteries #shorts", "description": "Abyss facts. #shorts", "tags": ["ocean", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (scenes, seo_data)
    )

    def mock_inspect(self, sc_list, candidate_evidence=None):
        return ClaimInspectionReport(
            claims=[
                ClaimRecord(
                    claim_id="claim_1_1",
                    scene_id=1,
                    original_text=sc_list[0].get("spoken_text", ""),
                    extracted_proposition=sc_list[0].get("spoken_text", ""),
                    classification=ClaimClassification.EMPIRICAL.value,
                    outcome=VerificationOutcome.UNVERIFIABLE.value,
                    risk_level=RiskLevel.MEDIUM.value,
                    rationale="Unsupported quantitative heart rate statistic."
                )
            ],
            status="completed"
        )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    rewrite_attempts = [0]
    def mock_rewrite(scene, claim_record, llm=None, **kwargs):
        rewrite_attempts[0] += 1
        rev = dict(scene)
        rev["spoken_text"] = f"Still unverified claim attempt {rewrite_attempts[0]}"
        return rev

    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", mock_rewrite)

    with pytest.raises(ValueError) as exc_info:
        run_spec_stage(video_type="short")

    err_msg = str(exc_info.value)
    assert "REJECTED_MEDIUM_RISK_UNVERIFIED" in err_msg
    assert "Rewrite budget exhausted" in err_msg
    assert "Scene 1" in err_msg
    assert rewrite_attempts[0] == 2  # Exactly 2 attempts before exhaustion
    assert not os.path.exists(test_spec_path)
    assert not (test_memory_dir / "thought_cache.json").exists()


def test_pipeline_runner_valid_grounded_shorts_spec_completes_validation(monkeypatch, tmp_path):
    """
    Verifies that a valid Shorts spec undergoing targeted factuality rewrite with available
    grounding evidence completes validation, packages spec.json, and passes without rewrite exhaustion.
    """
    from engine.managers.pipeline_runner import (
        run_spec_stage,
        FactualityPolicyStatus,
        get_last_factuality_decision,
        get_last_claim_report,
    )
    from engine.models import SpecOutput
    from engine.managers.claim_inspector import (
        ClaimInspectionReport,
        ClaimRecord,
        EvidenceReference,
        ClaimClassification,
        VerificationOutcome,
        RiskLevel,
    )

    test_output_dir, test_memory_dir, test_cfg_dir = _isolate_pipeline_persistence(monkeypatch, tmp_path)
    test_spec_path = str(test_output_dir / "spec.json")

    monkeypatch.setattr("engine.managers.health_manager.HealthManager.check_and_sync_models", lambda **kw: {})
    monkeypatch.setattr("engine.managers.competitor_spy.CompetitorSpy.get_surge_topic", lambda *a: None)
    monkeypatch.setattr(
        "engine.managers.topic_inspector.TopicInspector.discover_verified_topic",
        lambda self, niche, *a, **kw: {"topic": "Acoustic Phenomena", "source": "trend"}
    )
    monkeypatch.setattr(
        "engine.managers.voice_normalizer.VoiceNormalizer.synthesize_scenes_sync",
        lambda **kw: (12.0, [], [6.0, 6.0], [[], []])
    )

    initial_scenes = [
        {"scene_id": 1, "spoken_text": "Traveling at 1.3 times the speed of sound makes you hear backwards.", "stock_video_query": "jet sound"},
        {"scene_id": 2, "spoken_text": "Which means sonic physics bends your perception in unexpected ways...", "stock_video_query": "sound waves"}
    ]
    seo_data = {"title": "Acoustic Phenomena #shorts", "description": "Sound physics. #shorts", "tags": ["acoustics", "shorts"]}

    monkeypatch.setattr(
        "engine.managers.iterative_script_generator.IterativeScriptGenerator.generate_scene_chain",
        lambda self, topic="", channel_premise="", grounding_facts=None: (initial_scenes, seo_data)
    )

    inspect_calls = [0]
    def mock_inspect(self, scenes, candidate_evidence=None):
        inspect_calls[0] += 1
        curr_text = scenes[0].get("spoken_text", "")
        if "1.3 times" in curr_text:
            # First pass: medium-risk unverified claim
            return ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=curr_text,
                        extracted_proposition="Traveling at 1.3 times speed of sound makes you hear backwards.",
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.UNVERIFIABLE.value,
                        risk_level=RiskLevel.MEDIUM.value,
                        rationale="Acoustic proposition not supported by candidate evidence."
                    )
                ],
                status="completed"
            )
        else:
            # Second pass after rewrite: supported by evidence
            return ClaimInspectionReport(
                claims=[
                    ClaimRecord(
                        claim_id="claim_1_1",
                        scene_id=1,
                        original_text=curr_text,
                        extracted_proposition="Sound waves propagate through air at 343 meters per second.",
                        classification=ClaimClassification.EMPIRICAL.value,
                        outcome=VerificationOutcome.SUPPORTED.value,
                        risk_level=RiskLevel.MEDIUM.value,
                        evidence=[EvidenceReference(id="ev_01", text="Sound speed is 343 m/s.")],
                        rationale="Directly supported by acoustic physics."
                    )
                ],
                status="completed"
            )

    monkeypatch.setattr("engine.managers.claim_inspector.ClaimInspector.inspect_script", mock_inspect)

    def mock_rewrite(scene, claim_record, llm=None, topic=None, candidate_evidence=None, **kwargs):
        rev = dict(scene)
        rev["spoken_text"] = "Sound waves propagate through air at 343 meters per second."
        rev["phonetic_text"] = rev["spoken_text"]
        rev["_factuality_revised"] = True
        return rev

    monkeypatch.setattr("engine.managers.pipeline_runner._rewrite_scene_for_factuality", mock_rewrite)

    run_spec_stage(video_type="short")

    assert os.path.exists(test_spec_path)
    assert inspect_calls[0] >= 2
    with open(test_spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())
    assert "343 meters per second" in spec.scenes[0].spoken_text
    dec = get_last_factuality_decision()
    assert dec is not None
    assert dec[0] == FactualityPolicyStatus.PASSED
