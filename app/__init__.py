"""onionoo-fastapi package."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth for the version: whatever `pyproject.toml` declares,
    # read back off the installed distribution. Hardcoding it separately in
    # `main.py` and `settings.py` is what let them drift apart before (the FastAPI
    # app said 1.0.0 while the upstream User-Agent still said 0.1).
    __version__ = version("onionoo-fastapi")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare checkout
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
