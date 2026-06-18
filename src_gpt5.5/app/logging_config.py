from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Level name -> logging constant, used when mirroring task logs.
LEVEL_BY_NAME: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_configured = False


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> Path:
    """Configure the root logger with a rotating file handler + stdout.

    Writes to ``<logs_dir>/app.log`` (5 MB × 5 backups) and also echoes to
    stdout so foreground runs and service-script redirection still work.
    Safe to call once; subsequent calls are no-ops.
    """

    global _configured
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "app.log"

    root = logging.getLogger()
    # Avoid duplicate handlers if setup_logging is called twice.
    if _configured:
        return log_file
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    root.addHandler(stream_handler)

    _configured = True
    logging.getLogger(__name__).info("Logging initialized -> %s", log_file)
    return log_file


def level_for(name: str) -> int:
    """Map a task-log level string ('INFO', 'ERROR', ...) to a logging level."""

    return LEVEL_BY_NAME.get(str(name).upper(), logging.INFO)
