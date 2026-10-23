"""Smoke test: start ``python -m getsonar_mcp`` over stdio against a fake
SONAR API, list the tools and call two of them.

The fake API is a stdlib HTTP server on 127.0.0.1; the MCP subprocess is
pointed at it with ``SONAR_API_BASE``. Nothing leaves the machine and no
real key is used.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anyio
import pytest
from getsonar_mcp import __version__
from getsonar_mcp.tools import SERVER_NAME, TOOL_NAMES
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FAKE_KEY = "sk-sonar-test-not-a-real-key"
PKG_SRC = Path(__file__).resolve().parents[1] / "src"

FINDINGS = {
    "request_id": "req_1",
    "agent": "kyb-diligence",
    "company": {"name": "Acme Widgets Ltd", "domain": "acme.example"},
    "status": "completed",
    "fields": {
        "registry": {
            "findings": [
                {
                    "value": "ACME WIDGETS LTD (12345678), active",
                    "detail": "Incorporated 2015-03-02, private limited company",
                    "sources": [
                        {
                            "url": "https://find-and-update.company-information.service.gov.uk/company/12345678"
                        }
                    ],
                }
            ],
            "confidence": "HIGH",
        }
    },
    "sources_checked": 42,
    "fields_found": ["registry"],
    "fields_not_found": [],
    "field_status": {"registry": "found", "sanctions": "checked_clean"},
    "processing_time_ms": 1234,
}

USAGE = {
    "period": "2026-10",
    "total_requests": 1,
    "free_trial_remaining": 1,
    "balance_cents": 500,
    "by_endpoint": {"findings": 1},
}


class _FakeSonar(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, str | None]] = []

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.seen.append(("POST", self.path, self.headers.get("X-API-Key")))
        if self.path == "/v1/agents/kyb-diligence/findings":
            self._send(200, FINDINGS)
        else:
            self._send(
                404, {"detail": {"error": {"code": "NOT_FOUND", "message": "nope"}}}
            )

    def do_GET(self) -> None:
        self.seen.append(("GET", self.path, self.headers.get("X-API-Key")))
        if self.path == "/v1/usage":
            self._send(200, USAGE)
        else:
            self._send(
                404, {"detail": {"error": {"code": "NOT_FOUND", "message": "nope"}}}
            )

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def fake_api() -> Iterator[str]:
    _FakeSonar.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSonar)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _params(api_base: str, api_key: str | None) -> StdioServerParameters:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(PKG_SRC),
        "SONAR_API_BASE": api_base,
        "SONAR_MCP_LOG_LEVEL": "WARNING",
    }
    if api_key is not None:
        env["SONAR_API_KEY"] = api_key
    return StdioServerParameters(
        command=sys.executable, args=["-m", "getsonar_mcp"], env=env
    )


def _text(result) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)


def test_stdio_lists_tools_and_calls_fake_api(fake_api: str) -> None:
    async def run() -> None:
        with anyio.fail_after(60):
            async with stdio_client(_params(fake_api, FAKE_KEY)) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    assert init.serverInfo.name == SERVER_NAME
                    assert init.serverInfo.version == __version__
                    assert (
                        init.instructions
                        and "not a regulated AML/KYC provider" in init.instructions
                    )

                    tools = (await session.list_tools()).tools
                    assert tuple(t.name for t in tools) == TOOL_NAMES
                    for t in tools:
                        assert t.description, t.name
                        # No CI-era tool or wording leaks into the catalogue.
                        assert "competitive" not in (t.description or "").lower(), (
                            t.name
                        )
                        assert "$" not in (t.description or ""), t.name

                    by_name = {t.name: t for t in tools}
                    assert by_name["kyb_findings"].inputSchema["required"] == [
                        "company_name"
                    ]

                    out = _text(
                        await session.call_tool(
                            "kyb_findings",
                            {
                                "company_name": "Acme Widgets Ltd",
                                "website": "https://acme.example",
                            },
                        )
                    )
                    assert "KYB Quick Lookup: Acme Widgets Ltd" in out
                    assert "ACME WIDGETS LTD (12345678), active" in out
                    assert "**Checked, clean**" in out

                    bal = _text(await session.call_tool("account_balance", {}))
                    assert "Free trial calls remaining: **1**" in bal
                    assert "€5.00" in bal

    anyio.run(run)

    assert ("POST", "/v1/agents/kyb-diligence/findings", FAKE_KEY) in _FakeSonar.seen
    assert ("GET", "/v1/usage", FAKE_KEY) in _FakeSonar.seen


def test_missing_api_key_is_a_tool_error_not_a_crash(fake_api: str) -> None:
    async def run() -> None:
        with anyio.fail_after(60):
            async with stdio_client(_params(fake_api, None)) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    # Listing tools must work without a key (directories
                    # such as Glama inspect the server this way).
                    assert len((await session.list_tools()).tools) == len(TOOL_NAMES)
                    res = await session.call_tool("account_balance", {})
                    assert res.isError
                    assert "SONAR_API_KEY" in _text(res)

    anyio.run(run)
    assert _FakeSonar.seen == []


def test_http_transport_builds() -> None:
    from getsonar_mcp.http_server import build_server

    mcp = build_server(8123)
    assert mcp.settings.port == 8123
    assert mcp.name == SERVER_NAME


def test_version_is_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    server = json.loads((root / "server.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    pyproject = (root / "pyproject.toml").read_text()
    assert f'version = "{__version__}"' in pyproject
    assert server["version"] == __version__
    assert all(p["version"] == __version__ for p in server["packages"])
    assert manifest["version"] == __version__
    assert f"getsonar-mcp@{__version__}" in manifest["server"]["mcp_config"]["args"]
    assert [t["name"] for t in manifest["tools"]] == list(TOOL_NAMES)
