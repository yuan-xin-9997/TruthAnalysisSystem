from __future__ import annotations

import logging
import sys
from datetime import timezone, timedelta
from logging.handlers import TimedRotatingFileHandler
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
BEIJING_TZ = timezone(timedelta(hours=8))


class BeijingFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802
        from datetime import datetime

        dt = datetime.fromtimestamp(record.created, tz=BEIJING_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


def _dated_log_name(default_name: str) -> str:
    """Convert ``app.log.YYYY-MM-DD`` to ``app-YYYY-MM-DD.log``."""
    path = Path(default_name)
    marker = ".log."
    if marker not in path.name:
        return default_name
    stem, date_suffix = path.name.rsplit(marker, 1)
    return str(path.with_name(f"{stem}-{date_suffix}.log"))


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> Path:
    """Configure the root logger with a rotating file handler + stdout.

    Writes to ``<logs_dir>/app.log`` and rotates it daily at midnight Beijing
    time, keeping the most recent 30 rotated files. Also echoes to stdout so
    foreground runs and service-script redirection still work.
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

    formatter = BeijingFormatter(LOG_FORMAT, DATE_FORMAT)

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.namer = _dated_log_name
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
