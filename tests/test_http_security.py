"""Network safety of the Streamable-HTTP transport (0.3.3).

0.3.2 bound 0.0.0.0 with no Host / Origin checks and no auth, so anyone on
the LAN, or a web page through DNS rebinding, could call paid tools with the
user's SONAR_API_KEY. These tests pin the safe defaults. No socket is bound
and no SONAR API call is made: only ``initialize`` is sent.
"""

from __future__ import annotations

import pytest
from getsonar_mcp.http_server import (
    DEFAULT_HOST,
    ConfigError,
    HttpConfig,
    build_app,
    build_server,
    is_loopback_host,
    load_config,
)
from starlette.testclient import TestClient

TOKEN = "t" * 40
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


def _post(
    cfg: HttpConfig, base_url: str = "http://127.0.0.1:8080", **headers: str
) -> int:
    with TestClient(build_app(cfg), base_url=base_url) as c:
        return c.post("/mcp", json=INIT, headers={**HEADERS, **headers}).status_code


# --- bind address and opt-in ---------------------------------------------


def test_default_bind_is_loopback() -> None:
    cfg = load_config([], env={})
    assert cfg.host == DEFAULT_HOST == "127.0.0.1"
    assert build_server(cfg).settings.host == "127.0.0.1"
    # The 0.3.2 signature build_server(port) still works and is loopback.
    assert build_server(9000).settings.host == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com"])
def test_public_bind_refused_without_opt_in(host: str) -> None:
    with pytest.raises(ConfigError, match="Refusing to bind"):
        load_config([], env={"MCP_HOST": host, "SONAR_MCP_HTTP_TOKEN": TOKEN})


def test_public_bind_refused_without_token() -> None:
    with pytest.raises(ConfigError, match="SONAR_MCP_HTTP_TOKEN"):
        load_config(["--host", "0.0.0.0", "--allow-remote"], env={})


def test_public_bind_with_opt_in_and_token() -> None:
    cfg = load_config(
        [],
        env={
            "MCP_HOST": "0.0.0.0",
            "SONAR_MCP_ALLOW_REMOTE": "1",
            "SONAR_MCP_HTTP_TOKEN": TOKEN,
        },
    )
    assert cfg.host == "0.0.0.0" and cfg.allow_remote and cfg.token == TOKEN


def test_short_token_refused() -> None:
    with pytest.raises(ConfigError, match="at least"):
        load_config([], env={"SONAR_MCP_HTTP_TOKEN": "short"})


@pytest.mark.parametrize(
    ("host", "loop"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        ("127.0.0.2", True),
        ("0.0.0.0", False),
        ("::", False),
        ("10.0.0.5", False),
        ("myhost.local", False),
    ],
)
def test_is_loopback_host(host: str, loop: bool) -> None:
    assert is_loopback_host(host) is loop


def test_main_exits_on_unsafe_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    from getsonar_mcp import http_server

    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("SONAR_MCP_ALLOW_REMOTE", raising=False)
    with pytest.raises(SystemExit) as exc:
        http_server.main([])
    assert exc.value.code == 2


# --- Host / Origin (DNS rebinding) ---------------------------------------


def test_loopback_request_accepted() -> None:
    assert _post(HttpConfig()) == 200
    assert (
        _post(
            HttpConfig(),
            base_url="http://localhost:8080",
            Origin="http://localhost:3000",
        )
        == 200
    )


def test_rebinding_host_rejected() -> None:
    # A page on attacker.example re-resolved to 127.0.0.1 sends its own Host.
    assert _post(HttpConfig(), base_url="http://attacker.example") == 421


@pytest.mark.parametrize("method", ["GET", "DELETE"])
@pytest.mark.parametrize("with_session", [True, False])
def test_rebinding_host_rejected_on_get_and_delete(
    method: str, with_session: bool
) -> None:
    # The SSE stream (GET) and session close (DELETE) are checked too, also
    # for a real, live session id (an unknown id would 404 before the check).
    with TestClient(build_app(HttpConfig()), base_url="http://127.0.0.1:8080") as c:
        init = c.post("/mcp", json=INIT, headers=HEADERS)
        assert init.status_code == 200
        headers = {
            "Accept": "text/event-stream",
            "Host": "attacker.example",
            "Mcp-Protocol-Version": "2025-06-18",
        }
        if with_session:
            headers["Mcp-Session-Id"] = init.headers["mcp-session-id"]
        r = c.request(method, "/mcp", headers=headers)
    assert r.status_code == 421


def test_cross_site_origin_rejected() -> None:
    assert _post(HttpConfig(), Origin="https://attacker.example") == 403


def test_extra_allowed_host_and_origin() -> None:
    cfg = load_config(
        [],
        env={
            "MCP_ALLOWED_HOSTS": "mcp.internal:*",
            "MCP_ALLOWED_ORIGINS": "https://app.internal",
        },
    )
    assert (
        _post(cfg, base_url="http://mcp.internal:8080", Origin="https://app.internal")
        == 200
    )
    assert (
        _post(cfg, base_url="http://mcp.internal:8080", Origin="https://other.internal")
        == 403
    )


def test_public_bind_still_checks_host() -> None:
    cfg = HttpConfig(host="0.0.0.0", allow_remote=True, token=TOKEN)
    assert build_server(cfg).settings.transport_security.enable_dns_rebinding_protection
    assert (
        _post(cfg, base_url="http://192.168.1.10:8080", Authorization=f"Bearer {TOKEN}")
        == 421
    )


# --- bearer token ----------------------------------------------------------


def test_token_required_when_set() -> None:
    cfg = HttpConfig(token=TOKEN)
    assert _post(cfg) == 401
    assert _post(cfg, Authorization="Bearer wrong") == 401
    assert _post(cfg, Authorization=f"Bearer {TOKEN}") == 200
    assert _post(cfg, Authorization=f"bearer {TOKEN}") == 200
    assert _post(cfg, Authorization=f"BEARER {TOKEN}") == 200
    assert _post(cfg, Authorization=f"Basic {TOKEN}") == 401
    assert _post(cfg, Authorization=TOKEN) == 401


def test_unauthorized_response_does_not_echo_token() -> None:
    cfg = HttpConfig(token=TOKEN)
    with TestClient(build_app(cfg), base_url="http://127.0.0.1:8080") as c:
        r = c.post(
            "/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {TOKEN}x"}
        )
    assert r.status_code == 401
    assert TOKEN not in r.text and TOKEN not in str(r.headers)
