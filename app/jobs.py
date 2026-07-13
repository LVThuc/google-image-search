from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.google import GoogleImageSearch
from app.models import SearchJob, SearchRequest


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStore:
    """Bounded, in-memory job runner for lightweight subsystem integration."""

    def __init__(self, search: GoogleImageSearch, ttl_seconds: int, max_jobs: int) -> None:
        self.search = search
        self.ttl = timedelta(seconds=ttl_seconds)
        self.max_jobs = max_jobs
        self.jobs: dict[str, SearchJob] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.lock = asyncio.Lock()

    async def submit(self, request: SearchRequest) -> SearchJob:
        async with self.lock:
            self._purge()
            if len(self.jobs) >= self.max_jobs:
                raise OverflowError("The search queue is full")
            now = utcnow()
            job = SearchJob(
                id=uuid4().hex,
                status="queued",
                created_at=now,
                updated_at=now,
                request=request,
            )
            self.jobs[job.id] = job
            self.tasks[job.id] = asyncio.create_task(self._run(job.id))
            return job.model_copy(deep=True)

    async def get(self, job_id: str) -> SearchJob | None:
        async with self.lock:
            self._purge()
            job = self.jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    async def cancel(self, job_id: str) -> SearchJob | None:
        async with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            task = self.tasks.get(job_id)
            if task and not task.done():
                task.cancel()
                job.status = "cancelled"
                job.updated_at = utcnow()
            return job.model_copy(deep=True)

    async def close(self) -> None:
        tasks = [task for task in self.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job.status = "running"
        job.updated_at = utcnow()
        try:
            job.result = await self.search.search(job.request)
            job.status = "succeeded"
        except asyncio.CancelledError:
            job.status = "cancelled"
            raise
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.updated_at = utcnow()

    def _purge(self) -> None:
        cutoff = utcnow() - self.ttl
        expired = [
            job_id
            for job_id, job in self.jobs.items()
            if job.updated_at < cutoff
            and job.status in {"succeeded", "failed", "cancelled"}
        ]
        for job_id in expired:
            self.jobs.pop(job_id, None)
            self.tasks.pop(job_id, None)
