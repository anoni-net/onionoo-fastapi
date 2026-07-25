from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    onionoo_base_url: str = "https://onionoo.torproject.org"
    onionoo_timeout_seconds: float = 30.0
    user_agent: str = (
        f"onionoo-fastapi/{__version__} (+https://github.com/anoni-net/onionoo-fastapi)"
    )
    default_limit: int = 100
    # Onionoo has no server-side result cap; a single request can return the whole
    # corpus (~10k relays + ~2.5k bridges). Keep the ceiling high enough to retrieve
    # everything in one call, which avoids offset pagination, which drifts because
    # Onionoo's default ordering is not stable across requests. Tune via MAX_LIMIT.
    max_limit: int = 20000

    # The full-corpus ceiling above is only affordable with a `fields=` projection.
    # Measured against live Onionoo at limit=20000: /details is ~93 MB untrimmed and
    # ~2.4 MB with five fields, while /summary stays ~1.5 MB either way. So /details
    # rejects a limit past this without a projection. Tune via MAX_LIMIT_UNTRIMMED.
    max_limit_untrimmed: int = 200

    # Entries hold the parsed upstream body, so a handful of large `/details` documents
    # dominate the resident set. The untrimmed ceiling above keeps any single entry to
    # a few MB; raise this only after checking the payload sizes your deployment sees.
    # Tune via CACHE_MAXSIZE.
    cache_maxsize: int = 128
    cache_default_ttl_seconds: float = 300.0
    upstream_retry_attempts: int = 2

    cors_allowed_origins: list[str] = []
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 120
    log_level: str = "INFO"
    log_format: str = "json"
    metrics_enabled: bool = True
    healthz_ready_cache_seconds: float = 30.0


settings = Settings()
