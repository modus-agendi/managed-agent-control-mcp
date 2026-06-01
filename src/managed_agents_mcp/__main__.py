"""Entry point.

python -m managed_agents_mcp           # stdio (local, Claude Code, Inspector)
python -m managed_agents_mcp --http    # HTTP server (uvicorn; container, VPS)
"""

from __future__ import annotations

import sys


def main() -> None:
    if "--http" in sys.argv[1:]:
        from .app.run import run_http

        run_http()
    else:
        from .app.run import run_stdio

        run_stdio()


if __name__ == "__main__":
    main()
