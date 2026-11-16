#!/usr/bin/env bash
# Launches both pieces of the web demo together:
#   - the static WebGL viewer (plain http.server) on :8000
#   - the Flask query API (query_server.py, crime-image-tag env) on :5001
#     (port fixed by index.html's QUERY_API constant -- do not change
#     without updating that too)
#
# Usage: ./run_demo.sh   (from anywhere; paths resolve relative to this file)
# Stop with Ctrl+C -- cleanly kills both background servers, no orphans.

set -uo pipefail

UI_WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_PORT=8000
API_PORT=5001
CONDA_SH="/home/vedanth/miniforge3/etc/profile.d/conda.sh"

STATIC_LOG="$(mktemp -t run_demo_static.XXXXXX.log)"
API_LOG="$(mktemp -t run_demo_api.XXXXXX.log)"
STATIC_PID=""
API_PID=""

CLEANED_UP=0
cleanup() {
  [ "$CLEANED_UP" -eq 1 ] && return  # EXIT and INT/TERM both trigger this; only run once
  CLEANED_UP=1
  echo ""
  echo "[run_demo] shutting down..."
  for pid in "$STATIC_PID" "$API_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    fi
  done
  rm -f "$STATIC_LOG" "$API_LOG"
  echo "[run_demo] stopped."
}
trap cleanup EXIT INT TERM

port_in_use() {
  # Try the actual thing we care about: can we bind/connect on this port?
  # curl against a closed port fails fast and portably (no lsof/ss dependency).
  curl -s -o /dev/null --connect-timeout 1 "http://127.0.0.1:$1/" 2>/dev/null
  [ $? -ne 7 ]  # curl exit 7 = "couldn't connect" = port free; anything else = something's listening
}

if port_in_use "$STATIC_PORT"; then
  echo "[run_demo] ERROR: port $STATIC_PORT is already in use (a previous run_demo.sh, or something else, is already listening there)." >&2
  echo "           Find and stop it first, e.g.: lsof -i :$STATIC_PORT" >&2
  exit 1
fi
if port_in_use "$API_PORT"; then
  echo "[run_demo] ERROR: port $API_PORT is already in use (a previous run_demo.sh, or something else, is already listening there)." >&2
  echo "           Find and stop it first, e.g.: lsof -i :$API_PORT" >&2
  exit 1
fi

if [ ! -f "$CONDA_SH" ]; then
  echo "[run_demo] ERROR: expected conda at $CONDA_SH, not found. Edit CONDA_SH in this script for your machine." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$CONDA_SH"

echo "[run_demo] starting query API (query_server.py, crime-image-tag env) on :$API_PORT..."
conda activate crime-image-tag
if [ $? -ne 0 ]; then
  echo "[run_demo] ERROR: 'conda activate crime-image-tag' failed -- does that env exist? (conda env list)" >&2
  exit 1
fi
python "$UI_WEB_DIR/query_server.py" > "$API_LOG" 2>&1 &
API_PID=$!
conda deactivate

echo "[run_demo] starting static file server on :$STATIC_PORT..."
( cd "$UI_WEB_DIR" && python3 -m http.server "$STATIC_PORT" > "$STATIC_LOG" 2>&1 ) &
STATIC_PID=$!

echo "[run_demo] waiting for both servers to actually respond..."
api_ready=0
static_ready=0
for i in $(seq 1 60); do
  if [ "$api_ready" -eq 0 ]; then
    if ! kill -0 "$API_PID" 2>/dev/null; then
      echo "[run_demo] ERROR: query API process died before becoming ready. Log:" >&2
      cat "$API_LOG" >&2
      exit 1
    fi
    if curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/query?text=ping"; then
      api_ready=1
      echo "[run_demo]   query API is up (:$API_PORT)"
    fi
  fi
  if [ "$static_ready" -eq 0 ]; then
    if ! kill -0 "$STATIC_PID" 2>/dev/null; then
      echo "[run_demo] ERROR: static file server process died before becoming ready. Log:" >&2
      cat "$STATIC_LOG" >&2
      exit 1
    fi
    if curl -sf -o /dev/null "http://127.0.0.1:$STATIC_PORT/index.html"; then
      static_ready=1
      echo "[run_demo]   static viewer is up (:$STATIC_PORT)"
    fi
  fi
  [ "$api_ready" -eq 1 ] && [ "$static_ready" -eq 1 ] && break
  sleep 0.5
done

if [ "$api_ready" -ne 1 ] || [ "$static_ready" -ne 1 ]; then
  echo "[run_demo] ERROR: timed out waiting for servers to come up (30s)." >&2
  echo "--- query API log ---" >&2; cat "$API_LOG" >&2
  echo "--- static server log ---" >&2; cat "$STATIC_LOG" >&2
  exit 1
fi

echo ""
echo "Demo ready: http://127.0.0.1:$STATIC_PORT"
echo ""
echo "[run_demo] Ctrl+C to stop both servers."

# Wait on both background jobs; cleanup() runs automatically on Ctrl+C via the trap.
wait "$API_PID" "$STATIC_PID"
