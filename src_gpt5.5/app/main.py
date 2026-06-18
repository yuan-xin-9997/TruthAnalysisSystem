from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.config import load_settings
from app.db import connect, init_db
from app.logging_config import setup_logging
from app.server import make_server
from app.services.auth_service import (
    cleanup_expired_sessions,
    parse_password_file,
    sync_users,
)
from app.services.market_data_service import ensure_symbols
from app.services.task_manager import DailyScheduler, TaskManager


logger = logging.getLogger("app.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Truth Social post analysis system")
    parser.add_argument("--config", help="Path to app config JSON")
    parser.add_argument("--host", help="Host to bind, default from config")
    parser.add_argument("--port", type=int, help="Port to bind, default from config")
    args = parser.parse_args()

    settings = load_settings(Path(args.config) if args.config else None)
    # Configure file logging as early as possible so startup issues are captured.
    log_file = setup_logging(settings.paths.logs)
    if args.host:
        settings.app.host = args.host
    if args.port:
        settings.app.port = args.port

    init_db(settings.paths.database)
    manager = TaskManager(settings)
    conn = connect(settings.paths.database)
    try:
        ensure_symbols(conn, settings.market.symbols)
        # Bootstrap users from password.txt; creates the file with a default
        # admin row if missing.
        file_users = parse_password_file(settings.paths.password_file)
        sync_users(conn, file_users)
        cleanup_expired_sessions(conn)
        logger.info("Loaded %d user(s) from %s", len(file_users), settings.paths.password_file)
    finally:
        conn.close()
    scheduler = DailyScheduler(manager, settings)
    scheduler.start()

    server = make_server(settings, manager)
    url_host = "127.0.0.1" if settings.app.host == "0.0.0.0" else settings.app.host
    logger.info("Serving on http://%s:%s", url_host, settings.app.port)
    logger.info("LAN binding: %s:%s", settings.app.host, settings.app.port)
    logger.info("Log file: %s", log_file)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server (KeyboardInterrupt)")
    finally:
        scheduler.stop()
        server.server_close()


if __name__ == "__main__":
    main()
