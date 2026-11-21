"""Directory metadata stays consistent with the code and the copy rules
(DIRECTORIES.md "Copy rules for every listing")."""

from __future__ import annotations

import json
import re
from pathlib import Path

from getsonar_mcp.tools import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
SERVER = json.loads((ROOT / "server.json").read_text())
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
PUBLIC_TEXTS = {
    "README.md": README,
    "server.json": json.dumps(SERVER),
    "manifest.json": json.dumps(MANIFEST),
    "smithery.yaml": (ROOT / "smithery.yaml").read_text(),
    "pyproject.toml": (ROOT / "pyproject.toml").read_text(),
}


def test_readme_proves_registry_ownership() -> None:
    # The MCP Registry looks for this exact comment in the PyPI README.
    assert README.startswith(f"<!-- mcp-name: {SERVER['name']} -->")


def test_readme_documents_every_tool() -> None:
    for name in TOOL_NAMES:
        assert f"### `{name}`" in README, name
        assert f"| `{name}` |" in README, name


def test_readme_has_install_for_each_client() -> None:
    for client in ("Claude Desktop", "Claude Code", "Cursor", "Windsurf"):
        assert f"### {client}" in README, client
    assert "SONAR_API_KEY" in README


def test_pricing_and_scope_copy() -> None:
    for fname, text in PUBLIC_TEXTS.items():
        low = text.lower()
        assert "lifetime" not in low, fname
        assert not re.search(r"\b(3|three) free", low), fname
        assert "competitive" not in low, fname
        assert "strategic account" not in low, fname
        assert not re.search(r"\$\d", text), f"{fname}: prices are in euro"
        assert "zefix" not in low, fname
    assert "€0.50" in README and "€6.00" in README
    assert "first API call is free" in README


def test_server_json_limits() -> None:
    # Registry schema 2025-12-11: description and title max 100 chars.
    assert len(SERVER["description"]) <= 100
    assert len(SERVER["title"]) <= 100
    env = {e["name"]: e for e in SERVER["packages"][0]["environmentVariables"]}
    assert env["SONAR_API_KEY"]["isRequired"] and env["SONAR_API_KEY"]["isSecret"]
    assert SERVER["websiteUrl"] == "https://getsonar.report/integrations"


def test_mcp_dependency_is_capped_below_2() -> None:
    # mcp 2.x removed mcp.server.fastmcp; an uncapped pin breaks
    # `uvx getsonar-mcp` for every new install.
    pyproject = PUBLIC_TEXTS["pyproject.toml"]
    assert re.search(r'"mcp>=[0-9.]+,<2"', pyproject)
    assert "mcp>=1.10.0,<2" in (ROOT / "requirements.txt").read_text()


def test_desktop_and_plugin_listing_requirements() -> None:
    # Anthropic directory rules for local servers (claude.com/docs,
    # connectors/building/submission): privacy policy in manifest.json and a
    # "Privacy Policy" section in the README; the key is a sensitive setting.
    assert MANIFEST["manifest_version"] == "0.4"
    assert MANIFEST["privacy_policies"] == ["https://getsonar.report/privacy"]
    assert "## Privacy Policy" in README
    key = MANIFEST["user_config"]["sonar_api_key"]
    assert key["sensitive"] and key["required"]
    assert (
        MANIFEST["server"]["mcp_config"]["env"]["SONAR_API_KEY"]
        == "${user_config.sonar_api_key}"
    )
    assert (ROOT / MANIFEST["icon"]).is_file()
    for t in MANIFEST["tools"]:
        assert "EUR" in t["description"] or "free" in t["description"], t["name"]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["privacyPolicyUrl"] == "https://getsonar.report/privacy"
    assert plugin["userConfig"]["sonar_api_key"]["sensitive"] is True
    assert (ROOT / plugin["icon"]).is_file()
    mcp_json = json.loads((ROOT / ".mcp.json").read_text())
    server = mcp_json["mcpServers"]["sonar"]
    assert server["command"] == "uvx"
    # The directory blocks unpinned launchers: exact == pin only.
    assert re.fullmatch(r"getsonar-mcp==\d+\.\d+\.\d+", server["args"][0])
    assert server["env"]["SONAR_API_KEY"] == "${user_config.sonar_api_key}"
