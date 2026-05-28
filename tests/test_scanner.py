"""Unit tests for scanner.py — LLM prompt, JSON extraction, retry logic."""
import json
import time
import pytest
from unittest.mock import MagicMock, patch, call

import groq
import httpx

from scanner import _extract_json, scan, _MAX_TEXT_CHARS, CATEGORIES
from tests.fixtures import VALID_SCAN_RESPONSE, NINE_FINDINGS, make_groq_mock, SAMPLE_CONTRACT


# ─────────────────────────────────────────
# _extract_json
# ─────────────────────────────────────────

class TestExtractJson:
    def test_direct_parse(self):
        raw = '{"overall_grade": "B", "findings": []}'
        assert _extract_json(raw) == {"overall_grade": "B", "findings": []}

    def test_strips_markdown_fences(self):
        raw = '```json\n{"overall_grade": "A"}\n```'
        assert _extract_json(raw) == {"overall_grade": "A"}

    def test_strips_markdown_fences_no_lang(self):
        raw = '```\n{"overall_grade": "C"}\n```'
        assert _extract_json(raw) == {"overall_grade": "C"}

    def test_extracts_from_preamble(self):
        raw = 'Here is the analysis you requested:\n\n{"overall_grade": "D", "score": 80}'
        result = _extract_json(raw)
        assert result["overall_grade"] == "D"

    def test_extracts_from_trailing_text(self):
        raw = '{"overall_grade": "F"}\n\nLet me know if you need anything else.'
        assert _extract_json(raw)["overall_grade"] == "F"

    def test_brace_counting_handles_nested(self):
        obj = {"outer": {"inner": "value"}, "grade": "B"}
        raw = f"Response: {json.dumps(obj)} end."
        assert _extract_json(raw) == obj

    def test_full_valid_response(self):
        result = _extract_json(VALID_SCAN_RESPONSE)
        assert result["vendor_name"] == "Acme SaaS Inc."
        assert len(result["findings"]) == 9

    def test_raises_on_completely_invalid(self):
        with pytest.raises(ValueError, match="Could not extract JSON"):
            _extract_json("This is not JSON at all, no braces anywhere")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError):
            _extract_json("")

    def test_raises_on_array_only(self):
        # Top-level array — our extractor only finds objects
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _extract_json('["just", "an", "array"]')


# ─────────────────────────────────────────
# scan() — output shape
# ─────────────────────────────────────────

class TestScanOutputShape:
    def test_returns_all_top_level_keys(self):
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        for key in ("vendor_name", "overall_grade", "overall_risk_score",
                    "executive_summary", "findings", "key_dates", "favorable_terms"):
            assert key in result, f"Missing key: {key}"

    def test_grade_is_valid(self):
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        assert result["overall_grade"] in ("A", "B", "C", "D", "F")

    def test_risk_score_is_integer(self):
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        assert isinstance(result["overall_risk_score"], int)

    def test_findings_is_list(self):
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        assert isinstance(result["findings"], list)

    def test_nine_findings_returned(self):
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        assert len(result["findings"]) == 9

    def test_finding_fields_present(self):
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        for f in result["findings"]:
            for field in ("category", "display_name", "severity", "headline",
                          "clause_excerpt", "plain_english", "negotiation_tip"):
                assert field in f, f"Finding missing field: {field}"

    def test_severity_values_valid(self):
        valid = {"critical", "high", "medium", "low", "ok", "not_found"}
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        for f in result["findings"]:
            assert f["severity"] in valid, f"Invalid severity: {f['severity']}"

    def test_category_values_valid(self):
        valid = {cat for cat, _ in CATEGORIES}
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(SAMPLE_CONTRACT)
        for f in result["findings"]:
            assert f["category"] in valid, f"Unknown category: {f['category']}"


# ─────────────────────────────────────────
# scan() — input handling
# ─────────────────────────────────────────

class TestScanInputHandling:
    def test_truncates_text_over_limit(self):
        """Text longer than _MAX_TEXT_CHARS must be silently truncated."""
        captured = {}
        original_create = MagicMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content=VALID_SCAN_RESPONSE))]
        ))
        def capturing_create(*args, **kwargs):
            captured["messages"] = kwargs.get("messages") or args[0]
            return original_create(*args, **kwargs)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = capturing_create

        long_text = "x" * (_MAX_TEXT_CHARS + 10_000)
        with patch("scanner._get_client", return_value=mock_client):
            scan(long_text)

        user_msg = captured["messages"][1]["content"]
        assert len(user_msg) <= _MAX_TEXT_CHARS + 200  # prompt prefix overhead

    def test_exact_limit_text_passes(self):
        text = "A" * _MAX_TEXT_CHARS
        with patch("scanner._get_client", return_value=make_groq_mock()):
            result = scan(text)
        assert result["overall_grade"] in ("A", "B", "C", "D", "F")

    def test_focus_appended_to_user_message(self):
        captured = {}
        def capturing_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return MagicMock(choices=[MagicMock(message=MagicMock(content=VALID_SCAN_RESPONSE))])

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = capturing_create

        with patch("scanner._get_client", return_value=mock_client):
            scan(SAMPLE_CONTRACT, focus="GDPR compliance and data residency")

        user_content = captured["messages"][1]["content"]
        assert "GDPR compliance and data residency" in user_content

    def test_focus_none_not_appended(self):
        captured = {}
        def capturing_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return MagicMock(choices=[MagicMock(message=MagicMock(content=VALID_SCAN_RESPONSE))])

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = capturing_create

        with patch("scanner._get_client", return_value=mock_client):
            scan(SAMPLE_CONTRACT, focus=None)

        user_content = captured["messages"][1]["content"]
        assert "Buyer's priority focus" not in user_content

    def test_whitespace_only_focus_not_appended(self):
        captured = {}
        def capturing_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return MagicMock(choices=[MagicMock(message=MagicMock(content=VALID_SCAN_RESPONSE))])

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = capturing_create

        with patch("scanner._get_client", return_value=mock_client):
            scan(SAMPLE_CONTRACT, focus="   ")

        user_content = captured["messages"][1]["content"]
        assert "Buyer's priority focus" not in user_content


# ─────────────────────────────────────────
# scan() — normalization of partial responses
# ─────────────────────────────────────────

class TestScanNormalization:
    def test_missing_findings_defaults_to_empty_list(self):
        partial = json.dumps({"overall_grade": "C", "overall_risk_score": 60,
                              "executive_summary": "OK"})
        with patch("scanner._get_client", return_value=make_groq_mock(partial)):
            result = scan(SAMPLE_CONTRACT)
        assert result["findings"] == []

    def test_missing_key_dates_defaults_to_empty_list(self):
        partial = json.dumps({"overall_grade": "B", "findings": NINE_FINDINGS})
        with patch("scanner._get_client", return_value=make_groq_mock(partial)):
            result = scan(SAMPLE_CONTRACT)
        assert result["key_dates"] == []

    def test_missing_favorable_terms_defaults_to_empty_list(self):
        partial = json.dumps({"overall_grade": "A", "findings": NINE_FINDINGS})
        with patch("scanner._get_client", return_value=make_groq_mock(partial)):
            result = scan(SAMPLE_CONTRACT)
        assert result["favorable_terms"] == []

    def test_missing_vendor_name_defaults_to_none(self):
        partial = json.dumps({"overall_grade": "B", "overall_risk_score": 40,
                              "executive_summary": "OK", "findings": NINE_FINDINGS})
        with patch("scanner._get_client", return_value=make_groq_mock(partial)):
            result = scan(SAMPLE_CONTRACT)
        assert result["vendor_name"] is None

    def test_missing_risk_score_defaults_to_zero(self):
        partial = json.dumps({"overall_grade": "B", "executive_summary": "OK",
                              "findings": NINE_FINDINGS})
        with patch("scanner._get_client", return_value=make_groq_mock(partial)):
            result = scan(SAMPLE_CONTRACT)
        assert result["overall_risk_score"] == 0


# ─────────────────────────────────────────
# scan() — error handling and retry
# ─────────────────────────────────────────

class TestScanErrorHandling:
    def test_raises_runtime_on_unparseable_response(self):
        with patch("scanner._get_client", return_value=make_groq_mock("not json at all")):
            with pytest.raises(RuntimeError, match="could not be parsed"):
                scan(SAMPLE_CONTRACT)

    def test_retries_on_rate_limit_and_succeeds(self):
        call_count = 0
        good_response = MagicMock(
            choices=[MagicMock(message=MagicMock(content=VALID_SCAN_RESPONSE))]
        )
        mock_http = MagicMock()
        mock_http.status_code = 429
        rate_err = groq.RateLimitError(
            "Rate limited", response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/")), body=None
        )

        def flaky_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise rate_err
            return good_response

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = flaky_create

        with patch("scanner._get_client", return_value=mock_client), \
             patch("time.sleep"):
            result = scan(SAMPLE_CONTRACT)

        assert call_count == 3
        assert result["overall_grade"] == "B"

    def test_raises_after_all_retries_exhausted(self):
        mock_http = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/"))
        rate_err = groq.RateLimitError("Rate limited", response=mock_http, body=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = rate_err

        with patch("scanner._get_client", return_value=mock_client), \
             patch("time.sleep"):
            with pytest.raises(groq.RateLimitError):
                scan(SAMPLE_CONTRACT)

    def test_raises_runtime_on_413(self):
        mock_http = httpx.Response(413, request=httpx.Request("POST", "https://api.groq.com/"))
        err_413 = groq.APIStatusError("Too large", response=mock_http, body=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = err_413

        with patch("scanner._get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="too long"):
                scan(SAMPLE_CONTRACT)

    def test_other_api_errors_propagate(self):
        mock_http = httpx.Response(500, request=httpx.Request("POST", "https://api.groq.com/"))
        server_err = groq.APIStatusError("Server error", response=mock_http, body=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = server_err

        with patch("scanner._get_client", return_value=mock_client):
            with pytest.raises(groq.APIStatusError):
                scan(SAMPLE_CONTRACT)

    def test_missing_api_key_raises_environment_error(self):
        with patch("os.getenv", return_value=None), \
             patch("scanner._client", None):
            with pytest.raises(EnvironmentError, match="GROQ_API_KEY"):
                from scanner import _get_client
                _get_client()
