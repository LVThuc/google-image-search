import asyncio
import os
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.models import ImageResult, SearchResponse


class FakeSearch:
    async def search(self, request):
        await asyncio.sleep(0)
        result = ImageResult(image_url="https://example.com/image.jpg", title="Example")
        return SearchResponse(
            query=request.query,
            page=request.page,
            requested=request.limit,
            returned=1,
            backend="html",
            provider="google",
            results=[result],
        )


@pytest.fixture
async def client():
    app = create_app(Settings(backend="html"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client, app


async def test_health_describes_provider_order(client) -> None:
    test_client, _ = client
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "backend": "html",
        "providers": "google,bing,yahoo",
    }


async def test_direct_search(client) -> None:
    test_client, app = client
    app.state.search = FakeSearch()
    response = await test_client.post("/v1/images/search", json={"query": "red panda"})
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "Example"


async def test_async_search_job(client) -> None:
    test_client, app = client
    app.state.search = FakeSearch()
    app.state.jobs.search = app.state.search
    accepted = await test_client.post("/v1/searches", json={"query": "red panda"})
    assert accepted.status_code == 202
    status_url = accepted.json()["status_url"]
    for _ in range(20):
        response = await test_client.get(status_url)
        if response.json()["status"] == "succeeded":
            break
        await asyncio.sleep(0)
    assert response.json()["result"]["returned"] == 1


async def test_validation_and_missing_job(client) -> None:
    test_client, _ = client
    for query in ("", "   "):
        response = await test_client.post("/v1/images/search", json={"query": query})
        assert response.status_code == 422
    response = await test_client.get("/v1/searches/unknown")
    assert response.status_code == 404


def test_environment_defaults_to_selenium_and_provider_fallbacks() -> None:
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings.from_env()
    assert settings.backend == "selenium"
    assert settings.providers == ("google", "bing", "yahoo")


def test_provider_order_is_configurable_and_deduplicated() -> None:
    with patch.dict(
        os.environ, {"SEARCH_PROVIDERS": "bing,google,bing"}, clear=True
    ):
        settings = Settings.from_env()
    assert settings.providers == ("bing", "google")


def test_custom_search_requires_google_credentials() -> None:
    with pytest.raises(ValueError, match="GOOGLE_API_KEY.*GOOGLE_CX"):
        Settings(backend="custom_search").validate()
