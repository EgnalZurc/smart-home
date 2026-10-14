"""Unit tests for input sanitization and HTML escaping (L-3 security fix)."""


class TestSanitizeString:
    """Tests for the sanitize_string helper function."""

    def test_escapes_html_tags(self):
        """HTML tags should be escaped to prevent XSS."""
        from main import sanitize_string

        result = sanitize_string("<script>alert('xss')</script>", 200)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_escapes_html_entities(self):
        """HTML entities should be escaped."""
        from main import sanitize_string

        result = sanitize_string("Test & <b>bold</b>", 200)
        assert "&amp;" in result
        assert "&lt;b&gt;" in result
        assert "&lt;/b&gt;" in result

    def test_strips_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        from main import sanitize_string

        result = sanitize_string("  hello world  ", 200)
        assert result == "hello world"

    def test_truncates_long_input(self):
        """Input exceeding max_length should be truncated."""
        from main import sanitize_string

        result = sanitize_string("a" * 300, 200)
        assert len(result) == 200

    def test_empty_string_returns_empty(self):
        """Empty string should return empty."""
        from main import sanitize_string

        result = sanitize_string("", 200)
        assert result == ""

    def test_preserves_normal_text(self):
        """Normal text without special chars should be preserved."""
        from main import sanitize_string

        result = sanitize_string("Carrito de bebé", 200)
        assert result == "Carrito de bebé"


class TestGiftCreateSanitization:
    """Tests for GiftCreate model input sanitization."""

    def test_name_is_sanitized(self):
        """Gift name should have HTML escaped."""
        from main import GiftCreate

        gift = GiftCreate(name="<script>alert('xss')</script>")
        assert "<script>" not in gift.name
        assert "&lt;script&gt;" in gift.name

    def test_description_is_sanitized(self):
        """Gift description should have HTML escaped."""
        from main import GiftCreate

        gift = GiftCreate(name="Test", description="<img src=x onerror=alert(1)>")
        assert "<img" not in gift.description
        assert "&lt;img" in gift.description

    def test_price_range_is_sanitized(self):
        """Price range should have HTML escaped."""
        from main import GiftCreate

        gift = GiftCreate(name="Test", price_range="<b>€€€</b>")
        assert "<b>" not in gift.price_range
        assert "&lt;b&gt;" in gift.price_range

    def test_url_is_not_html_escaped(self):
        """URL should NOT be HTML escaped (valid URL chars would break)."""
        from main import GiftCreate

        gift = GiftCreate(name="Test", url="https://example.com?a=1&b=2")
        # & in URLs should NOT become &amp;
        assert "?a=1&b=2" in gift.url

    def test_name_truncated_to_200(self):
        """Name should be truncated to 200 chars."""
        from main import GiftCreate

        gift = GiftCreate(name="a" * 300)
        assert len(gift.name) == 200

    def test_description_truncated_to_1000(self):
        """Description should be truncated to 1000 chars."""
        from main import GiftCreate

        gift = GiftCreate(name="Test", description="a" * 1500)
        assert len(gift.description) == 1000


class TestGiftUpdateSanitization:
    """Tests for GiftUpdate model input sanitization."""

    def test_name_is_sanitized_when_provided(self):
        """Gift name should have HTML escaped when provided."""
        from main import GiftUpdate

        update = GiftUpdate(name="<script>bad</script>")
        assert "<script>" not in update.name
        assert "&lt;script&gt;" in update.name

    def test_none_values_preserved(self):
        """None values should remain None (partial updates)."""
        from main import GiftUpdate

        update = GiftUpdate(name="Test")
        assert update.description is None
        assert update.url is None or update.url == ""  # URL may be None or empty
        assert update.price_range is None


class TestInvitationCreateSanitization:
    """Tests for InvitationCreate model input sanitization."""

    def test_name_is_sanitized(self):
        """Invitation name should have HTML escaped."""
        from main import InvitationCreate

        invitation = InvitationCreate(name="<b>Tía María</b>")
        assert "<b>" not in invitation.name
        assert "&lt;b&gt;" in invitation.name

    def test_name_truncated_to_100(self):
        """Invitation name should be truncated to 100 chars."""
        from main import InvitationCreate

        invitation = InvitationCreate(name="a" * 200)
        assert len(invitation.name) == 100


class TestApiEndpointsSanitization:
    """Integration tests for sanitization through API endpoints."""

    def test_create_gift_sanitizes_xss_attempt(self, client):
        """POST /api/baby-gifts should sanitize XSS in gift name."""
        response = client.post(
            "/api/baby-gifts",
            json={
                "name": "<script>alert('xss')</script>",
                "description": "Test gift",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "<script>" not in data["gift"]["name"]
        assert "&lt;script&gt;" in data["gift"]["name"]

    def test_update_gift_sanitizes_xss_attempt(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} should sanitize XSS in updates."""
        # Create gift first
        create_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = create_resp.json()["gift"]["id"]

        # Update with XSS attempt
        response = client.put(
            f"/api/baby-gifts/{gift_id}",
            json={"description": "<img src=x onerror=alert(1)>"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "<img" not in data["gift"]["description"]
        assert "&lt;img" in data["gift"]["description"]

    def test_create_invitation_sanitizes_name(self, client):
        """POST /api/baby-gifts/invitations should sanitize guest name."""
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "<b>Tía María</b>"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "<b>" not in data["name"]
        assert "&lt;b&gt;" in data["name"]
