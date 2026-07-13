# AGENTS.md

## Purpose and contracts

This repository is a small FastAPI image-search service for people and other
software systems. It exposes both an immediate request/response API and a queued
submit/poll API. Routes under `/v1` are integration contracts: extend them
compatibly or introduce a new API version for breaking changes.

The credential-free default uses Selenium and headless Chrome. It attempts
Google Images first, followed by Bing Images and Yahoo Images when a page is
blocked or contains no usable results. The response's `provider` field identifies
the provider that actually succeeded. The `custom_search` mode uses Google's
official JSON API and never silently changes provider.

## Code map

- `app/main.py`: application factory, lifespan resources, error mapping, routes.
- `app/models.py`: explicit public Pydantic request, response, and job schemas.
- `app/google.py`: provider URLs, parsers, HTTP adapters, and Selenium adapter.
- `app/jobs.py`: bounded, expiring, process-local asynchronous job runner.
- `app/config.py`: environment loading and startup validation.
- `scripts/selenium_proof.py`: opt-in live proof of direct and queued workflows.
- `tests/`: deterministic, network-free unit and API tests.

Keep provider parsing and browser selectors out of route handlers. Keep public
schemas explicit so generated OpenAPI documentation remains useful.

## Development rules

1. Provider-facing HTTP must be asynchronous and reuse the lifespan-managed
   `httpx.AsyncClient`.
2. Selenium is synchronous; run it outside the event loop with
   `asyncio.to_thread`. Do not call WebDriver directly from a route coroutine.
3. Validate all caller-controlled parameters with Pydantic.
4. Translate upstream/browser failures into `SearchProviderError`. Never expose
   API keys, upstream bodies, Selenium traces, or internal exceptions.
5. Unit and API tests must not contact real search providers. Use mocked HTTP
   transports, representative HTML, or a fake search service.
6. Preserve Google-first ordering by default and preserve Bing/Yahoo fallback.
   All three HTML formats are undocumented and require parser maintenance.
7. Preserve `selenium`, `html`, and `custom_search` modes unless an intentional
   compatibility change is requested.
8. The job store is process-local. Multiple workers or durable delivery require
   a shared queue/store while retaining the public schemas and state names.
9. Returned URLs refer to third-party content. Do not download or persist those
   files in the API process without a separately reviewed security design.

## Verification

Run deterministic checks before handoff:

```bash
uv sync --extra dev
uv run pytest
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Confirm `/health`, `/docs`, `POST /v1/images/search`, and the submit/poll flow.
When browser/network access is available, also run the opt-in live proof:

```bash
uv run python scripts/selenium_proof.py --query "red panda" --limit 3
```

The live proof is intentionally not part of pytest because provider markup,
rate limits, consent screens, and network access are external variables.
