from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status_id TEXT UNIQUE,
  source_status_id INTEGER,
  title TEXT,
  author_name TEXT,
  author_handle TEXT,
  published_at_raw TEXT,
  published_at_utc TEXT,
  published_at_et TEXT,
  published_date TEXT,
  original_url TEXT,
  source_url TEXT,
  content_raw TEXT,
  content_clean TEXT,
  language TEXT DEFAULT 'en',
  is_retruth INTEGER DEFAULT 0,
  has_attachment INTEGER DEFAULT 0,
  word_count INTEGER DEFAULT 0,
  char_count INTEGER DEFAULT 0,
  file_path TEXT,
  file_hash TEXT,
  parse_status TEXT DEFAULT 'success',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_posts_published_at_utc ON posts(published_at_utc);
CREATE INDEX IF NOT EXISTS idx_posts_published_date ON posts(published_date);
CREATE INDEX IF NOT EXISTS idx_posts_source_status_id ON posts(source_status_id);
CREATE INDEX IF NOT EXISTS idx_posts_file_hash ON posts(file_hash);

CREATE TABLE IF NOT EXISTS post_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  attachment_type TEXT,
  url TEXT,
  local_path TEXT,
  description TEXT,
  raw_text TEXT
);

CREATE TABLE IF NOT EXISTS post_terms (
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  term TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY(post_id, term)
);

CREATE TABLE IF NOT EXISTS post_entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  entity_text TEXT,
  entity_type TEXT,
  normalized_name TEXT,
  confidence REAL,
  source TEXT
);

CREATE TABLE IF NOT EXISTS post_topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  topic TEXT,
  confidence REAL,
  source TEXT,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS post_china_relevance (
  post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  is_related INTEGER,
  score REAL,
  matched_keywords TEXT,
  reason TEXT,
  source TEXT,
  analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS post_sentiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  polarity TEXT,
  score REAL,
  intensity REAL,
  tones TEXT,
  source TEXT
);

CREATE TABLE IF NOT EXISTS post_llm_analysis (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  model TEXT,
  prompt_version TEXT,
  analysis_type TEXT,
  result_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(post_id, model, prompt_version, analysis_type)
);

CREATE TABLE IF NOT EXISTS post_market_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  signal_type TEXT,
  signal_score REAL,
  related_symbols TEXT,
  event_window TEXT,
  reason TEXT,
  source TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_type TEXT,
  status TEXT,
  trigger_type TEXT,
  parameters TEXT,
  started_at TEXT,
  finished_at TEXT,
  summary TEXT,
  error_message TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  level TEXT,
  message TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_symbols (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT UNIQUE,
  provider_symbol TEXT,
  name TEXT,
  asset_type TEXT,
  exchange_name TEXT,
  timezone TEXT,
  enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS market_prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol_id INTEGER NOT NULL REFERENCES market_symbols(id) ON DELETE CASCADE,
  trade_date TEXT,
  open REAL,
  high REAL,
  low REAL,
  close REAL,
  adjusted_close REAL,
  volume INTEGER,
  data_source TEXT,
  UNIQUE(symbol_id, trade_date, data_source)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  strategy_config TEXT,
  start_date TEXT,
  end_date TEXT,
  benchmark_symbol TEXT,
  total_return REAL,
  annual_return REAL,
  max_drawdown REAL,
  sharpe_ratio REAL,
  win_rate REAL,
  trade_count INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  backtest_run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
  post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL,
  symbol TEXT,
  entry_date TEXT,
  exit_date TEXT,
  entry_price REAL,
  exit_price REAL,
  return_pct REAL,
  signal_type TEXT,
  signal_score REAL
);

CREATE TABLE IF NOT EXISTS prediction_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  model_name TEXT,
  feature_version TEXT,
  train_start_date TEXT,
  train_end_date TEXT,
  target_symbol TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prediction_run_id INTEGER NOT NULL REFERENCES prediction_runs(id) ON DELETE CASCADE,
  symbol TEXT,
  target_date TEXT,
  horizon_days INTEGER,
  predicted_direction TEXT,
  predicted_return REAL,
  confidence REAL,
  feature_snapshot TEXT,
  actual_direction TEXT,
  actual_return REAL
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path | str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts "
                "USING fts5(title, content_clean, content='posts', content_rowid='id')"
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def refresh_post_fts(conn: sqlite3.Connection, post_id: int) -> None:
    try:
        row = conn.execute(
            "SELECT id, title, content_clean FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM posts_fts WHERE rowid = ?", (post_id,))
            conn.execute(
                "INSERT INTO posts_fts(rowid, title, content_clean) VALUES (?, ?, ?)",
                (row["id"], row["title"] or "", row["content_clean"] or ""),
            )
    except sqlite3.DatabaseError:
        return
