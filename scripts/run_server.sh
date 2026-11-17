#!/usr/bin/env bash
# Start the job-search dashboard, creating the virtualenv on first run.
#
# Usage: scripts/run_server.sh [extra uvicorn args]
#   HOST / PORT override the bind address (default 127.0.0.1:8000).
#   JSB_DB_PATH overrides the database path (default data/app.db).
#   PYTHON picks the interpreter used to create .venv (must be 3.10+).
set -euo pipefail

cd "$(dirname "$0")/.."

is_supported() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null
}

if [[ ! -x .venv/bin/uvicorn ]] || ! is_supported .venv/bin/python; then
  python_bin=""
  for candidate in ${PYTHON:-python3.14 python3.13 python3.12 python3.11 python3.10 python3}; do
    if command -v "$candidate" >/dev/null && is_supported "$candidate"; then
      python_bin="$candidate"
      break
    fi
  done
  if [[ -z "$python_bin" ]]; then
    echo "Error: Python 3.10+ is required, but none was found." >&2
    echo "Install one (e.g. 'brew install python@3.12') and re-run." >&2
    exit 1
  fi

  echo "Setting up .venv with $python_bin..."
  "$python_bin" -m venv --clear .venv
  .venv/bin/pip install -r requirements.txt
fi

# First run: start from the example profile so every page has something to show.
if [[ ! -f profile/profile.md && -z "${JSB_PROFILE_PATH:-}" ]]; then
  cp profile/profile.example.md profile/profile.md
  echo "Created profile/profile.md from the example. Fill it in on the Profile page."
fi
mkdir -p jobs data

exec .venv/bin/uvicorn app.main:create_app --factory --reload \
  --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
