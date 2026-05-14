"""Shared fixtures and mock Onionoo response builders for the test suite.

All tests in this directory must run without network access. Use the `mocked_app`
fixture (or `respx_mock` directly) to stub the upstream Onionoo API.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import settings


def make_summary_envelope(
    *,
    relays: list[dict[str, Any]] | None = None,
    bridges: list[dict[str, Any]] | None = None,
    relays_published: str = "2026-05-15 12:00:00",
    bridges_published: str = "2026-05-15 12:00:00",
    relays_skipped: int | None = None,
    relays_truncated: int | None = None,
) -> dict[str, Any]:
    """Build a minimal Onionoo /summary envelope for tests."""
    envelope: dict[str, Any] = {
        "version": "9.0",
        "relays_published": relays_published,
        "bridges_published": bridges_published,
        "relays": relays if relays is not None else [],
        "bridges": bridges if bridges is not None else [],
    }
    if relays_skipped is not None:
        envelope["relays_skipped"] = relays_skipped
    if relays_truncated is not None:
        envelope["relays_truncated"] = relays_truncated
    return envelope


def relay(n: str, f: str, a: list[str] | None = None, r: bool = True) -> dict[str, Any]:
    """Build an Onionoo summary relay (short-key form)."""
    return {"n": n, "f": f, "a": a or [f"10.0.0.{int(f[:2], 16) % 250 + 1}"], "r": r}


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a known base URL so respx routes line up with httpx calls."""
    monkeypatch.setattr(settings, "onionoo_base_url", "https://onionoo.torproject.org")


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(
        base_url="https://onionoo.torproject.org",
        assert_all_called=False,
    ) as router:
        yield router


@pytest.fixture
def app_client(respx_mock: respx.MockRouter) -> Iterator[TestClient]:  # noqa: ARG001
    """TestClient with respx mocking upstream Onionoo. Lifespan runs so client is created."""
    app = create_app()
    with TestClient(app) as c:
        yield c
