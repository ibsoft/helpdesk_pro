"""Standalone runner for the Fleet ingest service."""

from __future__ import annotations

import os

from werkzeug.serving import make_server

from app import create_app
from app.fleet.ingest import create_fleet_ingest_app


def main():
    # Ensure the main Flask app does not attempt to spawn its own ingest thread
    os.environ.setdefault("FLEET_EMBED_INGEST", "0")

    main_app = create_app()
    ingest_app = create_fleet_ingest_app(main_app)

    host = main_app.config.get("FLEET_INGEST_HOST", "0.0.0.0")
    port = int(main_app.config.get("FLEET_INGEST_PORT", 8449))

    server = make_server(host, port, ingest_app)
    ingest_app.logger.info("Standalone Fleet ingest server listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ingest_app.logger.info("Fleet ingest server stopping.")


if __name__ == "__main__":
    main()
