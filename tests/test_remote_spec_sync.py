"""The remote MCP Worker (mcp-remote/ in the monorepo) serves a tool catalogue
and formatter port generated from this package. Changing a tool, a
description, a price or a formatter here without re-running
``mcp-remote/scripts/export_spec.py`` fails this test.

Skipped in the public mirror (github.com/Ivanolegvak/getsonar-mcp), which has
no mcp-remote/ folder.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "mcp-remote" / "scripts" / "export_spec.py"
)


@pytest.mark.skipif(
    not SCRIPT.exists(), reason="mcp-remote/ not present (public mirror)"
)
def test_remote_worker_spec_is_current() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        "mcp-remote/spec is stale; run "
        "`uv run --project mcp-server python mcp-remote/scripts/export_spec.py` "
        "and commit spec/tool-spec.json + spec/golden.json.\n"
        + proc.stdout
        + proc.stderr
    )
