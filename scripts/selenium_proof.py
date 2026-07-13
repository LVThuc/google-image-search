"""Run a live Selenium proof against both public API workflows."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json

import httpx

from app.config import Settings
from app.main import create_app


async def prove(query: str, limit: int) -> None:
    settings = replace(Settings.from_env(), backend="selenium")
    settings.validate()
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://proof"
        ) as client:
            health = await client.get("/health")
            docs = await client.get("/docs")
            direct = await client.post(
                "/v1/images/search", json={"query": query, "limit": limit}
            )
            health.raise_for_status()
            docs.raise_for_status()
            direct.raise_for_status()
            direct_body = direct.json()
            if direct_body["returned"] < 1:
                raise RuntimeError("Direct search returned no results")

            accepted = await client.post(
                "/v1/searches", json={"query": query, "limit": limit}
            )
            accepted.raise_for_status()
            status_url = accepted.json()["status_url"]
            job_body = None
            for _ in range(120):
                job = await client.get(status_url)
                job.raise_for_status()
                job_body = job.json()
                if job_body["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.25)
            if not job_body or job_body["status"] != "succeeded":
                raise RuntimeError(f"Queued search did not succeed: {job_body}")

    print(
        json.dumps(
            {
                "health": health.json(),
                "docs_status": docs.status_code,
                "direct": direct_body,
                "queued_status": job_body["status"],
                "queued_provider": job_body["result"]["provider"],
                "queued_returned": job_body["result"]["returned"],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="red panda")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(prove(args.query, args.limit))


if __name__ == "__main__":
    main()
