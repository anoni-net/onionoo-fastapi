"""ASGI middleware that is neither observability nor routing.

Public surface:
- `VaryOriginMiddleware` — guarantees `Vary: Origin` on every HTTP response
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class VaryOriginMiddleware:
    """Advertise `Vary: Origin` on every response, including where CORS does not apply.

    Starlette's CORSMiddleware adds the header only on the branch it actually
    handles, which is a request carrying an allowed `Origin`. A request with no
    `Origin` returns early before the header is touched, and a rejected origin
    gets no `Access-Control-Allow-Origin` and no `Vary` either. Verified against
    Starlette 1.3: allowed origin yields `Vary: Origin`, the other two yield only
    the `Vary: Accept-Encoding` that GZipMiddleware contributes.

    That is a cache-correctness problem as soon as anything shared sits in front
    of this service (Cloudflare, in our deployment). A response fetched without
    an `Origin` header, by a crawler, an uptime check, or a plain curl, is a
    valid cache entry for the same URL, so a later browser fetch from
    https://anoni.net can be served that stored copy, which carries no
    `Access-Control-Allow-Origin`, and the fetch fails in the browser with no
    matching error on our side. Emitting the header unconditionally keeps the
    per-origin variants apart.

    Mount this as the outermost layer so it observes what CORSMiddleware did and
    only fills the header in when CORS left it out.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_vary(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                present = {v.strip().lower() for v in headers.get("vary", "").split(",")}
                # `Vary: *` already defeats caching, and appending to it would be
                # meaningless. Otherwise add ours without clobbering Accept-Encoding.
                if "origin" not in present and "*" not in present:
                    headers.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, send_with_vary)
