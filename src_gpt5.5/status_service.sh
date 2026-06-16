#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/service_common.sh"

echo "Root: $ROOT"
echo "Port: $PORT"

if [[ -f "$PID_FILE" ]]; then
  PID_VALUE="$(cat "$PID_FILE" 2>/dev/null || true)"
  echo "PID file: $PID_VALUE"
  if [[ "$PID_VALUE" =~ ^[0-9]+$ ]]; then
    if ps -p "$PID_VALUE" -o pid=,ppid=,comm=,etime= >/dev/null 2>&1; then
      ps -p "$PID_VALUE" -o pid=,ppid=,comm=,etime=
    else
      echo "PID file process is not running."
    fi
  fi
else
  echo "No PID file found."
fi

PORT_PIDS="$(port_pids || true)"
if [[ -n "$PORT_PIDS" ]]; then
  echo "Listening process IDs on port $PORT:"
  while IFS= read -r PID_VALUE; do
    [[ -z "$PID_VALUE" ]] && continue
    ps -p "$PID_VALUE" -o pid=,ppid=,comm=,etime= 2>/dev/null || echo "$PID_VALUE"
  done <<< "$PORT_PIDS"
else
  echo "No listening process found on port $PORT."
fi

if health_check; then
  print_health
else
  echo "HTTP check failed: http://127.0.0.1:$PORT/api/settings/health"
fi

