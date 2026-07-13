import httpx
import pytest

from app.config import Settings
from app.google import (
    GoogleImageSearch,
    SearchProviderError,
    parse_bing_html,
    parse_google_html,
    parse_yahoo_html,
)
from app.models import SearchRequest


def test_google_parser_finds_imgres_and_deduplicates() -> None:
    html = """
    <a href="/imgres?imgurl=https%3A%2F%2Fexample.com%2Fcat.jpg&amp;imgrefurl=https%3A%2F%2Fexample.com%2Fcats"><img src="https://example.com/thumb.jpg" alt="Cat"></a>
    <a href="/imgres?imgurl=https%3A%2F%2Fexample.com%2Fcat.jpg"></a>
    """
    results = parse_google_html(html, 10)
    assert str(results[0].image_url) == "https://example.com/cat.jpg"
    assert str(results[0].source_url) == "https://example.com/cats"
    assert len({str(result.image_url) for result in results}) == len(results)


def test_google_parser_finds_embedded_metadata_and_honors_limit() -> None:
    html = r'''["https://images.example/a.jpg",600,800],["https://images.example/b.jpg",300,400]'''
    results = parse_google_html(html, 1)
    assert len(results) == 1
    assert results[0].height == 600
    assert results[0].width == 800


def test_bing_parser_prefers_original_image_metadata() -> None:
    html = """
    <a class="iusc" m='{&quot;murl&quot;:&quot;https://images.example/full.jpg&quot;,&quot;turl&quot;:&quot;https://images.example/thumb.jpg&quot;,&quot;purl&quot;:&quot;https://example.com/page&quot;,&quot;t&quot;:&quot;A fox&quot;,&quot;mw&quot;:1200,&quot;mh&quot;:800}'></a>
    """
    [result] = parse_bing_html(html, 10)
    assert str(result.image_url) == "https://images.example/full.jpg"
    assert str(result.source_url) == "https://example.com/page"
    assert result.width == 1200


def test_yahoo_parser_accepts_lazy_loaded_images() -> None:
    html = '<img data-src="https://images.example/yahoo.jpg" alt="Ocean" width="640">'
    [result] = parse_yahoo_html(html, 10)
    assert result.title == "Ocean"
    assert result.width == 640


def test_parser_rejects_tiny_interface_images() -> None:
    html = '<img src="https://images.example/icon.png" width="42" height="42">'
    assert parse_bing_html(html, 10) == []


async def test_html_backend_falls_back_from_google_to_bing() -> None:
    visited: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.host)
        if request.url.host == "www.google.com":
            return httpx.Response(200, text="<html>verification</html>")
        return httpx.Response(
            200,
            text=(
                "<a m='{&quot;murl&quot;:"
                "&quot;https://images.example/result.jpg&quot;}'></a>"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await GoogleImageSearch(client, Settings(backend="html")).search(
            SearchRequest(query="cat")
        )

    assert visited == ["www.google.com", "www.bing.com"]
    assert response.provider == "bing"
    assert response.returned == 1


async def test_html_backend_reports_sanitized_error_after_all_fallbacks() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no results</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        search = GoogleImageSearch(client, Settings(backend="html"))
        with pytest.raises(SearchProviderError, match="No configured image provider"):
            await search.search(SearchRequest(query="cat"))


async def test_custom_search_is_normalized() -> None:
    seen_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "Red panda",
                        "link": "https://images.example/red-panda.jpg",
                        "mime": "image/jpeg",
                        "image": {
                            "thumbnailLink": "https://images.example/thumb.jpg",
                            "contextLink": "https://example.com/red-panda",
                            "width": 1200,
                            "height": 800,
                        },
                    }
                ]
            },
        )

    settings = Settings(
        backend="custom_search", google_api_key="test-key", google_cx="test-cx"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await GoogleImageSearch(client, settings).search(
            SearchRequest(query="red panda", limit=1)
        )

    assert response.provider == "google"
    assert response.results[0].width == 1200
    assert seen_request is not None
    assert seen_request.url.params["searchType"] == "image"
    assert seen_request.url.params["key"] == "test-key"
