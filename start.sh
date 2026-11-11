#!/usr/bin/env bash
# QNX Integration Advisor - one-command launcher for Linux, WSL2 and macOS.
# First run: creates a private Python environment in .venv and installs the tool (needs internet).
# Every run: starts the local web UI and opens it in your browser. Press Ctrl+C to stop.
# With QNX SDP 8.0: run `source ~/qnx800/qnxsdp-env.sh` first and results are verified against your sysroot.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8765}"

echo
echo "  QNX Integration Advisor"
echo "  -----------------------"

# 1. Python environment (first run only)
if [ ! -x .venv/bin/python ]; then
  PY=""
  for c in python3.13 python3.12 python3.14 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "  Python 3.11 or newer is required. On Ubuntu: sudo apt install python3 python3-venv" >&2
    exit 1
  fi
  echo "  First run: creating a Python environment with $PY ..."
  "$PY" -m venv .venv || { echo "  On Ubuntu you may need: sudo apt install python3-venv" >&2; exit 1; }
fi

# 2. Install or update the tool when pyproject.toml has changed
HASH="$(.venv/bin/python -c 'import hashlib;print(hashlib.sha256(open("pyproject.toml","rb").read()).hexdigest())')"
if [ "$(cat .venv/.installed 2>/dev/null || true)" != "$HASH+llm" ]; then
  echo "  Installing the tool and its dependencies - this takes a minute the first time ..."
  .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip >/dev/null 2>&1 || true
  .venv/bin/python -m pip install --disable-pip-version-check -q -e ".[llm]"
  echo "$HASH+llm" > .venv/.installed
fi

# 3. Web UI (shipped pre-built in advisor/static; rebuilt only if missing and Node is present)
if [ ! -f advisor/static/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "  Building the web UI ..."
    (cd web && npm ci --silent && npm run build --silent)
  else
    echo "  The web UI files (advisor/static) are missing and Node.js is not installed to rebuild them." >&2
    exit 1
  fi
fi

# 4. Run
if [ -n "${QNX_HOST:-}" ]; then echo "  QNX SDP detected: $QNX_HOST"; fi
echo "  Starting on http://127.0.0.1:$PORT - your browser will open shortly. Press Ctrl+C to stop."
echo
exec .venv/bin/python -m advisor.cli serve --port "$PORT" --open
