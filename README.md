# Image Search API

An unofficial, multi-provider web image search service built with FastAPI.

It exposes normalized JSON endpoints for retrieving image references from
third-party search providers. The default browser-based backend queries Google
Images first and falls back to Bing and Yahoo when a provider is unavailable,
returns a verification page, or yields no parseable results.

Both immediate and queued search workflows are supported.

> [!IMPORTANT]
> This is an independent project and is not affiliated with, endorsed by, or
> sponsored by Google, Microsoft, Bing, Yahoo, or any other search provider.

## Features

* Direct image search through `POST /v1/images/search`
* Queued searches through `POST /v1/searches`
* Job polling, cancellation, expiry, and bounded in-memory retention
* Selenium with headless Chrome by default
* Google → Bing → Yahoo fallback for credential-free backends
* Successful backend and provider reported in every response
* Optional asynchronous raw-HTML backend
* Optional Google Custom Search JSON API backend
* Safe Search, locale, pagination, and configurable result limits
* Explicit Pydantic request and response schemas
* Interactive OpenAPI documentation at `/docs`
* Deterministic tests that do not contact live providers
* Opt-in end-to-end Selenium verification

The service returns references to third-party content. It does not grant a
license to download, reproduce, redistribute, or republish any returned image.

Returned URLs may expire or change. Verify the licensing status and permitted
uses of an image through its original source before using it.

## Requirements

* Python 3.10 or newer
* Chrome or Chromium
* [`uv`](https://docs.astral.sh/uv/)

Selenium Manager normally obtains a compatible ChromeDriver automatically.

## Quick start

Clone the repository and install the project:

```bash
git clone https://github.com/LVThuc/google-image-search.git
cd google-image-search

uv sync --extra dev
```

Start the API server:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open the interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

Check that the service is running:

```bash
curl http://127.0.0.1:8000/health
```

### Custom Chrome location

When Chrome or Chromium is not available on `PATH`, set its executable
explicitly:

```bash
export SELENIUM_BROWSER_BINARY=/path/to/chrome
```

Chrome's normal system libraries must also be installed. On Debian and Ubuntu,
installing a regular Chrome or Chromium package normally supplies the required
runtime libraries.

## API usage

### Search immediately

Send a request to `POST /v1/images/search`:

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

A successful response contains the backend and provider that produced the
results:

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

The provider field may be `google`, `bing`, or `yahoo`, depending on which
configured provider successfully returned parseable results.

### Submit a queued search

Create a job through `POST /v1/searches`:

```bash
curl -X POST http://127.0.0.1:8000/v1/searches \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "red panda in snow",
    "limit": 5
  }'
```

The service returns HTTP 202 with a job identifier and polling URL:

```json
{
  "id": "9c03851ee5a14c82a27bc01a4320b1bd",
  "status": "queued",
  "status_url": "/v1/searches/9c03851ee5a14c82a27bc01a4320b1bd"
}
```

Poll the job until it reaches `succeeded`, `failed`, or `cancelled`:

```bash
curl \
  http://127.0.0.1:8000/v1/searches/9c03851ee5a14c82a27bc01a4320b1bd
```

Cancel a queued or running job:

```bash
curl -X DELETE \
  http://127.0.0.1:8000/v1/searches/9c03851ee5a14c82a27bc01a4320b1bd
```

## Search backends

Select a backend with the `SEARCH_BACKEND` environment variable.

### Selenium

```bash
export SEARCH_BACKEND=selenium
```

This is the default backend.

It controls Chrome or Chromium through Selenium and extracts results from
browser-rendered search pages. Browser work runs in a worker thread so that it
does not block FastAPI's event loop.

Searches are serialized inside each process to avoid launching multiple Chrome
instances concurrently.

### Raw HTML

```bash
export SEARCH_BACKEND=html
```

This backend makes lightweight asynchronous HTTP requests and uses the same
configurable provider fallback.

It is generally faster than Selenium, but providers may return JavaScript-only
pages, consent screens, verification pages, or markup that cannot be parsed.

### Google Custom Search JSON API

```bash
export SEARCH_BACKEND=custom_search
export GOOGLE_API_KEY=your-api-key
export GOOGLE_CX=your-search-engine-id
```

This backend uses API credentials and is Google-only. An authenticated request
is never silently redirected to Bing or Yahoo.

Availability, quotas, billing, and eligibility for this backend are determined
by Google.

## Provider fallback

The default order for credential-free backends is:

```text
google,bing,yahoo
```

Change it through `SEARCH_PROVIDERS`:

```bash
export SEARCH_PROVIDERS=bing,google,yahoo
```

Providers are attempted in order until one returns parseable image results.

A fallback may occur when a provider:

* times out;
* returns no usable images;
* presents a consent or verification page;
* changes its page structure;
* temporarily rejects or rate-limits the request.

The service does not include CAPTCHA solving or mechanisms intended to bypass
authentication, access controls, or provider verification challenges.

## Configuration

| Variable                  | Default             | Description                                                      |
| ------------------------- | ------------------- | ---------------------------------------------------------------- |
| `SEARCH_BACKEND`          | `selenium`          | Search implementation: `selenium`, `html`, or `custom_search`    |
| `SEARCH_PROVIDERS`        | `google,bing,yahoo` | Ordered providers used by the Selenium and HTML backends         |
| `GOOGLE_API_KEY`          | unset               | API key required by the `custom_search` backend                  |
| `GOOGLE_CX`               | unset               | Search-engine identifier required by the `custom_search` backend |
| `REQUEST_TIMEOUT_SECONDS` | `20`                | Timeout applied to each provider attempt                         |
| `JOB_TTL_SECONDS`         | `3600`              | Retention period after a job reaches a terminal state            |
| `MAX_JOBS`                | `1000`              | Maximum number of jobs retained in one process                   |
| `SEARCH_USER_AGENT`       | browser-like value  | User-Agent sent by credential-free backends                      |
| `SELENIUM_BROWSER_BINARY` | auto-discovered     | Path to the Chrome or Chromium executable                        |
| `SELENIUM_HEADLESS`       | `true`              | Whether Selenium runs without a visible browser window           |

## Testing

The deterministic test suite does not contact real search providers:

```bash
uv sync --extra dev
uv run pytest
```

## Live Selenium verification

Run the opt-in end-to-end verification script:

```bash
uv run python scripts/selenium_proof.py \
  --query "red panda" \
  --limit 3
```

The script exercises:

* a real Selenium browser;
* live provider traffic;
* the direct search endpoint;
* the queued search workflow;
* the OpenAPI documentation route.

It exits with a nonzero status unless both search workflows succeed and return
at least one result.

Live verification can fail because of consent pages, verification challenges,
provider markup changes, network conditions, regional behavior, or rate limits.

## Deployment notes

### Process-local job storage

The job queue, retained job state, and Selenium lock are process-local.

Do not start multiple Uvicorn workers when clients must reliably poll queued
jobs. A polling request may otherwise reach a process that does not contain the
original job.

For example, avoid:

```bash
uv run uvicorn app.main:app --workers 4
```

For multiple workers, replicas, or durable jobs, replace `JobStore` with shared
infrastructure such as:

* Redis;
* a relational database;
* a message broker and task queue.

The public request and response schemas can remain unchanged.

### Request rate

Credential-free search interfaces are undocumented and may change without
notice. Use conservative request rates, cache results when appropriate, and
respect the terms and policies of each selected provider.

Provider failures are returned as sanitized upstream errors and should generally
be treated as retryable unless the response indicates a permanent configuration
problem.

### Public deployments

This project does not provide authentication, per-client quotas, or distributed
rate limiting by default.

Before exposing an instance to the public internet, consider adding:

* authentication;
* request-size limits;
* per-user rate limits;
* network and browser sandboxing;
* structured monitoring;
* persistent or distributed job storage;
* outbound request controls.

## Reproducibility

Web search results are dynamic. The same query may produce different candidates
at different times, locations, or providers.

For reproducible experiments, persist the complete response produced by the
external search stage, including:

* the original query;
* retrieval timestamp;
* selected backend and provider;
* language, country, page, and Safe Search settings;
* rank and source URL for every candidate;
* the software commit used for retrieval;
* a content hash when an image is downloaded lawfully.

Comparative experiments should reuse the same frozen candidate set rather than
performing a new live web search for each model or method.

## Legal and usage notice

This software is an independent and unofficial project. It is not affiliated
with, endorsed by, or sponsored by Google, Microsoft, Bing, Yahoo, or any other
search provider.

Users are responsible for ensuring that their deployment and use of this
software comply with:

* applicable laws and regulations;
* the terms and policies of the selected search providers;
* copyright and licensing requirements;
* privacy and data-protection obligations;
* applicable rate limits and access restrictions.

Search responses contain references to content hosted by third parties. This
repository does not own that content and does not grant permission to download,
copy, modify, redistribute, or republish it.

Provider availability, result ranking, page structure, and policies may change
without notice. Search results may be incomplete, inaccurate, unavailable, or
non-reproducible.

The software is provided under the terms of the MIT License, without warranty of
any kind. See the `LICENSE` file for the governing license terms.

## Contributing

Bug reports and pull requests are welcome.

When reporting provider-specific parsing failures, include:

* the selected backend;
* provider name;
* operating system;
* browser version;
* relevant sanitized logs;
* whether the response was a consent, verification, or ordinary result page.

Do not include API keys, cookies, authentication tokens, complete browser
profiles, or other sensitive information in issues.

## License

Copyright © 2026 Lê Văn Thức.

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for
details.
