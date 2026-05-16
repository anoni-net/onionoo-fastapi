# onionoo-fastapi

FastAPI-based **semantic/OpenAPI proxy** for the Tor **Onionoo** API.

- GitHub: <https://github.com/anoni-net/onionoo-fastapi>
- Upstream data source: <https://onionoo.torproject.org>
- This service **does not store Onionoo data**, it only forwards requests and transforms responses.
- Primary motivation: Onionoo has a solid spec, but **no OpenAPI**; this service provides a friendly schema **for tooling/AI agents**.

Reference spec: [Tor Metrics – Onionoo](https://metrics.torproject.org/onionoo.html)

## Hosted instance

- Service: `https://onionoo.anoni.net`
- Swagger UI: `https://onionoo.anoni.net/docs`

## Releases

Tagged releases (`vX.Y.Z`) trigger two GitHub Actions workflows:

- `.github/workflows/release.yml` — builds the wheel/sdist and publishes to
  PyPI via Trusted Publishing. Register this workflow as a trusted publisher
  on the `onionoo-fastapi` PyPI project once before the first tag.
- `.github/workflows/docker.yml` — builds a multi-arch image and pushes to
  `ghcr.io/<owner>/onionoo-fastapi`. Uses the default `GITHUB_TOKEN`.

Cut a release with:

```bash
git tag -a v0.2.0 -m "Release 0.2.0"
git push origin v0.2.0
```

## License

MIT. See `LICENSE`.

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)

## Install

```bash
git clone https://github.com/anoni-net/onionoo-fastapi
cd onionoo-fastapi
uv sync
```

Or if you already have the source:

```bash
cd onionoo-fastapi
uv sync
```

## Run

```bash
fastapi run app.main:app --reload --host 0.0.0.0 --port 8000
```
**Note:** `fastapi run` requires FastAPI version 0.110.0 or newer.

OpenAPI docs:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Test

```bash
uv sync --extra dev
uv run pytest
```

## Docker

Build and run with Docker Compose:

```bash
docker compose up -d --build
```

If port 8000 is already in use, override host port (example: 8001):

```bash
HOST_PORT=8001 docker compose up -d --build
```

Stop:

```bash
docker compose down
```

Configuration via environment variables (example):

```bash
ONIONOO_BASE_URL=https://onionoo.torproject.org HOST_PORT=8001 docker compose up -d --build
```

## API

This service exposes semantic endpoints under `/v1/*`:

- `GET /v1/summary`
- `GET /v1/details`
- `GET /v1/bandwidth`
- `GET /v1/weights`
- `GET /v1/clients`
- `GET /v1/uptime`

Aggregate (server-side group-by, sorted by relay count):

- `GET /v1/aggregate/countries` — buckets by two-letter country code
- `GET /v1/aggregate/as` — buckets by autonomous system number
- `GET /v1/aggregate/flags` — buckets by directory-authority flag (a relay can fall into multiple flag buckets)

Plus:

- `GET /healthz` — static liveness
- `GET /healthz/ready` — verifies upstream reachability (cached)
- `GET /metrics` — Prometheus format

### Example requests

```bash
# Summary (semantic keys; upstream short keys are transformed)
curl -s 'http://localhost:8000/v1/summary?limit=1' | jq .

# Details (supports Onionoo query parameters + details-only `fields`)
curl -s 'http://localhost:8000/v1/details?limit=1&search=moria&fields=nickname,fingerprint' | jq .

# Bandwidth
curl -s 'http://localhost:8000/v1/bandwidth?limit=1&search=moria' | jq .

# Weights (relays only)
curl -s 'http://localhost:8000/v1/weights?limit=1&search=moria' | jq .

# Clients (bridges only)
curl -s 'http://localhost:8000/v1/clients?limit=1' | jq .

# Uptime
curl -s 'http://localhost:8000/v1/uptime?limit=1&search=moria' | jq .
```

### Semantic field mapping notes

- `/v1/summary` transforms Onionoo short keys:
  - relay: `n,f,a,r` → `nickname,fingerprint,addresses,running`
  - bridge: `n,h,r` → `nickname,hashed_fingerprint,running`
- For some bridge documents (`/bandwidth`, `/clients`, `/uptime`), Onionoo uses the key name `fingerprint` even though the value is a **hashed fingerprint**; this API exposes that as `hashed_fingerprint`.

### Caching / 304 behavior

If the client includes `If-Modified-Since`, it will be forwarded upstream. If Onionoo replies with `304`, this service will reply `304` too.

### Configuration

Upstream / cache:

- `ONIONOO_BASE_URL` (default: `https://onionoo.torproject.org`)
- `ONIONOO_TIMEOUT_SECONDS` (default: `30`)
- `DEFAULT_LIMIT` (default: `100`)
- `MAX_LIMIT` (default: `200`)
- `USER_AGENT`
- `CACHE_MAXSIZE` (default: `1024`)
- `CACHE_DEFAULT_TTL_SECONDS` (default: `300`)
- `UPSTREAM_RETRY_ATTEMPTS` (default: `2`)

Observability / production hardening:

- `LOG_LEVEL` (default: `INFO`)
- `LOG_FORMAT` (`json` or `console`, default `json`)
- `METRICS_ENABLED` (default: `true`) — exposes `/metrics` in Prometheus format
- `CORS_ALLOWED_ORIGINS` (default: empty, CORS disabled). Example: `["https://example.com"]`
- `RATE_LIMIT_ENABLED` (default: `false`)
- `RATE_LIMIT_PER_MINUTE` (default: `120`)
- `HEALTHZ_READY_CACHE_SECONDS` (default: `30`)

### Resource sizing

A single-worker container (the default `uvicorn` CMD in the Dockerfile) measured on Alpine 3.23 / Python 3.14 / aarch64 against the real Onionoo upstream:

| Phase | RSS | Notes |
|---|---:|---|
| **Idle** (just after start) | ~75 MiB | Python + FastAPI + Pydantic + httpx + fastapi-mcp + structlog + Prometheus instrumentator loaded; cache empty. |
| **Typical agent traffic** | ~90 MiB | After ~15 mixed `/v1/*` calls (details + aggregates), only a handful of distinct upstream payloads cached. |
| **Cache near saturation** | ~180 MiB | After 200 distinct `/v1/details` queries with `fields=` projection; cache holds ~200 entries. |

From these measurements, each cached entry costs **~0.5 MiB on average** when callers use the `fields=` projection. With the default `CACHE_MAXSIZE=1024` that yields a **~500 MiB upper bound** under realistic agent traffic.

If you expect callers to hit `/v1/details` **without** `fields=`, a single response can be several MiB (Onionoo returns ~10k full relay objects). A fully saturated cache of unfiltered details would then sit in the **1–5 GiB** range — bound it by tuning `CACHE_MAXSIZE` down.

Suggested memory limits for `docker run --memory` / Kubernetes requests:

| Deployment shape | Memory request | Memory limit |
|---|---:|---:|
| Personal / single-agent test | 128 MiB | 256 MiB |
| Hosted instance, mostly cached requests | 256 MiB | 512 MiB |
| Public instance, agents may issue unfiltered `/details` | 512 MiB | 1–2 GiB |

CPU is light — a single worker handles 10s of QPS comfortably; scale with replicas if you need more throughput. (`uvicorn ... --workers N` is also an option, but each worker keeps its own in-memory cache; horizontal scaling via separate containers is usually a better fit.)

### Health checks

- `GET /healthz` — static liveness probe, never hits upstream.
- `GET /healthz/ready` — pings Onionoo (`summary?limit=1`); 200 when reachable, 503 otherwise. Result is cached for `HEALTHZ_READY_CACHE_SECONDS`.

### Request tracing

Every request is assigned an `X-Request-ID`. Clients may supply one to correlate across systems; the same value is echoed back on the response and bound into every log record produced during the request.

### Metrics

`/metrics` exposes Prometheus-format counters / histograms, including:

- `onionoo_cache_hits_total`, `onionoo_cache_misses_total`
- `onionoo_upstream_seconds{method=...}` (histogram)
- `onionoo_upstream_errors_total{method=..., status=...}`
- Standard `http_request_duration_seconds` from the FastAPI instrumentator

### Raw passthrough

For large payloads (`/v1/details`), pass `?raw=true` to skip Pydantic re-validation and forward the upstream JSON verbatim. Trade-off: raw mode does **not** apply semantic key remapping (e.g. on `/v1/summary` you'll see `n,f,a,r` rather than `nickname,fingerprint,addresses,running`) and **no `_meta` block is injected**.

### Response metadata (`_meta`)

Non-raw responses on `/v1/*` include a proxy-injected `_meta` block at the top of the envelope:

```json
{
  "_meta": {
    "cache_age_seconds": 12.345,
    "upstream_last_modified": "Thu, 15 May 2026 12:00:00 GMT"
  },
  "version": "9.0",
  ...
}
```

`cache_age_seconds = 0.0` means the response was just fetched from Onionoo. A non-zero value means the proxy served it from its in-memory cache.

### Trimming payloads with `fields=`

All `/v1/*` endpoints accept `?fields=a,b,c`. On `/summary` and `/details` Onionoo applies the projection at the upstream level; on history endpoints (bandwidth, weights, clients, uptime) Onionoo applies it where supported. Using it on large queries can shrink LLM input by an order of magnitude.

## Use as an MCP server

This project ships an [MCP](https://modelcontextprotocol.io) server with two
transports — pick whichever fits your client.

### Tools

**Task-oriented (recommended for agents)**

- `find_relay(query)` — free-form lookup; auto-detects fingerprint, AS, IP, or nickname
- `get_relay_health(fingerprint)` — composite snapshot (details + uptime + bandwidth)
- `top_relays_by_bandwidth(country?, flag?, limit)` — top-N by consensus weight
- `compare_relays(fingerprints)` — parallel side-by-side details
- `country_summary(country)` — running relay count, total bandwidth, flag distribution

**Low-level pass-through (raw Onionoo endpoints)**

- `onionoo_summary`, `onionoo_details`, `onionoo_bandwidth`, `onionoo_weights`,
  `onionoo_clients`, `onionoo_uptime` — each takes a `params` dict matching the
  [Onionoo query spec](https://metrics.torproject.org/onionoo.html).

**Aggregates**

- `aggregate_relays(group_by="country"|"as"|"flag", running=True, top=N)` — server-side group-by, sorted by relay count.

> Streamable HTTP `/mcp` exposes the six low-level endpoints (`get_summary` …
> `get_uptime`) plus the three aggregate endpoints (`aggregate_countries`,
> `aggregate_as`, `aggregate_flags`). The task-oriented tools and the unified
> `aggregate_relays` live in the stdio server. Both transports can run side by side.

### Streamable HTTP transport (recommended for hosted use)

Run the FastAPI app — `/mcp` is mounted automatically.

Inspect with MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP
# URL: http://localhost:8000/mcp
```

Claude Desktop / Cursor:

```json
{
  "mcpServers": {
    "onionoo": {
      "type": "http",
      "url": "https://onionoo.anoni.net/mcp"
    }
  }
}
```

### stdio transport (recommended for local agents)

`uv sync` installs an `onionoo-mcp` console script:

```bash
onionoo-mcp
```

Claude Desktop / Cursor:

```json
{
  "mcpServers": {
    "onionoo": {
      "command": "uvx",
      "args": ["--from", "/path/to/onionoo-fastapi", "onionoo-mcp"]
    }
  }
}
```

Or, if the repo is checked out and you have `uv`:

```json
{
  "mcpServers": {
    "onionoo": {
      "command": "uv",
      "args": ["--directory", "/path/to/onionoo-fastapi", "run", "onionoo-mcp"]
    }
  }
}
```

