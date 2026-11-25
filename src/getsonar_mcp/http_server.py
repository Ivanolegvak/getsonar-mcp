"""Streamable-HTTP MCP server entry point, for self-hosted use.

Same tools as the stdio variant, exposed via Streamable HTTP. Every request
is served with the one global ``SONAR_API_KEY`` from the environment, so
anyone who can reach this endpoint spends that key's balance. The hosted,
multi-user SONAR server is the Cloudflare Worker in ``mcp-remote/`` (OAuth,
one SONAR key per user); this module is for a single user on their own
machine or behind their own gateway.

Network safety (0.3.3, after a private report of the 0.3.2 defaults):

- Binds ``127.0.0.1`` by default (was ``0.0.0.0``). The MCP spec asks local
  servers to bind to localhost only.
- Host and Origin headers are always checked (DNS-rebinding protection):
  loopback names are allowed, plus whatever ``MCP_ALLOWED_HOSTS`` /
  ``MCP_ALLOWED_ORIGINS`` add. A browser page on another site cannot reach
  the server through a rebinding hostname or a cross-site request.
- Binding any other address needs an explicit opt-in
  (``--allow-remote`` or ``SONAR_MCP_ALLOW_REMOTE=1``) AND a bearer token
  (``SONAR_MCP_HTTP_TOKEN``, at least 32 characters); without both the
  server refuses to start. Clients then send
  ``Authorization: Bearer <token>``. The token is optional on loopback but
  enforced whenever it is set.

Run via:
    python -m getsonar_mcp.http_server            # 127.0.0.1:8080
    getsonar-mcp-http --port 9000
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .tools import SERVER_INSTRUCTIONS, SERVER_NAME, register_tools

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
MIN_TOKEN_LEN = 32

LOOPBACK_HOSTS = [
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "127.0.0.1",
    "localhost",
    "[::1]",
]
LOOPBACK_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

_TRUE = {"1", "true", "yes", "on"}


class ConfigError(ValueError):
    """The HTTP server settings are unsafe or invalid; the server must not start."""


@dataclass(frozen=True)
class HttpConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    allow_remote: bool = False
    token: str | None = None
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)

    @property
    def is_loopback(self) -> bool:
        return is_loopback_host(self.host)


def is_loopback_host(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip().strip("[]")).is_loopback
    except ValueError:
        # A hostname other than localhost may resolve to any interface.
        return False


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def load_config(
    argv: Sequence[str] | None = None, env: dict[str, str] | None = None
) -> HttpConfig:
    """Read flags and env vars and refuse unsafe combinations."""
    env = dict(os.environ if env is None else env)
    parser = argparse.ArgumentParser(
        prog="getsonar-mcp-http",
        description="SONAR MCP server over Streamable HTTP (single user, uses SONAR_API_KEY).",
    )
    parser.add_argument("--host", default=env.get("MCP_HOST") or DEFAULT_HOST)
    parser.add_argument(
        "--port", type=int, default=int(env.get("PORT") or DEFAULT_PORT)
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        default=env.get("SONAR_MCP_ALLOW_REMOTE", "").strip().lower() in _TRUE,
        help="allow binding a non-loopback address (also SONAR_MCP_ALLOW_REMOTE=1); "
        "requires SONAR_MCP_HTTP_TOKEN",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    token = (env.get("SONAR_MCP_HTTP_TOKEN") or "").strip() or None
    cfg = HttpConfig(
        host=args.host.strip(),
        port=args.port,
        allow_remote=args.allow_remote,
        token=token,
        allowed_hosts=_split(env.get("MCP_ALLOWED_HOSTS")),
        allowed_origins=_split(env.get("MCP_ALLOWED_ORIGINS")),
    )
    if token is not None and len(token) < MIN_TOKEN_LEN:
        raise ConfigError(
            f"SONAR_MCP_HTTP_TOKEN must be at least {MIN_TOKEN_LEN} characters."
        )
    if not cfg.is_loopback:
        if not cfg.allow_remote:
            raise ConfigError(
                f"Refusing to bind {cfg.host}: anyone who can reach it would spend your "
                "SONAR_API_KEY balance. Bind 127.0.0.1 (the default), or pass "
                "--allow-remote / SONAR_MCP_ALLOW_REMOTE=1 together with SONAR_MCP_HTTP_TOKEN."
            )
        if cfg.token is None:
            raise ConfigError(
                f"Binding {cfg.host} needs SONAR_MCP_HTTP_TOKEN (at least {MIN_TOKEN_LEN} "
                "characters); clients send it as 'Authorization: Bearer <token>'."
            )
    return cfg


def transport_security(cfg: HttpConfig) -> TransportSecuritySettings:
    """Host / Origin allowlists, always on (FastMCP leaves them off for 0.0.0.0)."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=LOOPBACK_HOSTS + cfg.allowed_hosts,
        allowed_origins=LOOPBACK_ORIGINS + cfg.allowed_origins,
    )


class BearerTokenMiddleware:
    """Reject HTTP requests without ``Authorization: Bearer <token>``.

    The auth scheme is case-insensitive (RFC 9110 section 11.1), the token
    is compared in constant time, and neither is logged or echoed.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            got = b""
            for name, value in scope.get("headers", []):
                if name == b"authorization":
                    got = value
                    break
            scheme, _, presented = got.strip().partition(b" ")
            ok = scheme.lower() == b"bearer" and hmac.compare_digest(
                presented.strip(), self._expected
            )
            if not ok:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"text/plain; charset=utf-8"),
                            (b"www-authenticate", b'Bearer realm="getsonar-mcp"'),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)


def _setup_logging() -> None:
    level = os.environ.get("SONAR_MCP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def build_server(cfg: HttpConfig | int | None = None) -> FastMCP:
    """FastMCP instance for the HTTP transport (split out so tests can
    build it without binding a socket). An int is taken as the port, for
    callers of the 0.3.2 signature ``build_server(port)``."""
    if cfg is None:
        cfg = HttpConfig()
    elif isinstance(cfg, int):
        cfg = HttpConfig(port=cfg)
    # host / port are FastMCP settings, not run() arguments, and there is
    # no `description` kwarg: before 0.2.0 shipped, this call passed
    # description= and raised TypeError at startup.
    mcp = FastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=cfg.host,
        port=cfg.port,
        transport_security=transport_security(cfg),
    )
    register_tools(mcp)
    return mcp


def build_app(cfg: HttpConfig) -> ASGIApp:
    """The ASGI app that ``main`` serves: Streamable HTTP plus the token gate."""
    app: ASGIApp = build_server(cfg).streamable_http_app()
    if cfg.token:
        app = BearerTokenMiddleware(app, cfg.token)
    return app


def main(argv: Sequence[str] | None = None) -> None:
    _setup_logging()
    log = logging.getLogger("getsonar-mcp.http")
    try:
        cfg = load_config(argv)
    except ConfigError as e:
        log.error("%s", e)
        raise SystemExit(2) from None

    if not cfg.is_loopback:
        log.warning(
            "Listening on %s:%d, beyond this machine. Every client holding the bearer "
            "token spends this server's SONAR_API_KEY balance; put it behind TLS.",
            cfg.host,
            cfg.port,
        )
    log.info(
        "Starting SONAR MCP server v%s (streamable-http on %s:%d, bearer token %s)",
        __version__,
        cfg.host,
        cfg.port,
        "required" if cfg.token else "off",
    )

    import uvicorn  # a dependency of mcp

    uvicorn.run(build_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
