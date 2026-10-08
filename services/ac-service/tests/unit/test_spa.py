"""Unit tests for the spa module (static SPA serving helper)."""

from spa import serve_html


class TestServeHtml:
    """Tests for serve_html."""

    def test_returns_no_store_cache_headers(self, tmp_path):
        """Response must carry no-store cache headers to defeat HTML caching."""
        (tmp_path / "index.html").write_text(
            "<html><head></head><body>ok</body></html>", encoding="utf-8"
        )

        response = serve_html("index.html", static_dir=tmp_path)

        assert response.headers["Cache-Control"] == (
            "no-cache, no-store, must-revalidate, max-age=0"
        )
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"

    def test_injects_version_comment_before_head_close(self, tmp_path):
        """A cache-busting version comment must be injected before </head>."""
        (tmp_path / "index.html").write_text(
            "<html><head></head><body>ok</body></html>", encoding="utf-8"
        )

        response = serve_html("index.html", static_dir=tmp_path)
        body = response.body.decode("utf-8")

        assert "<!-- v:" in body
        assert body.index("<!-- v:") < body.index("</head>")

    def test_serves_file_content(self, tmp_path):
        """The original markup must be preserved in the response body."""
        (tmp_path / "index.html").write_text(
            "<html><head></head><body>hello world</body></html>", encoding="utf-8"
        )

        response = serve_html("index.html", static_dir=tmp_path)
        body = response.body.decode("utf-8")

        assert "hello world" in body
