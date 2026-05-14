from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    onionoo_base_url: str = "https://onionoo.torproject.org"
    onionoo_timeout_seconds: float = 30.0
    user_agent: str = "onionoo-fastapi/0.1 (+https://github.com/anoni-net/onionoo-fastapi)"
    default_limit: int = 100
    max_limit: int = 200

    cache_maxsize: int = 1024
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
