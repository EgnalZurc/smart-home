"""Tests for AUTH_SECRET validation at startup."""

import importlib
import sys
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_main_module():
    """Remove main from sys.modules so it can be re-imported with new env vars."""
    # Remove main and any cached references
    modules_to_remove = [k for k in sys.modules if k == "main" or k.startswith("main.")]
    for mod in modules_to_remove:
        del sys.modules[mod]
    yield
    # Cleanup after test
    for mod in modules_to_remove:
        sys.modules.pop(mod, None)


class TestAuthSecretValidation:
    """Test AUTH_SECRET environment variable validation."""

    def test_missing_auth_secret_raises(self, fresh_main_module):
        """AUTH_SECRET missing or empty should raise RuntimeError."""
        with patch.dict("os.environ", {"AUTH_SECRET": ""}, clear=False):
            with pytest.raises(RuntimeError, match="AUTH_SECRET not configured"):
                importlib.import_module("main")

    def test_short_auth_secret_raises(self, fresh_main_module):
        """AUTH_SECRET shorter than 32 bytes should raise RuntimeError."""
        with patch.dict("os.environ", {"AUTH_SECRET": "too_short"}, clear=False):
            with pytest.raises(RuntimeError, match="AUTH_SECRET too short"):
                importlib.import_module("main")

    def test_auth_secret_exactly_32_bytes_ok(self, fresh_main_module):
        """AUTH_SECRET with exactly 32 bytes should be accepted."""
        secret_32 = "a" * 32
        with patch.dict("os.environ", {"AUTH_SECRET": secret_32}, clear=False):
            # Should not raise - import succeeds
            module = importlib.import_module("main")
            assert module.AUTH_SECRET == secret_32

    def test_auth_secret_longer_than_32_bytes_ok(self, fresh_main_module):
        """AUTH_SECRET longer than 32 bytes should be accepted."""
        secret_64 = "b" * 64
        with patch.dict("os.environ", {"AUTH_SECRET": secret_64}, clear=False):
            module = importlib.import_module("main")
            assert module.AUTH_SECRET == secret_64
