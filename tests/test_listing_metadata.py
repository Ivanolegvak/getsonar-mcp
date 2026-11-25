"""Directory metadata stays consistent with the code and the copy rules
(DIRECTORIES.md "Copy rules for every listing")."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from getsonar_mcp.tools import TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "claude-plugin"
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


def test_server_json_lists_the_hosted_server() -> None:
    # Registry-fed catalogues (Glama connectors, VS Code, GitHub MCP registry)
    # only show the hosted server when server.json carries it under `remotes`.
    assert SERVER["remotes"] == [{"type": "streamable-http", "url": REMOTE_MCP_URL}]


def test_mcp_dependency_is_capped_below_2() -> None:
    # mcp 2.x removed mcp.server.fastmcp; an uncapped pin breaks
    # `uvx getsonar-mcp` for every new install.
    pyproject = PUBLIC_TEXTS["pyproject.toml"]
    assert re.search(r'"mcp>=[0-9.]+,<2"', pyproject)
    # >=1.30.0: the HTTP transport's Host / Origin checks are tested on it
    # (0.3.3); pyproject and requirements.txt keep the same floor.
    assert '"mcp>=1.30.0,<2"' in pyproject
    assert "mcp>=1.30.0,<2" in (ROOT / "requirements.txt").read_text()


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
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert "userConfig" not in plugin
    assert plugin["icon"] == "./icon.png"
    # In the monorepo icon.png is a symlink to the package icon; the
    # snapshot copies the file itself into the mirror.
    assert (PLUGIN / "icon.png").read_bytes() == (ROOT / "icon.png").read_bytes()
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
    mcp_text = (PLUGIN / ".mcp.json").read_text()
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
    # DIRECTORIES.md stays internal; .env* templates stay out of the public
    # mirror (they were blocked when the mirror root was the plugin folder).
    script = (ROOT / "scripts" / "snapshot-public-mirror.sh").read_text()
    match = re.search(r"^EXCLUDE=\(([^)]*)\)$", script, re.M)
    assert match, "no EXCLUDE=(...) in snapshot-public-mirror.sh"
    excluded = set(match.group(1).split())
    assert {"DIRECTORIES.md", ".env.example"} <= excluded
    dotenv = {p.name for p in ROOT.glob(".env*") if p.name != ".env"}
    assert dotenv <= excluded, dotenv - excluded


# The Claude directory accepts only these file types in a plugin from an
# unverified organization (Markdown, text, JSON, YAML and PNG/JPEG/GIF/WebP/ICO
# images): no scripts, lock or package-manager files, dotfiles such as
# .mcpbignore, CLAUDE.md/AGENTS.md or extra .claude-plugin folders.
PLUGIN_ALLOWED_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
}  # fmt: skip
PLUGIN_EXPECTED = {".claude-plugin/plugin.json", ".mcp.json", "README.md", "icon.png"}


def _plugin_files(folder: Path) -> set[str]:
    return {
        p.relative_to(folder).as_posix() for p in folder.rglob("*") if not p.is_dir()
    }


def test_plugin_folder_holds_only_allowed_files() -> None:
    assert _plugin_files(PLUGIN) == PLUGIN_EXPECTED
    script = (ROOT / "scripts" / "snapshot-public-mirror.sh").read_text()
    match = re.search(r"^PLUGIN_FILES=\(([^)]*)\)$", script, re.M)
    assert match, "no PLUGIN_FILES=(...) in snapshot-public-mirror.sh"
    assert set(match.group(1).split()) == PLUGIN_EXPECTED
    assert "PLUGIN_DIR=claude-plugin" in script
    # The package root is no plugin any more: one manifest, in claude-plugin/.
    assert not (ROOT / ".claude-plugin").exists()
    assert not (ROOT / ".mcp.json").exists()


def test_plugin_readme_copy() -> None:
    text = (PLUGIN / "README.md").read_text()
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    assert len(prose.split()) >= 40  # directory minimum, code blocks excluded
    assert "\u2014" not in text and "\u2013" not in text  # no em or en dashes
    low = text.lower()
    disclaimer = "is **not** a regulated aml/kyc provider"
    assert disclaimer in low
    low = low.replace(disclaimer, "")  # the only allowed mention
    for banned in ("aml provider", "kyc provider", "competitive", "lifetime"):
        assert banned not in low, banned
    assert REMOTE_MCP_URL in text
    for name in TOOL_NAMES:
        assert f"| `{name}` |" in text, name
    assert "€0.50" in text and "€6.00" in text
    assert "https://getsonar.report/privacy" in text


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_mirror_plugin_folder_has_exactly_the_allowed_files(tmp_path: Path) -> None:
    # Build the real snapshot and check the folder the portal reads.
    if subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse"], capture_output=True
    ).returncode:
        pytest.skip("not a git checkout")
    out = tmp_path / "mirror"
    subprocess.run(
        [str(ROOT / "scripts" / "snapshot-public-mirror.sh"), str(out)],
        check=True,
        capture_output=True,
    )
    folder = out / "claude-plugin"
    files = _plugin_files(folder)
    assert files == PLUGIN_EXPECTED
    for rel in files:
        path = folder / rel
        assert not path.is_symlink(), rel
        assert path.suffix.lower() in PLUGIN_ALLOWED_SUFFIXES, rel
        assert not path.read_bytes().startswith(b"#!"), rel
        assert path.stat().st_size < 256 * 1024, rel
    assert (folder / "icon.png").read_bytes() == (ROOT / "icon.png").read_bytes()
    manifests = [p for p in out.rglob(".claude-plugin") if ".git" not in p.parts]
    assert manifests == [folder / ".claude-plugin"]
