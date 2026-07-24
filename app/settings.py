from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    onionoo_base_url: str = "https://onionoo.torproject.org"
    onionoo_timeout_seconds: float = 30.0
    user_agent: str = "onionoo-fastapi/0.1 (+https://github.com/anoni-net/onionoo-fastapi)"
    default_limit: int = 100
    # Onionoo has no server-side result cap; a single `/details` request can return
    # the whole corpus (~10k relays + ~2.5k bridges). Keep the ceiling high enough
    # to retrieve everything in one call — combined with `fields=` to trim payload,
    # this avoids offset pagination, which drifts because Onionoo's default ordering
    # is not stable across requests. Operators can tune via MAX_LIMIT.
    max_limit: int = 20000

    # `/details` payloads can reach tens of MB once Onionoo's full corpus is
    # parsed; with hundreds of entries the resident set can quickly run into the
    # gigabytes. Keep the default conservative and let operators raise it for
    # high-traffic deployments. Tune via CACHE_MAXSIZE.
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
