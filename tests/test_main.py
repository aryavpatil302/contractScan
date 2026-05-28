"""Integration tests for main.py FastAPI endpoints."""
import json
import pytest
import httpx
import respx
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from tests.fixtures import VALID_SCAN_RESPONSE, SAMPLE_CONTRACT, make_groq_mock, MIN_VALID_TEXT

# TestClient wraps the async app synchronously — no pytest-asyncio needed here
import main as main_module
client = TestClient(main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────
# /health
# ─────────────────────────────────────────

class TestHealth:
    def test_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_returns_ok_status(self):
        r = client.get("/health")
        assert r.json() == {"status": "ok"}


# ─────────────────────────────────────────
# /scan — request validation
# ─────────────────────────────────────────

class TestScanValidation:
    def test_empty_body_returns_400(self):
        r = client.post("/scan", json={})
        assert r.status_code == 400
        assert "text" in r.json()["detail"].lower() or "url" in r.json()["detail"].lower()

    def test_null_text_and_url_returns_400(self):
        r = client.post("/scan", json={"text": None, "url": None})
        assert r.status_code == 400

    def test_text_too_short_returns_400(self):
        r = client.post("/scan", json={"text": "hi"})
        assert r.status_code == 400
        assert "short" in r.json()["detail"].lower()

    def test_text_exactly_99_chars_returns_400(self):
        r = client.post("/scan", json={"text": "A" * 99})
        assert r.status_code == 400

    def test_text_exactly_100_chars_passes_validation(self):
        with patch("main.scan", return_value=json.loads(VALID_SCAN_RESPONSE)):
            r = client.post("/scan", json={"text": "A" * 100})
        assert r.status_code == 200

    def test_whitespace_only_text_returns_400(self):
        r = client.post("/scan", json={"text": "   " * 50})
        assert r.status_code == 400

    def test_url_with_file_scheme_returns_400(self):
        r = client.post("/scan", json={"url": "file:///etc/passwd"})
        assert r.status_code == 400
        assert "http" in r.json()["detail"].lower()

    def test_url_with_ftp_scheme_returns_400(self):
        r = client.post("/scan", json={"url": "ftp://example.com/file"})
        assert r.status_code == 400

    def test_malformed_json_body_returns_422(self):
        r = client.post("/scan", content=b"not-json", headers={"Content-Type": "application/json"})
        assert r.status_code == 422


# ─────────────────────────────────────────
# /scan — text path success
# ─────────────────────────────────────────

class TestScanTextSuccess:
    def test_returns_200(self):
        with patch("main.scan", return_value=json.loads(VALID_SCAN_RESPONSE)):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert r.status_code == 200

    def test_response_has_grade(self):
        with patch("main.scan", return_value=json.loads(VALID_SCAN_RESPONSE)):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert r.json()["overall_grade"] == "B"

    def test_response_has_nine_findings(self):
        with patch("main.scan", return_value=json.loads(VALID_SCAN_RESPONSE)):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert len(r.json()["findings"]) == 9

    def test_response_has_vendor_name(self):
        with patch("main.scan", return_value=json.loads(VALID_SCAN_RESPONSE)):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert r.json()["vendor_name"] == "Acme SaaS Inc."

    def test_focus_passed_through_to_scan(self):
        captured = {}
        def capturing_scan(text, focus=None):
            captured["focus"] = focus
            return json.loads(VALID_SCAN_RESPONSE)

        with patch("main.scan", side_effect=capturing_scan):
            client.post("/scan", json={"text": SAMPLE_CONTRACT, "focus": "data residency"})

        assert captured["focus"] == "data residency"

    def test_null_focus_passed_as_none(self):
        captured = {}
        def capturing_scan(text, focus=None):
            captured["focus"] = focus
            return json.loads(VALID_SCAN_RESPONSE)

        with patch("main.scan", side_effect=capturing_scan):
            client.post("/scan", json={"text": SAMPLE_CONTRACT, "focus": None})

        assert captured["focus"] is None


# ─────────────────────────────────────────
# /scan — URL path
# ─────────────────────────────────────────

class TestScanUrlPath:
    @respx.mock
    def test_url_scan_returns_200(self):
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text="<html><body><p>" + "Contract text. " * 50 + "</p></body></html>")
        )
        with patch("main.scan", return_value=json.loads(VALID_SCAN_RESPONSE)):
            r = client.post("/scan", json={"url": "https://example.com/terms"})
        assert r.status_code == 200

    @respx.mock
    def test_url_404_returns_422(self):
        respx.get("https://example.com/missing").mock(
            return_value=httpx.Response(404)
        )
        r = client.post("/scan", json={"url": "https://example.com/missing"})
        assert r.status_code == 422
        assert "fetch" in r.json()["detail"].lower()

    @respx.mock
    def test_js_only_page_returns_422(self):
        """Pages that JS-render return too little text."""
        respx.get("https://spa.example.com/terms").mock(
            return_value=httpx.Response(200, text="<html><body><script>app()</script></body></html>")
        )
        r = client.post("/scan", json={"url": "https://spa.example.com/terms"})
        assert r.status_code == 422
        assert "javascript" in r.json()["detail"].lower() or "too little" in r.json()["detail"].lower()

    @respx.mock
    def test_url_takes_precedence_over_text(self):
        """When both text and url provided, url is used."""
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text="<html><body><p>" + "Contract text. " * 50 + "</p></body></html>")
        )
        captured = {}
        def capturing_scan(text, focus=None):
            captured["text"] = text
            return json.loads(VALID_SCAN_RESPONSE)

        with patch("main.scan", side_effect=capturing_scan):
            client.post("/scan", json={
                "url": "https://example.com/terms",
                "text": SAMPLE_CONTRACT,
            })

        # Text should come from fetched URL (shorter), not SAMPLE_CONTRACT
        assert captured.get("text") is not None
        assert captured["text"] != SAMPLE_CONTRACT


# ─────────────────────────────────────────
# /scan — error propagation
# ─────────────────────────────────────────

class TestScanErrorPropagation:
    def test_scan_runtime_error_returns_502(self):
        with patch("main.scan", side_effect=RuntimeError("AI response could not be parsed")):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert r.status_code == 502
        assert "parsed" in r.json()["detail"].lower()

    def test_scan_too_long_returns_502(self):
        with patch("main.scan", side_effect=RuntimeError("Contract text is too long for analysis")):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert r.status_code == 502
        assert "long" in r.json()["detail"].lower()

    def test_missing_api_key_returns_503(self):
        with patch("main.scan", side_effect=EnvironmentError("GROQ_API_KEY is not set")):
            r = client.post("/scan", json={"text": SAMPLE_CONTRACT})
        assert r.status_code == 503


# ─────────────────────────────────────────
# Static / frontend serving
# ─────────────────────────────────────────

class TestStaticServing:
    def test_root_serves_html(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_index_html_contains_app_title(self):
        r = client.get("/index.html")
        assert r.status_code == 200
        assert b"ContractScan" in r.content

    def test_nonexistent_static_file_returns_404(self):
        r = client.get("/does-not-exist.js")
        assert r.status_code == 404
