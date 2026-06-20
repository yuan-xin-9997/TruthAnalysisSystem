#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$ROOT/data"
LOGS_DIR="$ROOT/logs"
CONFIG_FILE="$ROOT/config/app.json"
PID_FILE="$LOGS_DIR/server.pid"
OUT_LOG="$LOGS_DIR/server.out.log"
ERR_LOG="$LOGS_DIR/server.err.log"

choose_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
  else
    printf '%s\n' "python3"
  fi
}

PYTHON_CMD="$(choose_python)"

read_port() {
  "$PYTHON_CMD" - "$CONFIG_FILE" <<'PY' 2>/dev/null || printf '%s\n' "8000"
import json
import sys
from pathlib import Path

config = Path(sys.argv[1])
if not config.exists():
    print(8000)
else:
    data = json.loads(config.read_text(encoding="utf-8"))
    print(data.get("app", {}).get("port", 8000))
PY
}

PORT="${SERVICE_PORT:-$(read_port)}"

health_check() {
  "$PYTHON_CMD" - "$PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

port = sys.argv[1]
urllib.request.urlopen(f"http://127.0.0.1:{port}/api/settings/health", timeout=3).read()
PY
}

print_health() {
  "$PYTHON_CMD" - "$PORT" <<'PY'
import sys
import urllib.request

port = sys.argv[1]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/settings/health", timeout=5) as response:
    print(f"HTTP: {response.status}")
    print(response.read().decode("utf-8"))
PY
}

port_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$PORT" 2>/dev/null \
      | grep -o 'pid=[0-9]*' \
      | cut -d= -f2 \
      | sort -u || true
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltnp 2>/dev/null \
      | awk -v port="$PORT" '$4 ~ ":" port "$" { split($7, a, "/"); if (a[1] ~ /^[0-9]+$/) print a[1] }' \
      | sort -u || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "$PORT/tcp" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
  fi
}

unique_lines() {
  awk 'NF && !seen[$0]++'
}
