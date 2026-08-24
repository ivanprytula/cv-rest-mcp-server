"""Run the CV MCP server over stdio for local MCP clients (e.g. opencode).

Boots the real FastAPI lifespan first so tools see app.state.pdf_service,
then serves the same FastMCP instance that is mounted at /mcp under uvicorn.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# main.py points root logging at stdout for the uvicorn console; stdio
# clients require a clean stdout, so re-point every handler at stderr.
import logging  # noqa: E402

import anyio  # noqa: E402

from app.main import app, mcp  # noqa: E402


logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)


async def serve() -> None:
    async with app.router.lifespan_context(app):
        await mcp.run_stdio_async()


if __name__ == "__main__":
    anyio.run(serve)
