#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/service_common.sh"

mkdir -p "$DATA_DIR"
mkdir -p "$LOGS_DIR"

if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
  echo "Python was not found. Install python3, or set PYTHON_BIN=/path/to/python."
  exit 1
fi

if health_check; then
  echo "Service is already running: http://127.0.0.1:$PORT"
  print_health
  exit 0
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "PID file points to a running process ($OLD_PID), but health check failed."
    echo "Run ./stop.sh first if this is a stale or unhealthy service."
    exit 1
  fi
  rm -f "$PID_FILE"
fi

cd "$ROOT"
nohup env PYTHONPATH="$ROOT" "$PYTHON_CMD" -m app.main --config "$CONFIG_FILE" >"$OUT_LOG" 2>"$ERR_LOG" &
SERVICE_PID="$!"
echo "$SERVICE_PID" > "$PID_FILE"

for _ in $(seq 1 15); do
  if health_check; then
    echo "Service started. PID=$SERVICE_PID"
    echo "Local URL: http://127.0.0.1:$PORT"
    echo "LAN URL: http://<this-machine-ip>:$PORT"
    print_health
    exit 0
  fi
  if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "Service did not respond after start."
echo "Stdout log: $OUT_LOG"
echo "Stderr log: $ERR_LOG"
if [[ -f "$ERR_LOG" ]]; then
  tail -n 80 "$ERR_LOG"
fi
exit 1
