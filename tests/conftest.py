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
            for k, v in kwargs.items():
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
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

        def model_dump(self):
            return self.dict()

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
