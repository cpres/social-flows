#!/usr/bin/env bash
# One command to set up (first time) and start Footage Studio.
#   ./studio/run.sh               # http://localhost:3009
#   ./studio/run.sh --port 9000
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "ffmpeg is not installed. Install it with:  brew install ffmpeg" >&2
  exit 1
fi

# Python deps live in studio/.venv so they never touch the system Python.
if [ ! -x .venv/bin/python ]; then
  echo "Creating Python environment in studio/.venv ..."
  python3 -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Installing Python packages ..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  touch .venv/.installed
fi

# Build the web app when it's missing or the source changed.
if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html -print -quit)" ]; then
  if ! command -v npm >/dev/null; then
    echo "Node.js is needed to build the app once. Install it with:  brew install node" >&2
    exit 1
  fi
  echo "Building the web app ..."
  (cd web && { [ -d node_modules ] && [ node_modules -nt package.json ] || npm install --silent; } && npm run build --silent)
fi

exec .venv/bin/python server.py --open "$@"
