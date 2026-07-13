from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.config import Settings
from app.google import GoogleImageSearch, SearchProviderError
from app.jobs import JobStore
from app.models import JobAccepted, SearchJob, SearchRequest, SearchResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    resolved.validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            timeout=resolved.request_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": resolved.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            try:
                search = GoogleImageSearch(client, resolved)
                app.state.search = search
                app.state.jobs = JobStore(
                    search, resolved.job_ttl_seconds, resolved.max_jobs
                )
                yield
            finally:
                if hasattr(app.state, "jobs"):
                    await app.state.jobs.close()

    app = FastAPI(
        title="Image Search API",
        description=(
            "Search Google Images, with Bing and Yahoo fallback, immediately or "
            "submit a job for another subsystem to poll later."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.exception_handler(SearchProviderError)
    async def provider_error(_: Request, exc: SearchProviderError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "image-search", "docs": "/docs"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "backend": resolved.backend,
            "providers": ",".join(resolved.providers),
        }

    @app.post("/v1/images/search", response_model=SearchResponse)
    async def search_images(body: SearchRequest, request: Request) -> SearchResponse:
        return await request.app.state.search.search(body)

    @app.post(
        "/v1/searches", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED
    )
    async def submit_search(body: SearchRequest, request: Request) -> JobAccepted:
        try:
            job = await request.app.state.jobs.submit(body)
        except OverflowError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JobAccepted(
            id=job.id, status="queued", status_url=f"/v1/searches/{job.id}"
        )

    @app.get("/v1/searches/{job_id}", response_model=SearchJob)
    async def get_search(job_id: str, request: Request) -> SearchJob:
        job = await request.app.state.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Search job not found")
        return job

    @app.delete("/v1/searches/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def cancel_search(job_id: str, request: Request) -> Response:
        job = await request.app.state.jobs.cancel(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Search job not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


app = create_app()
