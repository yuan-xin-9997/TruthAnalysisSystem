#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/service_common.sh"

mkdir -p "$DATA_DIR"

PIDS=""
if [[ -f "$PID_FILE" ]]; then
  PID_VALUE="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ "$PID_VALUE" =~ ^[0-9]+$ ]]; then
    PIDS="$PIDS"$'\n'"$PID_VALUE"
  fi
else
  echo "No PID file found."
fi

PORT_PIDS="$(port_pids || true)"
if [[ -n "$PORT_PIDS" ]]; then
  PIDS="$PIDS"$'\n'"$PORT_PIDS"
fi

PIDS="$(printf '%s\n' "$PIDS" | unique_lines)"

if [[ -z "$PIDS" ]]; then
  echo "No running service process found for port $PORT."
  rm -f "$PID_FILE"
  exit 0
fi

FAILED=0
while IFS= read -r TARGET_PID; do
  [[ -z "$TARGET_PID" ]] && continue
  if ! kill -0 "$TARGET_PID" 2>/dev/null; then
    echo "No running process for PID=$TARGET_PID"
    continue
  fi

  if kill "$TARGET_PID" 2>/dev/null; then
    sleep 1
    if kill -0 "$TARGET_PID" 2>/dev/null; then
      if kill -9 "$TARGET_PID" 2>/dev/null; then
        echo "Force stopped process PID=$TARGET_PID"
      else
        echo "Failed to force stop PID=$TARGET_PID. Try sudo ./stop.sh."
        FAILED=1
      fi
    else
      echo "Stopped process PID=$TARGET_PID"
    fi
  else
    echo "Failed to stop PID=$TARGET_PID. Try sudo ./stop.sh."
    FAILED=1
  fi
done <<< "$PIDS"

sleep 1
if health_check; then
  echo "Warning: service still responds on port $PORT."
  exit 1
fi

rm -f "$PID_FILE"
if [[ "$FAILED" -eq 0 ]]; then
  echo "Service stopped on port $PORT."
else
  echo "Service is not responding, but one or more process stop attempts failed."
fi
