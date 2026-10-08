"""Tests for serve_html — the shared static-HTML serving helper."""

import json

import pytest
from fastapi.responses import HTMLResponse

from html_serving import NO_CACHE_HEADERS, serve_html


@pytest.fixture
def static_dir(tmp_path):
    """A temp static dir with a minimal HTML page containing injection points."""
    page = (
        "<html><head><title>t</title></head>"
        "<body>"
        "<script>window.GUEST_TOKEN = null;</script>"
        "<script>window.AUTH_USER = null;</script>"
        "</body></html>"
    )
    (tmp_path / "index.html").write_text(page, encoding="utf-8")
    return tmp_path


def _body(resp: HTMLResponse) -> str:
    return resp.body.decode("utf-8")


def test_returns_htmlresponse_with_no_cache_headers(static_dir):
    resp = serve_html(static_dir, "index.html")
    assert isinstance(resp, HTMLResponse)
    assert resp.status_code == 200
    for key, value in NO_CACHE_HEADERS.items():
        assert resp.headers[key] == value


def test_injects_cache_buster_before_head_close(static_dir):
    resp = serve_html(static_dir, "index.html")
    body = _body(resp)
    assert "<!-- v:" in body
    # The buster must sit immediately before </head>.
    assert body.index("<!-- v:") < body.index("</head>")


def test_no_token_or_user_injection_by_default(static_dir):
    body = _body(serve_html(static_dir, "index.html"))
    assert "window.GUEST_TOKEN = null;" in body
    assert "window.AUTH_USER = null;" in body


def test_injects_guest_token(static_dir):
    body = _body(serve_html(static_dir, "index.html", guest_token="abc123"))
    assert f"window.GUEST_TOKEN = {json.dumps('abc123')};" in body
    assert "window.GUEST_TOKEN = null;" not in body
    # AUTH_USER untouched.
    assert "window.AUTH_USER = null;" in body


def test_injects_auth_user(static_dir):
    user = {"username": "alice"}
    body = _body(serve_html(static_dir, "index.html", auth_user=user))
    assert f"window.AUTH_USER = {json.dumps(user)};" in body
    assert "window.AUTH_USER = null;" not in body


def test_injects_both_token_and_user(static_dir):
    body = _body(
        serve_html(
            static_dir,
            "index.html",
            guest_token="tok",
            auth_user={"username": "bob"},
        )
    )
    assert 'window.GUEST_TOKEN = "tok";' in body
    assert 'window.AUTH_USER = {"username": "bob"};' in body


def test_missing_file_raises_without_not_found_html(static_dir):
    with pytest.raises(FileNotFoundError):
        serve_html(static_dir, "does-not-exist.html")


def test_missing_file_returns_404_with_not_found_html(static_dir):
    resp = serve_html(
        static_dir,
        "does-not-exist.html",
        not_found_html="<h1>404</h1>",
    )
    assert resp.status_code == 404
    assert _body(resp) == "<h1>404</h1>"


def test_present_file_ignores_not_found_html(static_dir):
    resp = serve_html(static_dir, "index.html", not_found_html="<h1>404</h1>")
    assert resp.status_code == 200
    assert "404" not in _body(resp)
