# getsonar-mcp — internal architecture

User-facing setup lives in [README.md](./README.md). This doc is the
internal map: what each module does, the OAuth flow, the two transport
entry points, and which file backs which install path.

> **Audience:** maintainers and anyone debugging a tool dispatch, OAuth
> callback, or Render deployment. New users should not need this — the
> README is the install + config surface.

---

## Module layout

```
mcp-server/
├── README.md              ─ user-facing: install, config, tools (also the PyPI page)
├── ARCHITECTURE.md        ─ this doc
├── DIRECTORIES.md         ─ release + MCP directory listing runbook
├── server.json            ─ official MCP Registry entry (mcp-publisher)
├── manifest.json          ─ MCPB bundle manifest (Smithery, Claude Desktop one-click)
├── smithery.yaml          ─ classic Smithery stdio config
├── glama.json             ─ Glama maintainer claim
├── tests/                 ─ stdio smoke test against a fake API (uv run pytest)
├── scripts/               ─ snapshot-public-mirror.sh (public source mirror)
├── server.py              ─ legacy entry point (Render Dockerfile target)
├── oauth.py               ─ OAuth 2.0 server (Anthropic MCP directory)
├── pyproject.toml         ─ PyPI package metadata (`getsonar-mcp`)
├── requirements.txt       ─ runtime deps for the legacy server.py path
├── Dockerfile             ─ Render deployment image (CMD: python server.py)
└── src/
    └── getsonar_mcp/
        ├── __init__.py        ─ package version + public surface
        ├── __main__.py        ─ stdio transport entry (uvx getsonar-mcp)
        ├── http_server.py     ─ Streamable-HTTP transport entry
        ├── tools.py           ─ MCP tool registrations (the 5 tools)
        └── client.py          ─ HTTP client + response formatters
```

**Two transports, one tool definition.** `tools.py:register_tools()` is
called from BOTH `__main__.py` (stdio) and `http_server.py` (HTTP). The
client (`client.py`) is also shared. So tool behaviour is identical
across `uvx getsonar-mcp`, the hosted Render instance, and direct
Python-module invocation.

---

## Two entry points — when to use which

| Path | File | Transport | Used by |
|---|---|---|---|
| `uvx getsonar-mcp` | `src/getsonar_mcp/__main__.py` | **stdio** | Claude Desktop, Claude Code, Cursor, Windsurf, Continue.dev — local installs |
| `python -m getsonar_mcp.http_server` | `src/getsonar_mcp/http_server.py` | **Streamable HTTP** | Hosted / remote MCP — Anthropic MCP directory listings, web clients |
| `python server.py` | `mcp-server/server.py` | Streamable HTTP (legacy) | Render container — kept for back-compat with the original Dockerfile `CMD ["python", "server.py"]` |

`server.py` is a 25-line shim that imports `http_server.main()` so the
deployed container keeps working without changing the Dockerfile. New
deployments should target `python -m getsonar_mcp.http_server`
directly.

---

## File-by-file

### `src/getsonar_mcp/__init__.py`
Exports `__version__` (read by PyPI installers) and surfaces the
`register_tools` function. Nothing else lives here on purpose — keeps
the import-time surface tiny so tool registration is the only side
effect.

### `src/getsonar_mcp/__main__.py`
Stdio entry. Three responsibilities:
- `_setup_logging()` — log to stderr so MCP-protocol stdout stays
  clean. (Any log line on stdout corrupts the protocol stream.)
- `main()` — instantiate `FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)`
  (both from `tools.py`), call `register_tools()`, call `mcp.run()` which
  blocks on stdio.
- Module-level `if __name__ == "__main__": main()` — what `python -m
  getsonar_mcp` and `uvx getsonar-mcp` resolve to.

### `src/getsonar_mcp/http_server.py`
HTTP entry. `build_server(port)` builds the same FastMCP instance with
`host` / `port` settings (they are constructor settings, not `run()`
arguments); `main()` calls `run(transport="streamable-http")`. Reads
`MCP_HOST` / `PORT` env vars.

### `src/getsonar_mcp/tools.py`
Where the 5 MCP tools are defined and registered (0.2.0):

1. `kyb_findings` — sync, ~30-90s. Structured KYB signals.
2. `kyb_run_submit` — async, returns `run_id`. Full Claude-narrated KYB report.
3. `adverse_media` — sync. Negative news + complaints + bad reviews.
4. `check_report_status` — poll `run_id` until status="completed".
5. `account_balance` — current balance and free-trial calls remaining.

The competitive-intelligence tools were removed in 0.2.0 (CI frozen; see
`SONAR_DECISIONS/ci_sa_freeze.md` in the main repo).

`register_tools()` plus three constants are public: `SERVER_NAME`,
`SERVER_INSTRUCTIONS` (sent to the client at initialize) and
`TOOL_NAMES` (the catalogue the smoke test, `manifest.json` and the
frontend /developers page are checked against).

### `src/getsonar_mcp/client.py`
HTTP layer + response formatters. Six functions:

| Function | Purpose |
|---|---|
| `get_api_base()` | Reads `SONAR_API_BASE` env var, defaults to `https://api.getsonar.report`. |
| `get_default_timeout()` | Reads `SONAR_API_TIMEOUT`, defaults to 120s. |
| `get_api_key_from_env()` | Reads `SONAR_API_KEY`, raises if missing. |
| `call_sonar(method, path, ...)` | The single HTTP entry — every tool routes through here. Async. |
| `format_findings(result, title)` | Markdown response shape for `*_findings` tools. |
| `format_run_started(result, agent_type)` | Markdown response when a run is submitted. |
| `format_run_status(result)` | Markdown response when polling completes. |

These response formatters are why both transports show identical output
to Claude — the Markdown is composed once and served either way.

### `oauth.py`
OAuth 2.0 authorization code flow, required by Anthropic's MCP
directory. The flow:

```
   ┌──────────┐    1. authorize?client_id=...    ┌──────────────┐
   │  Claude  │ ───────────────────────────────► │  oauth.py    │
   │ Desktop/ │                                   │  endpoints   │
   │  Web     │ ◄─── 2. redirect to SONAR ─────── │              │
   └──────────┘                                   └──────────────┘
        │                                                 ▲
        │  3. user logs in at getsonar.report             │
        ▼                                                 │
   ┌──────────────────────────────────────────────────────┘
   │  4. issue_auth_code(api_key, redirect_uri)
   │  5. callback?code=...&state=...
   ▼
   ┌──────────┐    6. token?code=...              ┌──────────────┐
   │  Claude  │ ───────────────────────────────► │  oauth.py    │
   │  client  │ ◄─── 7. {access_token: sonar_at_  │ exchange_..  │
   └──────────┘                                   └──────────────┘
        │
        │  8. tools.py.call_sonar() with Bearer token
        ▼
   ┌────────────────────┐
   │  api.getsonar.     │
   │  report/v1/...     │
   └────────────────────┘
```

Six functions:

| Function | Step in flow |
|---|---|
| `create_authorization_url()` | Step 2 — builds the redirect URL to SONAR's login |
| `issue_auth_code()` | Step 4 — issues a 10-min one-time code after user approves |
| `exchange_code_for_token()` | Step 7 — swaps the code for a 30-day access token |
| `validate_token()` | Per-request — checks Bearer token, returns the SONAR API key |
| `revoke_token()` | Logout — deletes the token from the in-memory store |
| `_sign(data)` | HMAC helper — shared signing key from `OAUTH_SECRET` env |

**State storage:** in-memory only (`_auth_codes` and `_access_tokens`
dicts). Fine for single-instance Render deploys; **needs to move to
Redis or Postgres before any horizontal scale-out.** Tokens last 30
days; auth codes 10 minutes.

**Allowed callbacks** are hard-coded to the four Anthropic-mandated
URLs (localhost:6274 + claude.ai/.com `/api/mcp/auth_callback`). Adding
custom callbacks for self-hosted clients requires editing
`ALLOWED_CALLBACKS` in source.

### `server.py` (legacy)
25-line shim. Adds `src/` to `sys.path` and re-exports
`http_server.main()`. Why it exists: the original `Dockerfile` line
`CMD ["python", "server.py"]` is what the deployed Render image runs.
Removing it would break the live deployment without a coordinated
Dockerfile change. New deployments should bypass it and target
`python -m getsonar_mcp.http_server` directly; keep `server.py` until
the next Render deploy cycle.

---

## Configuration matrix

| Env var | Default | Read by | Purpose |
|---|---|---|---|
| `SONAR_API_KEY` | (required) | `client.py:get_api_key_from_env` | Bearer token for the SONAR API |
| `SONAR_API_BASE` | `https://api.getsonar.report` | `client.py:get_api_base` | Override for staging / self-hosted |
| `SONAR_API_TIMEOUT` | `120` | `client.py:get_default_timeout` | Per-request timeout in seconds |
| `SONAR_MCP_LOG_LEVEL` | `INFO` | `__main__.py:_setup_logging` | `DEBUG` for verbose dispatch |
| `MCP_HOST` | `0.0.0.0` | `http_server.py` | HTTP transport bind address |
| `PORT` | `8080` | `http_server.py` | HTTP transport port |
| `OAUTH_SECRET` | random per-process | `oauth.py:_sign` | HMAC signing key for codes/tokens |
| `SONAR_APP_URL` | `https://getsonar.report` | `oauth.py:create_authorization_url` | OAuth landing page host |

The first four ship with documented defaults (see README); the bottom
four are deployment-internal and only matter when you run the HTTP
transport.

---

## Cross-references

- **User-facing setup:** [README.md](./README.md)
- **Pricing model:** the source of truth for `/run` and `/findings`
  costs is the SONAR pricing page (`/pricing` on getsonar.report).
  Both this doc and `tools.py` reflect that model — €2 / `/run`,
  €0.40 / `/findings`, three free trial API calls granted once at signup.
- **SONAR backend internals:** see `docs/SONAR_TECHNICAL_OVERVIEW.md` (path
  from the repo root). The MCP server is a thin client over the public
  SONAR API; the heavy lifting (OSINT collection, Haiku→Sonnet
  pipeline, Postgres job-queue worker) all lives in the FastAPI
  backend, not here.
- **OAuth config in production:** the four allowed callback URLs are
  fixed by Anthropic's MCP directory requirements; do not edit
  without coordinating with the directory listing.
