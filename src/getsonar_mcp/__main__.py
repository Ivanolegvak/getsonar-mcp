"""Stdio MCP entry point — what ``uvx getsonar-mcp`` and
``python -m getsonar_mcp`` invoke.

The default transport for local install. Each customer runs the server
on their own machine; the MCP client (Claude Desktop / Code / Cursor)
spawns this process and talks to it over stdin/stdout. The customer's
``SONAR_API_KEY`` env var holds their API key — see the README for
client-specific config snippets.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import __version__
from .tools import SERVER_INSTRUCTIONS, SERVER_NAME, register_tools


def _setup_logging() -> None:
    """Log to stderr so MCP-protocol stdout stays clean."""
    level = os.environ.get("SONAR_MCP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main() -> None:
    _setup_logging()
    log = logging.getLogger("getsonar-mcp")
    log.info("Starting SONAR MCP server v%s (stdio transport)", __version__)

    # FastMCP has no `description` kwarg (removed in mcp v1.x). The
    # server-level blurb goes in `instructions`, which clients surface to
    # the model at initialize time; tool-level descriptions live on each
    # register_tools call.
    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    register_tools(mcp)

    # FastMCP.run() defaults to stdio transport when called with no args
    mcp.run()


if __name__ == "__main__":
    main()
