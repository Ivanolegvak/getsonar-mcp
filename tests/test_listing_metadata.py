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
        assert "competitive" not in low, fname
        assert "strategic account" not in low, fname
        assert not re.search(r"\$\d", text), f"{fname}: prices are in euro"
        assert "zefix" not in low, fname
    assert "€0.40" in README and "€2.00" in README
    assert "3 free trial API calls" in README


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
