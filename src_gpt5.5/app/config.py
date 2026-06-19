from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SRC_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SRC_ROOT.parent


@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    timezone: str = "Asia/Shanghai"


@dataclass
class PathConfig:
    content_root: Path = WORKSPACE_ROOT
    database: Path = SRC_ROOT / "data" / "app.sqlite3"
    logs: Path = SRC_ROOT / "data" / "logs"
    exports: Path = SRC_ROOT / "data" / "exports"
    password_file: Path = SRC_ROOT / "data" / "password.txt"


@dataclass
class CrawlerConfig:
    enabled: bool = True
    progress_file: str = "已抓取.md"
    base_url: str = "https://trumpstruth.org/statuses"
    batch_size: int = 100
    daily_time: str = "06:30"
    request_timeout_seconds: int = 20
    request_delay_seconds: float = 0.1
    max_workers: int = 4
    max_retries: int = 3
    download_attachments: bool = True
    translate_to_chinese: bool = True


@dataclass
class AnalysisConfig:
    enable_llm: bool = True
    openai_model: str = "gpt-5.5"
    prompt_version: str = "v1"
    cache_llm_results: bool = True


@dataclass
class MarketConfig:
    enabled: bool = True
    daily_sync_time: str = "07:00"
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    prediction_horizons: list[int] = field(default_factory=lambda: [1, 3, 5])
    transaction_cost_bps: float = 5.0
    provider: str = "stooq"


@dataclass
class SchedulerConfig:
    enabled: bool = True
    run_on_startup: bool = False


@dataclass
class Settings:
    app: AppConfig = field(default_factory=AppConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)


def _merge_dataclass(obj: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if not hasattr(obj, key):
            continue
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        elif isinstance(current, Path):
            setattr(obj, key, _resolve_path(value))
        else:
            setattr(obj, key, value)


def _resolve_path(value: str | Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not path.is_absolute():
        path = SRC_ROOT / path
    return path.resolve()


def load_settings(config_path: str | Path | None = None) -> Settings:
    settings = Settings()
    path = Path(config_path) if config_path else SRC_ROOT / "config" / "app.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        paths = data.get("paths")
        if isinstance(paths, dict) and "data_root" in paths and "content_root" not in paths:
            paths["content_root"] = paths["data_root"]
        _merge_dataclass(settings, data)
    if env_content_root := os.environ.get("TRUTH_CONTENT_ROOT"):
        settings.paths.content_root = _resolve_path(env_content_root)
    settings.paths.content_root.mkdir(parents=True, exist_ok=True)
    settings.paths.database.parent.mkdir(parents=True, exist_ok=True)
    settings.paths.logs.mkdir(parents=True, exist_ok=True)
    settings.paths.exports.mkdir(parents=True, exist_ok=True)
    return settings


def public_settings(settings: Settings) -> dict[str, Any]:
    return {
        "app": settings.app.__dict__,
        "paths": {
            "content_root": str(settings.paths.content_root),
            "database": str(settings.paths.database),
            "logs": str(settings.paths.logs),
            "exports": str(settings.paths.exports),
            "password_file": str(settings.paths.password_file),
        },
        "crawler": settings.crawler.__dict__,
        "analysis": {
            **settings.analysis.__dict__,
            "openai_api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        },
        "market": settings.market.__dict__,
        "scheduler": settings.scheduler.__dict__,
    }
