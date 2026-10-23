"""Streamable-HTTP MCP server entry point — for hosted/remote deployment.

Same tools as the stdio variant, just exposed via Streamable HTTP so a
single hosted instance can serve many customers. Combine with ``oauth.py``
(in the parent directory) once OAuth is fully wired into the request
pipeline so per-user API keys are resolved from the bearer token.

For now this still uses the global ``SONAR_API_KEY`` env var as the
authentication gate. That's correct for self-hosted single-tenant; full
multi-tenant deployment needs the OAuth ``validate_token`` integration.

Run via:
    python -m getsonar_mcp.http_server
or:
    PORT=8080 python -m getsonar_mcp.http_server

The Dockerfile in the parent directory uses the legacy ``server.py``
entry which delegates here.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import __version__
from .tools import SERVER_INSTRUCTIONS, SERVER_NAME, register_tools


def _setup_logging() -> None:
    level = os.environ.get("SONAR_MCP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def build_server(port: int) -> FastMCP:
    """FastMCP instance for the HTTP transport (split out so tests can
    build it without binding a socket)."""
    # host / port are FastMCP settings, not run() arguments, and there is
    # no `description` kwarg: before 0.2.0 shipped, this call passed
    # description= and raised TypeError at startup.
    mcp = FastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=os.environ.get("MCP_HOST", "0.0.0.0"),  # container bind
        port=port,
    )
    register_tools(mcp)
    return mcp


def main() -> None:
    _setup_logging()
    log = logging.getLogger("getsonar-mcp.http")
    port = int(os.environ.get("PORT", "8080"))
    log.info(
        "Starting SONAR MCP server v%s (streamable-http on :%d)", __version__, port
    )
    build_server(port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
