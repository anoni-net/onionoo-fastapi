from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MetaInfo(BaseModel):
    """Proxy-injected metadata about a response. Not present on raw passthrough."""

    model_config = ConfigDict(extra="allow")

    cache_age_seconds: float = Field(
        description=(
            "Age in seconds of the cached upstream payload that produced this "
            "response. 0.0 means freshly fetched from Onionoo."
        )
    )
    upstream_last_modified: str | None = Field(
        default=None,
        description="Last-Modified header value reported by Onionoo for this payload.",
    )


class OnionooEnvelope[RelayT, BridgeT](BaseModel):
    """
    Onionoo responses share a common envelope across all methods.

    Spec: https://metrics.torproject.org/onionoo.html
    """

    model_config = ConfigDict(extra="allow")

    meta: MetaInfo | None = Field(
        default=None,
        alias="_meta",
        description=(
            "Proxy-injected metadata (cache age, upstream Last-Modified). "
            "Absent when the response was returned via raw passthrough."
        ),
    )

    version: str = Field(description="Onionoo protocol version string (major.minor).")
    next_major_version_scheduled: str | None = Field(
        default=None,
        description="UTC date (YYYY-MM-DD) when the next major protocol version is scheduled.",
    )
    build_revision: str | None = Field(
        default=None,
        description="Git revision of the Onionoo instance's software (if provided by upstream).",
    )

    relays_published: str | None = Field(
        default=None,
        description=(
            "UTC timestamp (YYYY-MM-DD hh:mm:ss) when the relay consensus started being "
            "valid. Optional because some upstream methods (bandwidth/weights/clients/"
            "uptime) and trimmed `fields=` responses omit it."
        ),
    )
    relays_skipped: int | None = Field(
        default=None, description="Number of relays skipped due to offset (if non-zero)."
    )
    relays_truncated: int | None = Field(
        default=None, description="Number of relays truncated due to limit (if non-zero)."
    )
    relays: list[RelayT] = Field(default_factory=list, description="Relay objects.")

    bridges_published: str | None = Field(
        default=None,
        description=(
            "UTC timestamp (YYYY-MM-DD hh:mm:ss) when the bridge status was published. "
            "Optional for the same reasons as `relays_published`."
        ),
    )
    bridges_skipped: int | None = Field(
        default=None, description="Number of bridges skipped due to offset (if non-zero)."
    )
    bridges_truncated: int | None = Field(
        default=None, description="Number of bridges truncated due to limit (if non-zero)."
    )
    bridges: list[BridgeT] = Field(default_factory=list, description="Bridge objects.")
