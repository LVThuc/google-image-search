# Image Search API

A FastAPI service that searches Google Images and returns normalized JSON. If
Google blocks the browser or yields no parseable images, the credential-free
backends automatically try Bing and then Yahoo. Both immediate and queued
workflows are supported.

## What it provides

- `POST /v1/images/search` for a direct result
- `POST /v1/searches` plus `GET /v1/searches/{id}` for queued work
- Selenium + headless Chrome by default, with no API key required
- Google → Bing → Yahoo fallback with the successful provider in every response
- Optional raw-HTML and Google Custom Search JSON API modes
- Safe Search, locale, pagination, result limits, cancellation, and job expiry
- Explicit Pydantic schemas and OpenAPI docs at `/docs`

Returned URLs point to third-party content and can expire. Check licensing and
usage rights before downloading or republishing an image.

## Quick start

Python 3.10+ and Chrome/Chromium are required. Selenium Manager normally obtains
a compatible ChromeDriver automatically.

```bash
uv sync --extra dev
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs` or verify the process:

```bash
curl http://127.0.0.1:8000/health
```

If Chrome is not on `PATH`, set its executable explicitly:

```bash
export SELENIUM_BROWSER_BINARY=/path/to/chrome
```

Chrome's normal system libraries must also be installed. On Debian/Ubuntu, a
regular Chrome/Chromium package installation supplies them.

## Search immediately

```bash
curl -X POST http://127.0.0.1:8000/v1/images/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "red panda in snow",
    "limit": 5,
    "page": 1,
    "safe_search": "active",
    "language": "en",
    "country": "us"
  }'
```

A successful response includes both the backend and the provider that worked:

```json
{
  "query": "red panda in snow",
  "page": 1,
  "requested": 5,
  "returned": 1,
  "backend": "selenium",
  "provider": "google",
  "results": [
    {
      "title": "Red panda",
      "image_url": "https://example.org/red-panda.jpg",
      "thumbnail_url": "https://example.org/red-panda-thumb.jpg",
      "source_url": "https://example.org/animals/red-panda",
      "width": 1600,
      "height": 900,
      "mime_type": "image/jpeg"
    }
  ]
}
```

## Submit and poll a job

```bash
curl -X POST http://127.0.0.1:8000/v1/searches \
  -H 'Content-Type: application/json' \
  -d '{"query":"red panda in snow","limit":5}'
```

The service returns HTTP 202 and a `status_url`:

```json
{
  "id": "9c03851ee5a14c82a27bc01a4320b1bd",
  "status": "queued",
  "status_url": "/v1/searches/9c03851ee5a14c82a27bc01a4320b1bd"
}
```

Poll until the state is `succeeded`, `failed`, or `cancelled`:

```bash
curl http://127.0.0.1:8000/v1/searches/9c03851ee5a14c82a27bc01a4320b1bd
curl -X DELETE http://127.0.0.1:8000/v1/searches/9c03851ee5a14c82a27bc01a4320b1bd
```

## Backends and fallback order

`SEARCH_BACKEND=selenium` is the default. Browser calls run in a worker thread so
they do not block FastAPI's event loop. Searches are serialized inside one
process to avoid launching many Chrome instances at once.

`SEARCH_BACKEND=html` makes lightweight asynchronous HTTP requests and applies
the same Google → Bing → Yahoo fallback. It is faster, but search providers may
return JavaScript-only or verification pages.

`SEARCH_BACKEND=custom_search` uses Google's Custom Search JSON API. Configure:

```bash
export SEARCH_BACKEND=custom_search
export GOOGLE_API_KEY=your-key
export GOOGLE_CX=your-search-engine-id
```

This official mode is Google-only; it does not silently send an API-authenticated
request to another provider.

Change credential-free provider order when needed:

```bash
export SEARCH_PROVIDERS=google,bing,yahoo
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `SEARCH_BACKEND` | `selenium` | `selenium`, `html`, or `custom_search` |
| `SEARCH_PROVIDERS` | `google,bing,yahoo` | Ordered providers for Selenium/HTML |
| `GOOGLE_API_KEY` | unset | Required for `custom_search` |
| `GOOGLE_CX` | unset | Required for `custom_search` |
| `REQUEST_TIMEOUT_SECONDS` | `20` | Per-provider request/browser timeout |
| `JOB_TTL_SECONDS` | `3600` | Retention after a terminal job update |
| `MAX_JOBS` | `1000` | Maximum retained jobs in this process |
| `SEARCH_USER_AGENT` | browser-like value | User-Agent sent to providers |
| `SELENIUM_BROWSER_BINARY` | auto-discovered | Chrome/Chromium executable |
| `SELENIUM_HEADLESS` | `true` | Run Chrome without a visible window |

## Verification

The deterministic suite never contacts a real provider:

```bash
uv sync --extra dev
uv run pytest
```

For an opt-in end-to-end proof with real Selenium, provider traffic, the direct
route, `/docs`, and the queued workflow:

```bash
uv run python scripts/selenium_proof.py --query "red panda" --limit 3
```

The command exits nonzero unless both search workflows succeed with at least one
result. Live checks can still be affected by consent pages, verification
challenges, provider markup changes, and rate limits.

## Deployment notes

The queue and Selenium lock are process-local. Do not use multiple Uvicorn
workers when clients must reliably poll a queued job; a later request can reach a
different worker. For multiple replicas or durable jobs, replace `JobStore` with
Redis, a database, or a task queue while preserving the public job schema.

Automated search pages are undocumented and can change. Use conservative request
rates, honor provider terms and policies, and treat sanitized 502 provider
failures as retryable.
