from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable

from app.config import SRC_ROOT, Settings
from app.db import connect
from app.logging_config import level_for
from app.services.crawler_service import crawl_new_statuses
from app.services.market_data_service import (
    ensure_symbols,
    generate_predictions,
    run_event_backtest,
    sync_market_prices,
)
from app.services.post_importer import import_markdown_tree
from app.services.text_analyzer import analyze_all_posts


TaskFunc = Callable[[sqlite3.Connection, int, dict[str, Any]], dict[str, Any]]

logger = logging.getLogger("app.task_manager")


class TaskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self._registry: dict[str, TaskFunc] = {
            "crawl": self._task_crawl,
            "import": self._task_import,
            "analyze": self._task_analyze,
            "reanalyze": self._task_reanalyze,
            "market_sync": self._task_market_sync,
            "backtest": self._task_backtest,
            "predict": self._task_predict,
            "daily_chain": self._task_daily_chain,
        }

    def start_task(self, task_type: str, trigger_type: str = "manual", parameters: dict[str, Any] | None = None) -> int:
        if task_type not in self._registry:
            raise ValueError(f"Unknown task type: {task_type}")
        params = parameters or {}
        with connect(self.settings.paths.database) as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks(task_type, status, trigger_type, parameters)
                VALUES (?, 'pending', ?, ?)
                """,
                (task_type, trigger_type, json.dumps(params, ensure_ascii=False)),
            )
            conn.commit()
            task_id = int(cur.lastrowid)
        thread = threading.Thread(
            target=self._run_task_thread,
            args=(task_id, task_type, params),
            name=f"task-{task_type}-{task_id}",
            daemon=True,
        )
        thread.start()
        return task_id

    def _run_task_thread(self, task_id: int, task_type: str, params: dict[str, Any]) -> None:
        with self._lock:
            if task_type in self._running and task_type != "daily_chain":
                self._mark_failed(task_id, f"Task {task_type} is already running")
                return
            self._running.add(task_type)
        conn = connect(self.settings.paths.database)
        try:
            conn.execute(
                "UPDATE tasks SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE id = ?",
                (task_id,),
            )
            conn.commit()
            self.log(conn, task_id, "INFO", f"Started {task_type}")
            summary = self._registry[task_type](conn, task_id, params)
            conn.execute(
                """
                UPDATE tasks
                SET status = 'success', finished_at = CURRENT_TIMESTAMP, summary = ?
                WHERE id = ?
                """,
                (json.dumps(summary, ensure_ascii=False), task_id),
            )
            self.log(conn, task_id, "INFO", f"Finished {task_type}")
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            error = str(exc)
            self.log(conn, task_id, "ERROR", error)
            self.log(conn, task_id, "ERROR", traceback.format_exc()[:3000])
            conn.execute(
                """
                UPDATE tasks
                SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error_message = ?
                WHERE id = ?
                """,
                (error, task_id),
            )
            conn.commit()
        finally:
            conn.close()
            with self._lock:
                self._running.discard(task_type)

    def _mark_failed(self, task_id: int, error: str) -> None:
        with connect(self.settings.paths.database) as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error_message = ?
                WHERE id = ?
                """,
                (error, task_id),
            )
            conn.commit()

    def log(self, conn: sqlite3.Connection, task_id: int, level: str, message: str) -> None:
        conn.execute(
            "INSERT INTO task_logs(task_id, level, message) VALUES (?, ?, ?)",
            (task_id, level, message),
        )
        conn.commit()
        # Mirror to the file logger so log files capture task progress.
        logger.log(level_for(level), "[task#%s] %s", task_id, message)

    def _task_crawl(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        task_started = time.perf_counter()
        self.log(conn, task_id, "INFO", "开始抓取新增贴文")
        start_after = _optional_int(params.get("start_after"))
        batch_size = _optional_int(params.get("batch_size"))
        download_attachments = params.get("download_attachments")
        if download_attachments is not None:
            download_attachments = _as_bool(download_attachments)
        translate_to_chinese = params.get("translate_to_chinese")
        if translate_to_chinese is not None:
            translate_to_chinese = _as_bool(translate_to_chinese)
        self.log(
            conn,
            task_id,
            "INFO",
            (
                f"参数：start_after={start_after if start_after is not None else '读取进度文件'}，"
                f"batch_size={batch_size if batch_size is not None else self.settings.crawler.batch_size}，"
                f"download_attachments={download_attachments if download_attachments is not None else self.settings.crawler.download_attachments}，"
                f"translate_to_chinese={translate_to_chinese if translate_to_chinese is not None else self.settings.crawler.translate_to_chinese}，"
                f"chain={_as_bool(params.get('chain', True))}"
            ),
        )
        result = crawl_new_statuses(
            self.settings,
            start_after=start_after,
            batch_size=batch_size,
            download_attachments_enabled=download_attachments,
            translate_to_chinese_enabled=translate_to_chinese,
            log=lambda level, message: self.log(conn, task_id, level, message),
        )
        self.log(conn, task_id, "INFO", f"抓取阶段结束：保存 {result['saved']} 个 Markdown，耗时 {result['seconds']}s")
        if _as_bool(params.get("chain", True)):
            import_started = time.perf_counter()
            self.log(conn, task_id, "INFO", "开始导入 Markdown 到 SQLite")
            import_result = import_markdown_tree(
                conn,
                self.settings.paths.content_root,
                SRC_ROOT,
                limit=_optional_int(params.get("import_limit")),
            )
            import_seconds = round(time.perf_counter() - import_started, 3)
            self.log(
                conn,
                task_id,
                "INFO",
                (
                    f"导入阶段结束：扫描 {import_result['scanned']}，候选 {import_result['candidates']}，"
                    f"新增 {import_result['inserted']}，更新 {import_result['updated']}，"
                    f"跳过 {import_result['skipped']}，失败 {import_result['failed']}，耗时 {import_seconds}s"
                ),
            )
            analyze_started = time.perf_counter()
            self.log(conn, task_id, "INFO", "开始增量分析未分析贴文")
            analysis_result = analyze_all_posts(conn, only_missing=True, settings=self.settings)
            analysis_seconds = round(time.perf_counter() - analyze_started, 3)
            self.log(conn, task_id, "INFO", f"分析阶段结束：分析 {analysis_result['analyzed']} 条，耗时 {analysis_seconds}s")
            result["import"] = import_result
            result["analysis"] = analysis_result
            result["import_seconds"] = import_seconds
            result["analysis_seconds"] = analysis_seconds
        result["total_seconds"] = round(time.perf_counter() - task_started, 3)
        self.log(conn, task_id, "INFO", f"抓取任务总耗时 {result['total_seconds']}s")
        return result

    def _task_import(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        self.log(conn, task_id, "INFO", "开始导入 Markdown 文件")
        result = import_markdown_tree(
            conn,
            self.settings.paths.content_root,
            SRC_ROOT,
            limit=_optional_int(params.get("limit")),
        )
        result["seconds"] = round(time.perf_counter() - started, 3)
        self.log(
            conn,
            task_id,
            "INFO",
            (
                f"导入完成：扫描 {result['scanned']}，候选 {result['candidates']}，"
                f"新增 {result['inserted']}，更新 {result['updated']}，跳过 {result['skipped']}，"
                f"失败 {result['failed']}，耗时 {result['seconds']}s"
            ),
        )
        return result

    def _task_analyze(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        only_missing = bool(params.get("only_missing", True))
        started = time.perf_counter()
        self.log(conn, task_id, "INFO", f"开始分析贴文，only_missing={only_missing}")
        result = analyze_all_posts(conn, only_missing=only_missing, settings=self.settings)
        result["seconds"] = round(time.perf_counter() - started, 3)
        self.log(conn, task_id, "INFO", f"分析完成：分析 {result['analyzed']} 条，耗时 {result['seconds']}s")
        return result

    def _task_reanalyze(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        self.log(conn, task_id, "INFO", "开始重分析已有贴文，覆盖旧分析结果")
        result = analyze_all_posts(conn, only_missing=False, settings=self.settings)
        result["seconds"] = round(time.perf_counter() - started, 3)
        self.log(conn, task_id, "INFO", f"重分析完成：分析 {result['analyzed']} 条，耗时 {result['seconds']}s")
        return result

    def _task_market_sync(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        symbols = params.get("symbols") or self.settings.market.symbols
        self.log(conn, task_id, "INFO", f"Syncing market data: {', '.join(symbols)}")
        ensure_symbols(conn, symbols)
        return sync_market_prices(conn, symbols)

    def _task_backtest(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        symbol = params.get("symbol", "SPY")
        hold_days = int(params.get("hold_days", 1))
        self.log(conn, task_id, "INFO", f"Running backtest: {symbol}, hold_days={hold_days}")
        return run_event_backtest(
            conn,
            symbol=symbol,
            hold_days=hold_days,
            transaction_cost_bps=self.settings.market.transaction_cost_bps,
        )

    def _task_predict(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        symbols = params.get("symbols") or self.settings.market.symbols
        horizons = params.get("horizons") or self.settings.market.prediction_horizons
        self.log(conn, task_id, "INFO", "Generating market predictions")
        return generate_predictions(conn, symbols, horizons)

    def _task_daily_chain(self, conn: sqlite3.Connection, task_id: int, params: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        result["crawl"] = self._task_crawl(conn, task_id, {"chain": True})
        try:
            result["market_sync"] = self._task_market_sync(conn, task_id, {})
        except Exception as exc:  # noqa: BLE001
            result["market_sync_error"] = str(exc)
        try:
            result["predict"] = self._task_predict(conn, task_id, {})
        except Exception as exc:  # noqa: BLE001
            result["predict_error"] = str(exc)
        return result


class DailyScheduler:
    def __init__(self, manager: TaskManager, settings: Settings) -> None:
        self.manager = manager
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run: dict[str, str] = {}

    def start(self) -> None:
        if not self.settings.scheduler.enabled:
            return
        self._thread = threading.Thread(target=self._loop, name="daily-scheduler", daemon=True)
        self._thread.start()
        if self.settings.scheduler.run_on_startup:
            self.manager.start_task("daily_chain", trigger_type="startup")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            today = now.date().isoformat()
            if current_time == self.settings.crawler.daily_time and self._last_run.get("daily_chain") != today:
                self._last_run["daily_chain"] = today
                self.manager.start_task("daily_chain", trigger_type="schedule")
            if current_time == self.settings.market.daily_sync_time and self._last_run.get("market_sync") != today:
                self._last_run["market_sync"] = today
                self.manager.start_task("market_sync", trigger_type="schedule")
            time.sleep(20)


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)
