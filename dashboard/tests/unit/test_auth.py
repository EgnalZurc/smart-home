"""Unit tests for auth.py - JWT session and password verification."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest

# Patch AUTH_SECRET before importing auth module
with patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum"):
    import auth


class TestVerifyPassword:
    def test_valid_password(self):
        # Create a known apr_md5_crypt hash for "testpassword"
        from passlib.hash import apr_md5_crypt

        hashed = apr_md5_crypt.hash("testpassword")
        assert auth.verify_password("testpassword", hashed)

    def test_invalid_password(self):
        from passlib.hash import apr_md5_crypt

        hashed = apr_md5_crypt.hash("correctpassword")
        assert not auth.verify_password("wrongpassword", hashed)

    def test_malformed_hash_returns_false(self):
        assert not auth.verify_password("anypassword", "not-a-valid-hash")

    def test_empty_password_against_hash(self):
        from passlib.hash import apr_md5_crypt

        hashed = apr_md5_crypt.hash("realpassword")
        assert not auth.verify_password("", hashed)


class TestCreateToken:
    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_creates_valid_jwt(self):
        token = auth.create_token("testuser")

        # Should be decodable
        payload = jwt.decode(
            token, "test-secret-key-32-chars-minimum", algorithms=["HS256"]
        )
        assert payload["sub"] == "testuser"

    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_token_has_expiry(self):
        token = auth.create_token("testuser")
        payload = jwt.decode(
            token,
            "test-secret-key-32-chars-minimum",
            algorithms=["HS256"],
        )

        assert "exp" in payload
        assert "iat" in payload

    @patch("auth.AUTH_SECRET", "")
    def test_raises_without_secret(self):
        with pytest.raises(RuntimeError, match="AUTH_SECRET"):
            auth.create_token("testuser")


class TestDecodeToken:
    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_decodes_valid_token(self):
        token = auth.create_token("testuser")
        payload = auth.decode_token(token)

        assert payload is not None
        assert payload["sub"] == "testuser"

    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_returns_none_for_expired_token(self):
        # Create an already-expired token
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

    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_returns_none_for_invalid_signature(self):
        token = jwt.encode(
            {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "wrong-secret",
            algorithm="HS256",
        )
        result = auth.decode_token(token)
        assert result is None

    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_returns_none_for_malformed_token(self):
        result = auth.decode_token("not-a-valid-token")
        assert result is None

    @patch("auth.AUTH_SECRET", "")
    def test_returns_none_without_secret(self):
        result = auth.decode_token("any-token")
        assert result is None


class TestDecodeTokenExpiredOk:
    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_decodes_expired_token(self):
        # Create an expired token
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

    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_returns_none_for_invalid_token(self):
        result = auth.decode_token_expired_ok("garbage")
        assert result is None

    @patch("auth.AUTH_SECRET", "")
    def test_returns_none_without_secret(self):
        result = auth.decode_token_expired_ok("any-token")
        assert result is None


class TestGetTokenFromCookie:
    def test_extracts_cookie(self):
        request = MagicMock()
        request.cookies = {"smh_session": "my-jwt-token"}

        result = auth.get_token_from_cookie(request)
        assert result == "my-jwt-token"

    def test_returns_none_when_missing(self):
        request = MagicMock()
        request.cookies = {}

        result = auth.get_token_from_cookie(request)
        assert result is None


class TestGetCurrentUser:
    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_returns_username_for_valid_session(self):
        token = auth.create_token("testuser")
        request = MagicMock()
        request.cookies = {"smh_session": token}

        result = auth.get_current_user(request)
        assert result == "testuser"

    def test_returns_none_without_cookie(self):
        request = MagicMock()
        request.cookies = {}

        result = auth.get_current_user(request)
        assert result is None

    @patch("auth.AUTH_SECRET", "test-secret-key-32-chars-minimum")
    def test_returns_none_for_expired_session(self):
        # Create expired token
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


class TestSetSessionCookie:
    def test_sets_cookie_with_correct_params(self):
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
        response = MagicMock()

        auth.clear_session_cookie(response)

        response.delete_cookie.assert_called_once()
        call_kwargs = response.delete_cookie.call_args.kwargs
        assert call_kwargs["key"] == "smh_session"
        assert call_kwargs["path"] == "/"


class TestModuleConstants:
    def test_cookie_name_defined(self):
        assert auth.COOKIE_NAME == "smh_session"

    def test_algorithm_defined(self):
        assert auth.ALGORITHM == "HS256"

    def test_session_ttl_is_24_hours(self):
        assert auth.AUTH_SESSION_TTL == 86400
