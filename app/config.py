from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
SUPPORTED_BACKENDS = {"selenium", "html", "custom_search"}
SUPPORTED_PROVIDERS = ("google", "bing", "yahoo")


def _positive_integer(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _providers(raw: str) -> tuple[str, ...]:
    values = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not values:
        raise ValueError("SEARCH_PROVIDERS must contain at least one provider")
    unknown = set(values) - set(SUPPORTED_PROVIDERS)
    if unknown:
        raise ValueError(
            "SEARCH_PROVIDERS may contain only google, bing, and yahoo"
        )
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    backend: str = "selenium"
    providers: tuple[str, ...] = SUPPORTED_PROVIDERS
    google_api_key: str | None = None
    google_cx: str | None = None
    request_timeout_seconds: int = 20
    job_ttl_seconds: int = 3600
    max_jobs: int = 1000
    user_agent: str = DEFAULT_USER_AGENT
    selenium_browser_binary: str | None = None
    selenium_headless: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend=os.getenv("SEARCH_BACKEND", "selenium").lower(),
            providers=_providers(
                os.getenv("SEARCH_PROVIDERS", ",".join(SUPPORTED_PROVIDERS))
            ),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            google_cx=os.getenv("GOOGLE_CX"),
            request_timeout_seconds=_positive_integer(
                "REQUEST_TIMEOUT_SECONDS", 20
            ),
            job_ttl_seconds=_positive_integer("JOB_TTL_SECONDS", 3600),
            max_jobs=_positive_integer("MAX_JOBS", 1000),
            user_agent=os.getenv("SEARCH_USER_AGENT", DEFAULT_USER_AGENT),
            selenium_browser_binary=os.getenv("SELENIUM_BROWSER_BINARY"),
            selenium_headless=_boolean("SELENIUM_HEADLESS", True),
        )

    def validate(self) -> None:
        if self.backend not in SUPPORTED_BACKENDS:
            raise ValueError(
                "SEARCH_BACKEND must be selenium, html, or custom_search"
            )
        if not self.providers or set(self.providers) - set(SUPPORTED_PROVIDERS):
            raise ValueError("Unsupported search provider")
        if self.backend == "custom_search" and not (
            self.google_api_key and self.google_cx
        ):
            raise ValueError(
                "GOOGLE_API_KEY and GOOGLE_CX are required for custom_search"
            )
        if min(
            self.request_timeout_seconds,
            self.job_ttl_seconds,
            self.max_jobs,
        ) <= 0:
            raise ValueError("timeout, TTL, and job limit settings must be positive")
