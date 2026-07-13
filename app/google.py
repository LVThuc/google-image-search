from __future__ import annotations

import asyncio
from collections.abc import Iterable
from glob import glob
from html.parser import HTMLParser
import json
import os
import re
import shutil
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from app.config import Settings
from app.models import ImageResult, SearchRequest, SearchResponse


class SearchProviderError(RuntimeError):
    """A sanitized provider failure suitable for returning through the API."""


class _ResultParser(HTMLParser):
    """Collect common image markup plus Bing's JSON metadata attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, Any]] = []
        self._anchors: list[dict[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "a":
            self._anchors.append(values)
            metadata = values.get("m")
            if metadata:
                try:
                    item = json.loads(metadata)
                except (TypeError, json.JSONDecodeError):
                    item = None
                if isinstance(item, dict):
                    self.results.append(
                        {
                            "title": item.get("t") or item.get("title") or "",
                            "image_url": item.get("murl"),
                            "thumbnail_url": item.get("turl"),
                            "source_url": item.get("purl"),
                            "width": item.get("mw"),
                            "height": item.get("mh"),
                        }
                    )
            return

        if tag != "img":
            return
        src = (
            values.get("data-src")
            or values.get("data-original")
            or values.get("src")
        )
        if not _is_http_url(src):
            return
        anchor = self._anchors[-1] if self._anchors else {}
        href = _source_href(anchor.get("href", ""))
        width = _dimension(values.get("data-width") or values.get("width"))
        height = _dimension(values.get("data-height") or values.get("height"))
        self.results.append(
            {
                "title": values.get("alt", ""),
                "image_url": src,
                "thumbnail_url": src,
                "source_url": href,
                "width": width,
                "height": height,
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchors:
            self._anchors.pop()


_GOOGLE_IMAGE_LINK = re.compile(r'href=["\']([^"\']*(?:/imgres|/url)\?[^"\']+)', re.I)
_GOOGLE_EMBEDDED_IMAGE = re.compile(
    r'\["((?:https?:)?(?:\\u003d|\\u0026|\\/|[^" ])+?)",(\d+),(\d+)\]'
)


def _is_http_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _dimension(value: object) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        match = re.match(r"\d+", value)
        if match and int(match.group()) > 0:
            return int(match.group())
    return None


def _source_href(href: str) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.path == "/url":
        href = (parse_qs(parsed.query).get("q") or [""])[0]
    return href if _is_http_url(href) else None


def _decode_google_string(value: str) -> str | None:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return None
    if decoded.startswith("//"):
        decoded = "https:" + decoded
    return decoded if _is_http_url(decoded) else None


def _is_provider_asset(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    if path.endswith((".svg", ".gif")):
        return True
    return host in {
        "www.google.com",
        "www.bing.com",
        "s.yimg.com",
    }


def _normalize(
    raw: Iterable[dict[str, Any]], limit: int
) -> list[ImageResult]:
    output: list[ImageResult] = []
    seen: set[str] = set()
    for item in raw:
        url = item.get("image_url")
        if not _is_http_url(url) or url in seen or _is_provider_asset(url):
            continue
        seen.add(url)
        cleaned = {
            "title": str(item.get("title") or ""),
            "image_url": url,
            "thumbnail_url": item.get("thumbnail_url"),
            "source_url": item.get("source_url"),
            "width": _dimension(item.get("width")),
            "height": _dimension(item.get("height")),
            "mime_type": item.get("mime_type"),
        }
        width = cleaned["width"]
        height = cleaned["height"]
        if width is not None and height is not None and max(width, height) < 100:
            continue
        try:
            output.append(ImageResult.model_validate(cleaned))
        except ValueError:
            continue
        if len(output) >= limit:
            break
    return output


def parse_google_html(html: str, limit: int) -> list[ImageResult]:
    raw: list[dict[str, Any]] = []

    for match in _GOOGLE_IMAGE_LINK.finditer(html):
        query = parse_qs(urlparse(match.group(1).replace("&amp;", "&")).query)
        image_url = (query.get("imgurl") or [None])[0]
        if image_url:
            raw.append(
                {
                    "image_url": image_url,
                    "source_url": (query.get("imgrefurl") or [None])[0],
                }
            )

    for match in _GOOGLE_EMBEDDED_IMAGE.finditer(html):
        encoded, height, width = match.groups()
        url = _decode_google_string(encoded)
        if url:
            raw.append(
                {"image_url": url, "height": height, "width": width}
            )

    parser = _ResultParser()
    parser.feed(html)
    raw.extend(parser.results)
    return _normalize(raw, limit)


def parse_bing_html(html: str, limit: int) -> list[ImageResult]:
    parser = _ResultParser()
    parser.feed(html)
    return _normalize(parser.results, limit)


def parse_yahoo_html(html: str, limit: int) -> list[ImageResult]:
    parser = _ResultParser()
    parser.feed(html)
    return _normalize(parser.results, limit)


PARSERS = {
    "google": parse_google_html,
    "bing": parse_bing_html,
    "yahoo": parse_yahoo_html,
}


class GoogleImageSearch:
    """Normalize image results from Google, with Bing/Yahoo fallback modes."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self._browser_lock = asyncio.Lock()

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self.settings.backend == "custom_search":
            provider = "google"
            results = await self._custom_search(request)
        elif self.settings.backend == "selenium":
            async with self._browser_lock:
                provider, results = await asyncio.to_thread(
                    self._selenium_search, request
                )
        else:
            provider, results = await self._html_search(request)
        return SearchResponse(
            query=request.query,
            page=request.page,
            requested=request.limit,
            returned=len(results),
            backend=self.settings.backend,
            provider=provider,
            results=results,
        )

    async def _custom_search(self, request: SearchRequest) -> list[ImageResult]:
        start = (request.page - 1) * request.limit + 1
        if start > 91:
            raise SearchProviderError(
                "Google Custom Search cannot serve this result page"
            )
        response = await self._get(
            "https://customsearch.googleapis.com/customsearch/v1",
            params={
                "key": self.settings.google_api_key,
                "cx": self.settings.google_cx,
                "q": request.query,
                "searchType": "image",
                "num": min(request.limit, 10),
                "start": start,
                "safe": request.safe_search.value,
                "hl": request.language.lower(),
                "gl": request.country.lower(),
            },
            provider="Google",
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SearchProviderError("Google returned an invalid response") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise SearchProviderError("Google returned no image results")
        raw = []
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            image = item.get("image") if isinstance(item.get("image"), dict) else {}
            raw.append(
                {
                    "title": item.get("title", ""),
                    "image_url": item.get("link"),
                    "thumbnail_url": image.get("thumbnailLink"),
                    "source_url": image.get("contextLink"),
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "mime_type": item.get("mime"),
                }
            )
        results = _normalize(raw, request.limit)
        if not results:
            raise SearchProviderError("Google returned no image results")
        return results

    async def _html_search(
        self, request: SearchRequest
    ) -> tuple[str, list[ImageResult]]:
        for provider in self.settings.providers:
            url, params = self._provider_request(provider, request)
            try:
                response = await self._get(url, params=params, provider=provider.title())
            except SearchProviderError:
                continue
            results = PARSERS[provider](response.text, request.limit)
            if results:
                return provider, results
        raise SearchProviderError(
            "No configured image provider returned usable results"
        )

    def _selenium_search(
        self, request: SearchRequest
    ) -> tuple[str, list[ImageResult]]:
        driver = None
        try:
            driver = webdriver.Chrome(options=self._chrome_options(request))
            driver.set_page_load_timeout(self.settings.request_timeout_seconds)
            for provider in self.settings.providers:
                url, params = self._provider_request(provider, request)
                try:
                    driver.get(f"{url}?{urlencode(params)}")
                    WebDriverWait(
                        driver, self.settings.request_timeout_seconds
                    ).until(
                        lambda browser: browser.execute_script(
                            "return document.readyState"
                        )
                        in {"interactive", "complete"}
                    )
                    driver.execute_script(
                        "window.scrollTo(0, Math.min(document.body.scrollHeight, 1600))"
                    )
                    WebDriverWait(driver, 3).until(
                        lambda browser: len(browser.find_elements("css selector", "img"))
                        > 0
                    )
                except WebDriverException:
                    continue
                results = PARSERS[provider](driver.page_source, request.limit)
                if results:
                    return provider, results
        except WebDriverException as exc:
            raise SearchProviderError(
                "Selenium could not start or control Chrome"
            ) from exc
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except WebDriverException:
                    pass
        raise SearchProviderError(
            "No configured image provider returned usable results in Selenium"
        )

    def _chrome_options(self, request: SearchRequest) -> Options:
        options = Options()
        binary = self.settings.selenium_browser_binary or _discover_chrome()
        if binary:
            options.binary_location = binary
        if self.settings.selenium_headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1440,1200")
        options.add_argument(f"--lang={request.language.lower()}-{request.country.upper()}")
        options.add_argument(f"--user-agent={self.settings.user_agent}")
        options.add_experimental_option(
            "excludeSwitches", ["enable-automation", "enable-logging"]
        )
        return options

    def _provider_request(
        self, provider: str, request: SearchRequest
    ) -> tuple[str, dict[str, object]]:
        offset = (request.page - 1) * request.limit
        if provider == "google":
            return "https://www.google.com/search", {
                "q": request.query,
                "udm": "2",
                "start": offset,
                "safe": request.safe_search.value,
                "hl": request.language.lower(),
                "gl": request.country.lower(),
                "filter": "0",
            }
        if provider == "bing":
            return "https://www.bing.com/images/search", {
                "q": request.query,
                "first": offset + 1,
                "safeSearch": "strict"
                if request.safe_search.value == "active"
                else "off",
                "setlang": request.language.lower(),
                "cc": request.country.lower(),
            }
        return "https://images.search.yahoo.com/search/images", {
            "p": request.query,
            "b": offset + 1,
            "vm": "r"
            if request.safe_search.value == "active"
            else "p",
        }

    async def _get(
        self,
        url: str,
        params: dict[str, object],
        provider: str,
    ) -> httpx.Response:
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {429, 503}:
                raise SearchProviderError(
                    f"{provider} temporarily rejected the search"
                ) from exc
            raise SearchProviderError(f"{provider} search request failed") from exc
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Could not reach {provider}") from exc


def _discover_chrome() -> str | None:
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    candidates: list[str] = []
    for pattern in (
        os.path.expanduser(
            "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"
        ),
        "/tmp/google-image-search-browsers/chromium-*/chrome-linux64/chrome",
    ):
        candidates.extend(glob(pattern))
    return sorted(candidates, reverse=True)[0] if candidates else None
