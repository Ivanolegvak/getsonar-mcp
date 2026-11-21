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


def test_desktop_bundle_listing_requirements() -> None:
    # Anthropic rules for the local MCPB bundle (claude.com/docs,
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


REMOTE_MCP_URL = "https://sonar-mcp.sonar-mcp-remote.workers.dev/mcp"


def test_plugin_uses_the_hosted_server() -> None:
    # Claude directory "Plugin bundle" rules for an unverified organization
    # (claude.com/docs/plugins/pre-submission-checklist): remote MCP servers
    # only, an https URL, no credential in the plugin. OAuth runs in the
    # client, so the plugin asks for no key and declares no userConfig.
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert "userConfig" not in plugin
    assert (ROOT / plugin["icon"]).is_file()
    # Directory listing fields are top-level keys (code.claude.com plugins
    # manifest-reference, "Directory listing fields"); `metadata` is
    # free-form and the directory does not read it.
    assert "metadata" not in plugin
    for key in (
        "documentationUrl",
        "supportUrl",
        "privacyPolicyUrl",
        "termsOfServiceUrl",
    ):
        assert plugin[key].startswith("https://"), key
    assert plugin["privacyPolicyUrl"] == "https://getsonar.report/privacy"
    mcp_text = (ROOT / ".mcp.json").read_text()
    assert "user_config" not in mcp_text and "sk-sonar" not in mcp_text
    mcp_json = json.loads(mcp_text)
    assert mcp_json == {
        "mcpServers": {"sonar": {"type": "http", "url": REMOTE_MCP_URL}}
    }
    assert "### Claude plugin" in README and REMOTE_MCP_URL in README


def test_plugin_icon_has_no_metadata_chunks() -> None:
    # The portal flagged the old icon; it stays a bare 512x512 PNG (IHDR,
    # IDAT, IEND only: no tEXt/iTXt/zTXt/eXIf metadata).
    data = (ROOT / "icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, i = [], 8
    while i < len(data):
        length = int.from_bytes(data[i : i + 4], "big")
        chunks.append(data[i + 4 : i + 8])
        i += 12 + length
    assert set(chunks) <= {b"IHDR", b"IDAT", b"IEND"}, chunks
    assert data[16:24] == (512).to_bytes(4, "big") * 2


def test_mirror_leaves_out_internal_and_disallowed_files() -> None:
    # The mirror root is the plugin folder, and the directory blocks dotenv
    # files there: every .env* template must be in the snapshot EXCLUDE.
    script = (ROOT / "scripts" / "snapshot-public-mirror.sh").read_text()
    match = re.search(r"^EXCLUDE=\(([^)]*)\)$", script, re.M)
    assert match, "no EXCLUDE=(...) in snapshot-public-mirror.sh"
    excluded = set(match.group(1).split())
    assert {"DIRECTORIES.md", ".env.example"} <= excluded
    dotenv = {p.name for p in ROOT.glob(".env*") if p.name != ".env"}
    assert dotenv <= excluded, dotenv - excluded
