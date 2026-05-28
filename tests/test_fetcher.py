"""Unit tests for fetcher.py — URL fetching and HTML-to-text extraction."""
import pytest
import httpx
import respx

from fetcher import fetch_url, MAX_CHARS

SIMPLE_HTML = """
<html>
<head><title>Test</title></head>
<body>
  <nav>Navigation menu items</nav>
  <header>Site header content</header>
  <main>
    <h1>Terms of Service</h1>
    <p>This agreement governs your use of the service.</p>
    <p>By using the service you accept these terms.</p>
  </main>
  <script>var tracking = true;</script>
  <style>body { color: red; }</style>
  <footer>Footer content here</footer>
</body>
</html>
"""


@pytest.mark.asyncio
class TestFetchUrl:

    @respx.mock
    async def test_returns_text_content(self):
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        result = await fetch_url("https://example.com/terms")
        assert "Terms of Service" in result
        assert "This agreement governs" in result

    @respx.mock
    async def test_strips_script_tags(self):
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        result = await fetch_url("https://example.com/terms")
        assert "var tracking" not in result

    @respx.mock
    async def test_strips_style_tags(self):
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        result = await fetch_url("https://example.com/terms")
        assert "color: red" not in result

    @respx.mock
    async def test_strips_nav_and_footer(self):
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        result = await fetch_url("https://example.com/terms")
        assert "Navigation menu items" not in result
        assert "Footer content here" not in result

    @respx.mock
    async def test_strips_header_tag(self):
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        result = await fetch_url("https://example.com/terms")
        assert "Site header content" not in result

    @respx.mock
    async def test_collapses_blank_lines(self):
        html = "<html><body><p>Line one</p>\n\n\n\n<p>Line two</p></body></html>"
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=html)
        )
        result = await fetch_url("https://example.com/terms")
        # No consecutive blank lines in output
        assert "\n\n\n" not in result

    @respx.mock
    async def test_truncates_at_max_chars(self):
        long_text = "word " * 20_000  # ~100k chars
        html = f"<html><body><p>{long_text}</p></body></html>"
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=html)
        )
        result = await fetch_url("https://example.com/terms")
        assert len(result) <= MAX_CHARS

    @respx.mock
    async def test_short_page_returns_short_text(self):
        html = "<html><body><p>Short.</p></body></html>"
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=html)
        )
        result = await fetch_url("https://example.com/terms")
        assert len(result) < MAX_CHARS
        assert "Short." in result

    @respx.mock
    async def test_raises_on_404(self):
        respx.get("https://example.com/missing").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_url("https://example.com/missing")

    @respx.mock
    async def test_raises_on_500(self):
        respx.get("https://example.com/error").mock(
            return_value=httpx.Response(500)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_url("https://example.com/error")

    @respx.mock
    async def test_follows_redirects(self):
        respx.get("https://example.com/redirect").mock(
            return_value=httpx.Response(
                301,
                headers={"location": "https://example.com/terms"},
            )
        )
        respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        result = await fetch_url("https://example.com/redirect")
        assert "Terms of Service" in result

    @respx.mock
    async def test_javascript_only_page_returns_minimal_text(self):
        """Pages that only load content via JS return essentially empty HTML."""
        spa_html = "<html><body><div id='app'></div><script>loadApp()</script></body></html>"
        respx.get("https://spa.example.com/terms").mock(
            return_value=httpx.Response(200, text=spa_html)
        )
        result = await fetch_url("https://spa.example.com/terms")
        # After stripping script, almost nothing remains
        assert len(result.strip()) < 50

    @respx.mock
    async def test_sends_browser_user_agent(self):
        route = respx.get("https://example.com/terms").mock(
            return_value=httpx.Response(200, text=SIMPLE_HTML)
        )
        await fetch_url("https://example.com/terms")
        request = route.calls[0].request
        assert "Mozilla" in request.headers["user-agent"]
