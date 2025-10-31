"""
Entrypoint for running the MCP server with uvicorn.
"""

import uvicorn

from .config import get_settings
from .server import app


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
