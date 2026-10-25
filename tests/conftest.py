# tests/conftest.py
"""
Pytest configuration and local environment mock stubs.
Allows test suite to run locally in environments without heavy external dependencies installed,
while seamlessly deferring to real installed packages in CI/production.
"""
import sys
from unittest.mock import MagicMock

# Graceful fallback for pydantic if running locally without pydantic installed
try:
    import pydantic
except ImportError:
    class MockBaseModel:
        def __init__(self, **kwargs):
            hints = getattr(self.__class__, "__annotations__", {})
            for k, v in kwargs.items():
                hint = hints.get(k)
                if isinstance(v, dict) and isinstance(hint, type) and issubclass(hint, MockBaseModel):
                    v = hint(**v)
                elif isinstance(v, list) and hasattr(hint, "__origin__") and hint.__origin__ is list:
                    args = getattr(hint, "__args__", ())
                    if args and isinstance(args[0], type) and issubclass(args[0], MockBaseModel):
                        v = [args[0](**item) if isinstance(item, dict) else item for item in v]
                setattr(self, k, v)
            # Fill default attributes from class annotations/attributes
            for k in dir(self.__class__):
                if not k.startswith("_") and k not in kwargs:
                    val = getattr(self.__class__, k)
                    if callable(val) and hasattr(val, "_is_mock_field"):
                        setattr(self, k, val())
                    elif not callable(val):
                        setattr(self, k, val)

        def dict(self):
            res = {}
            for k, v in self.__dict__.items():
                if not k.startswith("_"):
                    if isinstance(v, list):
                        res[k] = [item.dict() if hasattr(item, "dict") else item for item in v]
                    elif hasattr(v, "dict"):
                        res[k] = v.dict()
                    else:
                        res[k] = v
            return res

        def model_dump(self):
            return self.dict()

        def model_dump_json(self, indent=None):
            import json
            return json.dumps(self.dict(), indent=indent)

        @classmethod
        def model_validate_json(cls, json_str):
            import json
            return cls(**json.loads(json_str))

    def MockField(default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            func = lambda: default_factory()
            func._is_mock_field = True
            return func
        return default

    mock_pydantic = MagicMock()
    mock_pydantic.BaseModel = MockBaseModel
    mock_pydantic.Field = MockField
    sys.modules["pydantic"] = mock_pydantic

# Graceful fallback for requests if running locally without requests installed
try:
    import requests
except ImportError:
    mock_requests = MagicMock()
    sys.modules["requests"] = mock_requests


# Shared test-isolation mocks to protect persistent memory and config files on disk
import json
import os
import shutil
import tempfile
import pytest

# Create a unique per-session temporary directory for test isolation
_SESSION_TEMP_DIR = tempfile.TemporaryDirectory(prefix="yt_test_session_", ignore_cleanup_errors=True)
_SESSION_TEMP_PATH = _SESSION_TEMP_DIR.name

# 1. Dynamic Models Registry isolation
real_reg = os.path.abspath(os.path.join("memory", "dynamic_models_registry.json"))
temp_reg = os.path.join(_SESSION_TEMP_PATH, "dynamic_models_registry.json")
if os.path.exists(real_reg):
    try:
        shutil.copy2(real_reg, temp_reg)
    except Exception:
        pass

try:
    from engine.model_entity import DynamicQuotaTracker
    orig_tracker_init = DynamicQuotaTracker.__init__

    def patched_tracker_init(self, registry_path=None):
        if registry_path is None or (registry_path and os.path.abspath(str(registry_path)) == real_reg):
            registry_path = temp_reg
        orig_tracker_init(self, registry_path=registry_path)

    DynamicQuotaTracker.__init__ = patched_tracker_init
except Exception:
    pass

try:
    import engine.dynamic_discovery as dd
    dd.REGISTRY_PATH = temp_reg
except Exception:
    pass

# 2. Guardian Health isolation
real_health = os.path.abspath(os.path.join("memory", "guardian_health.json"))
temp_health = os.path.join(_SESSION_TEMP_PATH, "guardian_health.json")
if os.path.exists(real_health):
    try:
        shutil.copy2(real_health, temp_health)
    except Exception:
        pass

try:
    import engine.guardian as eg
    eg._HEALTH_PATH = temp_health
except Exception:
    pass

# 3. LLM Performance destination path isolation (preserving original production functions)
from pathlib import Path

real_perf = os.path.abspath(os.path.join("config", "llm_performance.json"))
temp_perf = os.path.join(_SESSION_TEMP_PATH, "llm_performance.json")
if os.path.exists(real_perf):
    try:
        shutil.copy2(real_perf, temp_perf)
    except Exception:
        pass

try:
    import engine.discovery as ed

    class _IsolatedConfigDir(type(Path())):
        def __new__(cls, real_dir, temp_dir):
            inst = super().__new__(cls, real_dir)
            inst._real_dir = Path(real_dir)
            inst._temp_dir = Path(temp_dir)
            return inst

        def __truediv__(self, other):
            if str(other) == "llm_performance.json" or str(other).endswith("llm_performance.json"):
                return self._temp_dir / Path(other).name
            return self._real_dir / other

    ed._CFG_DIR = _IsolatedConfigDir(ed._CFG_DIR, _SESSION_TEMP_PATH)
except Exception:
    pass


def pytest_sessionfinish(session, exitstatus):
    """Clean up the isolated session temporary directory after all tests complete."""
    try:
        _SESSION_TEMP_DIR.cleanup()
    except Exception:
        pass
