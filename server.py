"""Legacy entry point — delegates to ``getsonar_mcp.http_server``.

The Dockerfile + Render service config still ``CMD ["python", "server.py"]``,
so this file keeps backward compatibility with any deployed instance. The
real implementation now lives in the ``getsonar_mcp`` package (importable
from PyPI as ``getsonar-mcp``) so stdio + http transports share one tool
definition.

For new deployments, prefer:
    python -m getsonar_mcp.http_server  (remote / hosted, Streamable HTTP)
    python -m getsonar_mcp              (local, stdio — what `uvx getsonar-mcp` runs)
"""

import sys
from pathlib import Path

# Allow running this file without `pip install` — make `src/` importable.
_pkg_root = Path(__file__).parent / "src"
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from getsonar_mcp.http_server import main  # noqa: E402

if __name__ == "__main__":
    main()
