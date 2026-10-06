"""Unit tests for auth.py - JWT session and password verification.

NOTE: test_auth_profiles.py mocks passlib globally. These tests must
handle that by using fresh imports or checking if passlib is real.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest


def _get_real_passlib():
    """Get real passlib module, reimporting if necessary."""
    import sys

    # Check if passlib is mocked
    passlib = sys.modules.get("passlib.hash")
    if passlib and isinstance(passlib, MagicMock):
        # Force reimport of real passlib
        for key in list(sys.modules.keys()):
            if key.startswith("passlib"):
                del sys.modules[key]
        import passlib.hash

        return passlib.hash
    elif passlib:
        return passlib
    else:
        import passlib.hash

        return passlib.hash


class TestVerifyPassword:
    def test_valid_password(self):
        passlib_hash = _get_real_passlib()
        # Reimport auth to get fresh module
        import importlib
        import sys

        if "auth" in sys.modules:
            auth = importlib.reload(sys.modules["auth"])
        else:
            import auth

        hashed = passlib_hash.apr_md5_crypt.hash("testpassword")
        assert auth.verify_password("testpassword", hashed)

    def test_invalid_password(self):
        passlib_hash = _get_real_passlib()
        import importlib
        import sys

        if "auth" in sys.modules:
            auth = importlib.reload(sys.modules["auth"])
        else:
            import auth

        hashed = passlib_hash.apr_md5_crypt.hash("correctpassword")
        result = auth.verify_password("wrongpassword", hashed)
        assert result is False

    def test_malformed_hash_returns_false(self):
        _get_real_passlib()  # Ensure passlib is real
        import importlib
        import sys

        if "auth" in sys.modules:
            auth = importlib.reload(sys.modules["auth"])
        else:
            import auth

        result = auth.verify_password("anypassword", "not-a-valid-hash")
        assert result is False

    def test_empty_password_against_hash(self):
        passlib_hash = _get_real_passlib()
        import importlib
        import sys

        if "auth" in sys.modules:
            auth = importlib.reload(sys.modules["auth"])
        else:
            import auth

        hashed = passlib_hash.apr_md5_crypt.hash("realpassword")
        result = auth.verify_password("", hashed)
        assert result is False


class TestCreateToken:
    def test_creates_valid_jwt(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            token = auth.create_token("testuser")
            payload = jwt.decode(
                token, "test-secret-key-32-chars-minimum", algorithms=["HS256"]
            )
            assert payload["sub"] == "testuser"
        finally:
            auth.AUTH_SECRET = orig

    def test_token_has_expiry(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            token = auth.create_token("testuser")
            payload = jwt.decode(
                token, "test-secret-key-32-chars-minimum", algorithms=["HS256"]
            )
            assert "exp" in payload
            assert "iat" in payload
        finally:
            auth.AUTH_SECRET = orig

    def test_raises_without_secret(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = ""
        try:
            with pytest.raises(RuntimeError, match="AUTH_SECRET"):
                auth.create_token("testuser")
        finally:
            auth.AUTH_SECRET = orig


class TestDecodeToken:
    def test_decodes_valid_token(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            token = auth.create_token("testuser")
            payload = auth.decode_token(token)
            assert payload is not None
            assert payload["sub"] == "testuser"
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_for_expired_token(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            now = datetime.now(timezone.utc) - timedelta(hours=25)
            payload = {
                "sub": "testuser",
                "iat": now,
                "exp": now + timedelta(seconds=1),
            }
            token = jwt.encode(
                payload, "test-secret-key-32-chars-minimum", algorithm="HS256"
            )
            result = auth.decode_token(token)
            assert result is None
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_for_invalid_signature(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            token = jwt.encode(
                {
                    "sub": "testuser",
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                },
                "wrong-secret",
                algorithm="HS256",
            )
            result = auth.decode_token(token)
            assert result is None
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_for_malformed_token(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            result = auth.decode_token("not-a-valid-token")
            assert result is None
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_without_secret(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = ""
        try:
            result = auth.decode_token("any-token")
            assert result is None
        finally:
            auth.AUTH_SECRET = orig


class TestDecodeTokenExpiredOk:
    def test_decodes_expired_token(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            now = datetime.now(timezone.utc) - timedelta(hours=25)
            payload = {
                "sub": "testuser",
                "iat": now,
                "exp": now + timedelta(seconds=1),
            }
            token = jwt.encode(
                payload, "test-secret-key-32-chars-minimum", algorithm="HS256"
            )
            result = auth.decode_token_expired_ok(token)
            assert result is not None
            assert result["sub"] == "testuser"
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_for_invalid_token(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            result = auth.decode_token_expired_ok("garbage")
            assert result is None
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_without_secret(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = ""
        try:
            result = auth.decode_token_expired_ok("any-token")
            assert result is None
        finally:
            auth.AUTH_SECRET = orig


class TestGetTokenFromCookie:
    def test_extracts_cookie(self):
        import auth

        request = MagicMock()
        request.cookies = {"smh_session": "my-jwt-token"}
        result = auth.get_token_from_cookie(request)
        assert result == "my-jwt-token"

    def test_returns_none_when_missing(self):
        import auth

        request = MagicMock()
        request.cookies = {}
        result = auth.get_token_from_cookie(request)
        assert result is None


class TestGetCurrentUser:
    def test_returns_username_for_valid_session(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            token = auth.create_token("testuser")
            request = MagicMock()
            request.cookies = {"smh_session": token}
            result = auth.get_current_user(request)
            assert result == "testuser"
        finally:
            auth.AUTH_SECRET = orig

    def test_returns_none_without_cookie(self):
        import auth

        request = MagicMock()
        request.cookies = {}
        result = auth.get_current_user(request)
        assert result is None

    def test_returns_none_for_expired_session(self):
        import auth

        orig = auth.AUTH_SECRET
        auth.AUTH_SECRET = "test-secret-key-32-chars-minimum"
        try:
            now = datetime.now(timezone.utc) - timedelta(hours=25)
            payload = {
                "sub": "testuser",
                "iat": now,
                "exp": now + timedelta(seconds=1),
            }
            token = jwt.encode(
                payload, "test-secret-key-32-chars-minimum", algorithm="HS256"
            )
            request = MagicMock()
            request.cookies = {"smh_session": token}
            result = auth.get_current_user(request)
            assert result is None
        finally:
            auth.AUTH_SECRET = orig


class TestSetSessionCookie:
    def test_sets_cookie_with_correct_params(self):
        import auth

        response = MagicMock()
        auth.set_session_cookie(response, "test-token")
        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args.kwargs
        assert call_kwargs["key"] == "smh_session"
        assert call_kwargs["value"] == "test-token"
        assert call_kwargs["httponly"] is True
        assert call_kwargs["secure"] is True
        assert call_kwargs["samesite"] == "strict"
        assert call_kwargs["path"] == "/"


class TestClearSessionCookie:
    def test_deletes_cookie(self):
        import auth

        response = MagicMock()
        auth.clear_session_cookie(response)
        response.delete_cookie.assert_called_once()
        call_kwargs = response.delete_cookie.call_args.kwargs
        assert call_kwargs["key"] == "smh_session"
        assert call_kwargs["path"] == "/"


class TestModuleConstants:
    def test_cookie_name_defined(self):
        import auth

        assert auth.COOKIE_NAME == "smh_session"

    def test_algorithm_defined(self):
        import auth

        assert auth.ALGORITHM == "HS256"

    def test_session_ttl_is_24_hours(self):
        import auth

        assert auth.AUTH_SESSION_TTL == 86400
