"""Stdio entry point for the MCPB bundle (manifest.json, server type ``uv``).

Claude Desktop runs ``uv run --directory <bundle> --frozen --no-dev
mcpb_server.py``: uv builds the environment from the bundled
``pyproject.toml`` + ``uv.lock``, so the bundle runs the source it ships
(not whatever version PyPI has). ``src/getsonar_mcp/__main__.py`` uses
relative imports and cannot be run as a plain script, hence this file.
"""

import sys
from pathlib import Path

# Make src/ importable even if the host runs this file without the project
# installed in the environment.
_pkg_root = Path(__file__).parent / "src"
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from getsonar_mcp.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
