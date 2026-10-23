"""SONAR KYB MCP server.

Exposes SONAR's KYB due diligence and adverse media screening tools to
MCP-compatible AI clients (Claude Desktop, Claude Code, Cursor, etc.).
Competitive intelligence tools were removed in 0.2.0 (product frozen).

Two transports from one codebase:

  - **stdio** (default, for local install) — ``python -m getsonar_mcp`` or
    ``uvx getsonar-mcp``. Each customer runs the server locally, configures
    their API key via the ``SONAR_API_KEY`` env var, and adds the command
    to their MCP client config. No infrastructure required.

  - **streamable-http** (remote/hosted) — ``python -m getsonar_mcp.http_server``
    starts an HTTP MCP endpoint suitable for Render / Cloud Run. Customers
    paste a single URL into their MCP client config; OAuth handles auth.
    See ``http_server.py`` and ``oauth.py`` for the deployment story.
"""

__version__ = "0.2.0"
