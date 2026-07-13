# Image search subsystem brief

The service turns a validated text query into normalized third-party image
records. Callers can wait on `POST /v1/images/search` or submit the same request
to `POST /v1/searches` and poll the returned `status_url`.

The default Selenium mode searches in this order:

1. Google Images (preferred)
2. Bing Images (fallback)
3. Yahoo Images (final fallback)

Search stops at the first provider with usable results. `SearchResponse.provider`
records that choice; `SearchResponse.backend` records the mechanism (`selenium`,
`html`, or `custom_search`). Provider failures are sanitized before crossing the
API boundary.

Implementation constraints, compatibility rules, and verification commands live
in `AGENTS.md`. Setup, API examples, and operating guidance live in `README.md`.
