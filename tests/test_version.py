"""The version is declared once in pyproject.toml and read back everywhere else.

Before this, `main.py` hardcoded "1.0.0", `settings.py` hardcoded "0.1" in the
outbound User-Agent, and `uv.lock` still recorded 0.1.0, so a release bump could
(and did) update one and leave the others behind.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.settings import settings

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_package_version_matches_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    assert __version__ == declared, (
        f"installed distribution reports {__version__}, pyproject declares {declared}. "
        "Run `uv sync` after bumping the version."
    )


def test_openapi_version_matches_package() -> None:
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/openapi.json").json()["info"]["version"] == __version__


def test_user_agent_carries_the_current_version() -> None:
    """Onionoo operators identify clients by User-Agent, so a stale one misattributes
    traffic to a version that is no longer running."""
    assert settings.user_agent.startswith(f"onionoo-fastapi/{__version__} ")
    assert "github.com/anoni-net/onionoo-fastapi" in settings.user_agent
