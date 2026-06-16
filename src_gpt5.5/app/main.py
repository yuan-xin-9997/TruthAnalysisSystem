from __future__ import annotations

import argparse
from pathlib import Path

from app.config import load_settings
from app.db import connect, init_db
from app.server import make_server
from app.services.market_data_service import ensure_symbols
from app.services.task_manager import DailyScheduler, TaskManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Truth Social post analysis system")
    parser.add_argument("--config", help="Path to app config JSON")
    parser.add_argument("--host", help="Host to bind, default from config")
    parser.add_argument("--port", type=int, help="Port to bind, default from config")
    args = parser.parse_args()

    settings = load_settings(Path(args.config) if args.config else None)
    if args.host:
        settings.app.host = args.host
    if args.port:
        settings.app.port = args.port

    init_db(settings.paths.database)
    manager = TaskManager(settings)
    conn = connect(settings.paths.database)
    try:
        ensure_symbols(conn, settings.market.symbols)
    finally:
        conn.close()
    scheduler = DailyScheduler(manager, settings)
    scheduler.start()

    server = make_server(settings, manager)
    url_host = "127.0.0.1" if settings.app.host == "0.0.0.0" else settings.app.host
    print(f"Serving on http://{url_host}:{settings.app.port}")
    print(f"LAN binding: {settings.app.host}:{settings.app.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server")
    finally:
        scheduler.stop()
        server.server_close()


if __name__ == "__main__":
    main()
