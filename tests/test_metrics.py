"""/metrics exposes Prometheus output and our custom OnionooClient counters move."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.observability import CACHE_HITS, CACHE_MISSES, UPSTREAM_LATENCY
from tests.conftest import make_summary_envelope, relay


def _value(counter) -> float:
    """Read the current numeric value of a prometheus Counter/Histogram (labelless)."""
    return counter._value.get()  # type: ignore[attr-defined]


def test_metrics_endpoint_serves_prometheus_format(app_client: TestClient) -> None:
    r = app_client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert "onionoo_cache_hits_total" in body
    assert "onionoo_cache_misses_total" in body
    assert "onionoo_upstream_seconds" in body
    assert "onionoo_upstream_errors_total" in body


def test_cache_hits_and_misses_counters_advance(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json=make_summary_envelope(relays=[relay("r1", "a" * 40)]))
    )

    miss_before = _value(CACHE_MISSES)
    hit_before = _value(CACHE_HITS)

    # First call → miss; second identical call → hit.
    app_client.get("/v1/summary", params={"limit": 1, "type": "relay"})
    app_client.get("/v1/summary", params={"limit": 1, "type": "relay"})

    assert _value(CACHE_MISSES) == miss_before + 1
    assert _value(CACHE_HITS) == hit_before + 1


def test_upstream_latency_histogram_records_observation(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))

    # `_sum.get()` is incremented by every observe() call on a labeled histogram.
    labeled = UPSTREAM_LATENCY.labels(method="summary")
    sum_before = labeled._sum.get()  # type: ignore[attr-defined]

    app_client.get("/v1/summary", params={"limit": 1, "type": "relay", "search": "uniq"})

    assert labeled._sum.get() > sum_before  # type: ignore[attr-defined]
