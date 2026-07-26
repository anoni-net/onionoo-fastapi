from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    # Comma-separated, matching pulse/backend's CORS_ALLOW_ORIGINS so both services
    # are configured the same way. Everything here is public read-only Onionoo data,
    # so the allowlist limits who can spend our upstream budget rather than
    # protecting anything secret. Set CORS_ALLOW_ORIGINS="" to switch CORS off.
    #
    # The default covers where the docs site is actually served from. Note the two
    # spellings are not symmetric: on clearnet the docs live under a path
    # (https://anoni.net/docs/), so the origin is the bare apex, while the onion
    # mirror is a subdomain of the same onion key, which is its own origin. The last
    # two entries are what `mkdocs serve` binds to, so a local docs checkout works
    # without extra configuration.
    #
    # CORS_ALLOWED_ORIGINS is the 1.0.0 name, still accepted so that upgrading does
    # not silently drop a self-hosted allowlist: `extra="ignore"` above would swallow
    # the old name without a word, and the only symptom would be a browser-side CORS
    # failure with nothing in our logs. `create_app` logs a deprecation line when the
    # old name is the one supplying the value.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default=[
            "https://anoni.net",
            "http://docs.anoninetru5tflukgfaehun7q6khowgmymcff3gtk5oyesqazhmfxtyd.onion",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        validation_alias=AliasChoices("CORS_ALLOW_ORIGINS", "CORS_ALLOWED_ORIGINS"),
    )
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 120
    log_level: str = "INFO"
    log_format: str = "json"
    metrics_enabled: bool = True
    healthz_ready_cache_seconds: float = 30.0

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accept `a,b` from the environment as well as a real list.

        `NoDecode` above is what makes this reachable: for a `list[str]` field
        pydantic-settings otherwise runs `json.loads` on the raw environment
        value first, and a bare `https://anoni.net` raises there before any
        validator gets to see it.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
