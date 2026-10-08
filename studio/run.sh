#!/usr/bin/env bash
# One command to set up (first time) and start Footage Studio.
#   ./studio/run.sh               # http://localhost:3009
#   ./studio/run.sh --port 9000
#   ./studio/run.sh --beat        # also install beat detection (for cutting on the beat)
set -euo pipefail
cd "$(dirname "$0")"

BEAT=0
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--beat" ]; then BEAT=1; else ARGS+=("$arg"); fi
done

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "ffmpeg is not installed. Install it with:  brew install ffmpeg" >&2
  exit 1
fi

new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; }

# A venv left over from an older Python (e.g. a failed first run) is rebuilt.
if [ -e .venv ] && ! new_enough .venv/bin/python; then
  echo "Removing studio/.venv (built with an older Python) ..."
  rm -rf .venv
fi

# Python deps live in studio/.venv so they never touch the system Python.
if [ ! -x .venv/bin/python ]; then
  PY=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3.9 python3 \
              /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$cand" >/dev/null && new_enough "$cand"; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    found="$(python3 --version 2>&1 || echo 'no python3')"
    echo "Footage Studio needs Python 3.9+ (found: $found)." >&2
    echo "Install it with:  brew install python@3.12   then run this again." >&2
    exit 1
  fi
  echo "Creating Python environment in studio/.venv with $("$PY" --version) ..."
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Installing Python packages ..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  touch .venv/.installed
fi
# Beat detection (librosa) is optional and only installed with --beat. Ready-made
# packages only: never try to compile (llvmlite would need a full LLVM install).
if [ "$BEAT" = 1 ] && { [ ! -f .venv/.music-installed ] || [ requirements-music.txt -nt .venv/.music-installed ]; }; then
  echo "Installing beat detection ..."
  if .venv/bin/python -m pip install --only-binary=:all: -r requirements-music.txt > .venv/beat-install.log 2>&1; then
    touch .venv/.music-installed
  else
    echo "  Beat detection isn't available for this Python on this Mac (details: studio/.venv/beat-install.log)." >&2
    echo "  The studio works without it; cuts just won't snap to beats." >&2
  fi
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

# Put the terminal back as we found it when the server stops (Ctrl-C included),
# in case anything it ran left typing invisible.
if [ -t 0 ]; then
  TTY_STATE="$(stty -g)"
  trap 'stty "$TTY_STATE"' EXIT
  trap 'exit 130' INT TERM
fi
.venv/bin/python server.py --open ${ARGS[@]+"${ARGS[@]}"}
