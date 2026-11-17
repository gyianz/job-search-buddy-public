#!/usr/bin/env bash
# Double-click this file (macOS) to start the dashboard and open it in your
# browser. Close this window to stop it.
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
(
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
      open "http://127.0.0.1:$PORT/"
      exit 0
    fi
    sleep 1
  done
) &
echo "Starting Job Search Buddy at http://127.0.0.1:$PORT ..."
echo "(The first start installs a few things and can take a minute.)"
echo "Close this window to stop it."
echo
exec scripts/run_server.sh
