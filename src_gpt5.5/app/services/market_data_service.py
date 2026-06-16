from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any


STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={start}&d2={end}&i=d"


def ensure_symbols(conn: sqlite3.Connection, symbols: list[str]) -> None:
    for symbol in symbols:
        provider_symbol = f"{symbol.lower()}.us"
        conn.execute(
            """
            INSERT OR IGNORE INTO market_symbols
              (symbol, provider_symbol, name, asset_type, exchange_name, timezone, enabled)
            VALUES (?, ?, ?, 'etf', 'US', 'America/New_York', 1)
            """,
            (symbol.upper(), provider_symbol, symbol.upper()),
        )
    conn.commit()


def sync_market_prices(conn: sqlite3.Connection, symbols: list[str], years_back: int = 8) -> dict[str, Any]:
    ensure_symbols(conn, symbols)
    end = date.today()
    start = end - timedelta(days=365 * years_back)
    summary: dict[str, Any] = {"symbols": {}, "errors": []}
    for symbol in symbols:
        row = conn.execute(
            "SELECT * FROM market_symbols WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
        if not row:
            continue
        try:
            count = _sync_symbol(conn, dict(row), start, end)
            summary["symbols"][symbol.upper()] = count
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append({"symbol": symbol, "error": str(exc)})
    conn.commit()
    return summary


def _sync_symbol(conn: sqlite3.Connection, symbol_row: dict[str, Any], start: date, end: date) -> int:
    url = STOOQ_URL.format(
        symbol=symbol_row["provider_symbol"],
        start=start.strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
    )
    with urllib.request.urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    count = 0
    for item in reader:
        if not item.get("Date") or item.get("Close") in {None, "N/D"}:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO market_prices
              (symbol_id, trade_date, open, high, low, close, adjusted_close, volume, data_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'stooq')
            """,
            (
                symbol_row["id"],
                item["Date"],
                _float(item.get("Open")),
                _float(item.get("High")),
                _float(item.get("Low")),
                _float(item.get("Close")),
                _float(item.get("Close")),
                int(float(item.get("Volume") or 0)),
            ),
        )
        count += 1
    return count


def run_event_backtest(
    conn: sqlite3.Connection,
    symbol: str = "SPY",
    hold_days: int = 1,
    min_score: float = 0.35,
    transaction_cost_bps: float = 5.0,
) -> dict[str, Any]:
    prices = _load_prices(conn, symbol)
    if len(prices) < 2:
        raise RuntimeError(f"Not enough market data for {symbol}")
    price_dates = sorted(prices)
    signals = conn.execute(
        """
        SELECT s.*, p.published_date, p.title
        FROM post_market_signals s
        JOIN posts p ON p.id = s.post_id
        WHERE s.signal_score >= ?
        ORDER BY p.published_date
        """,
        (min_score,),
    ).fetchall()
    trades = []
    cost = transaction_cost_bps / 10000.0
    for signal in signals:
        entry_date = _next_trade_date(price_dates, signal["published_date"])
        if not entry_date:
            continue
        exit_date = _offset_trade_date(price_dates, entry_date, hold_days)
        if not exit_date:
            continue
        entry = prices[entry_date]
        exit_price = prices[exit_date]
        direction = -1 if signal["signal_type"] == "bearish" else 1
        ret = direction * ((exit_price / entry) - 1.0) - cost
        trades.append(
            {
                "post_id": signal["post_id"],
                "symbol": symbol,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_price": entry,
                "exit_price": exit_price,
                "return_pct": ret,
                "signal_type": signal["signal_type"],
                "signal_score": signal["signal_score"],
            }
        )
    if not trades:
        raise RuntimeError("No trades generated from current signals")
    equity = 1.0
    curve = []
    wins = 0
    for trade in trades:
        equity *= 1.0 + trade["return_pct"]
        curve.append(equity)
        wins += 1 if trade["return_pct"] > 0 else 0
    max_dd = _max_drawdown(curve)
    total_return = equity - 1.0
    years = max(1 / 365, (datetime.fromisoformat(trades[-1]["exit_date"]) - datetime.fromisoformat(trades[0]["entry_date"])).days / 365)
    annual_return = (1 + total_return) ** (1 / years) - 1
    returns = [t["return_pct"] for t in trades]
    sharpe = _sharpe(returns)

    cur = conn.execute(
        """
        INSERT INTO backtest_runs
          (name, strategy_config, start_date, end_date, benchmark_symbol, total_return,
           annual_return, max_drawdown, sharpe_ratio, win_rate, trade_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"{symbol} event signal hold {hold_days}d",
            json.dumps({"hold_days": hold_days, "min_score": min_score}, ensure_ascii=False),
            trades[0]["entry_date"],
            trades[-1]["exit_date"],
            symbol,
            total_return,
            annual_return,
            max_dd,
            sharpe,
            wins / len(trades),
            len(trades),
        ),
    )
    run_id = int(cur.lastrowid)
    for trade in trades:
        conn.execute(
            """
            INSERT INTO backtest_trades
              (backtest_run_id, post_id, symbol, entry_date, exit_date, entry_price,
               exit_price, return_pct, signal_type, signal_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                trade["post_id"],
                trade["symbol"],
                trade["entry_date"],
                trade["exit_date"],
                trade["entry_price"],
                trade["exit_price"],
                trade["return_pct"],
                trade["signal_type"],
                trade["signal_score"],
            ),
        )
    conn.commit()
    return {"run_id": run_id, "trade_count": len(trades), "total_return": total_return}


def generate_predictions(conn: sqlite3.Connection, symbols: list[str], horizons: list[int]) -> dict[str, Any]:
    run = conn.execute(
        """
        INSERT INTO prediction_runs(name, model_name, feature_version, train_start_date, train_end_date, target_symbol)
        VALUES ('rule baseline prediction', 'rule-v1', 'features-v1', NULL, date('now'), ?)
        """,
        (",".join(symbols),),
    )
    run_id = int(run.lastrowid)
    count = 0
    recent = conn.execute(
        """
        SELECT s.signal_type, s.signal_score
        FROM post_market_signals s
        JOIN posts p ON p.id = s.post_id
        WHERE p.published_date >= date('now', '-7 day')
        """
    ).fetchall()
    net = 0.0
    for row in recent:
        if row["signal_type"] == "bullish":
            net += float(row["signal_score"])
        elif row["signal_type"] == "bearish":
            net -= float(row["signal_score"])
    direction = "up" if net > 0.3 else "down" if net < -0.3 else "flat"
    confidence = min(0.85, 0.45 + abs(net) / 5)
    target_base = date.today()
    for symbol in symbols:
        for horizon in horizons:
            conn.execute(
                """
                INSERT INTO predictions
                  (prediction_run_id, symbol, target_date, horizon_days, predicted_direction,
                   predicted_return, confidence, feature_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    symbol,
                    (target_base + timedelta(days=horizon)).isoformat(),
                    horizon,
                    direction,
                    0.002 * horizon if direction == "up" else -0.002 * horizon if direction == "down" else 0.0,
                    confidence,
                    json.dumps({"recent_signal_count": len(recent), "net_signal_score": net}),
                ),
            )
            count += 1
    conn.commit()
    return {"run_id": run_id, "predictions": count, "direction": direction, "confidence": confidence}


def _load_prices(conn: sqlite3.Connection, symbol: str) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT p.trade_date, p.adjusted_close
        FROM market_prices p
        JOIN market_symbols s ON s.id = p.symbol_id
        WHERE s.symbol = ?
        ORDER BY p.trade_date
        """,
        (symbol.upper(),),
    ).fetchall()
    return {row["trade_date"]: float(row["adjusted_close"]) for row in rows}


def _next_trade_date(price_dates: list[str], date_value: str | None) -> str | None:
    if not date_value:
        return None
    for trade_date in price_dates:
        if trade_date >= date_value:
            return trade_date
    return None


def _offset_trade_date(price_dates: list[str], entry_date: str, offset: int) -> str | None:
    try:
        idx = price_dates.index(entry_date)
    except ValueError:
        return None
    target = idx + offset
    return price_dates[target] if target < len(price_dates) else None


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0]
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1)
    return max_dd


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    return 0.0 if std == 0 else avg / std * math.sqrt(252)


def _float(value: str | None) -> float | None:
    if value in {None, "", "N/D"}:
        return None
    return float(value)

