from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SafeSearch(str, Enum):
    active = "active"
    off = "off"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500, examples=["red panda"])
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=1, ge=1, le=100)
    safe_search: SafeSearch = SafeSearch.active
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}$")
    country: str = Field(default="us", pattern=r"^[A-Za-z]{2}$")

    @field_validator("query")
    @classmethod
    def query_must_not_be_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must contain non-whitespace characters")
        return value


class ImageResult(BaseModel):
    title: str = ""
    image_url: HttpUrl
    thumbnail_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    mime_type: str | None = None


class SearchResponse(BaseModel):
    query: str
    page: int
    requested: int
    returned: int
    backend: str
    provider: Literal["google", "bing", "yahoo"]
    results: list[ImageResult]


class JobAccepted(BaseModel):
    id: str
    status: Literal["queued"]
    status_url: str


class SearchJob(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    created_at: datetime
    updated_at: datetime
    request: SearchRequest
    result: SearchResponse | None = None
    error: str | None = None
