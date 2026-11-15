#!/usr/bin/env bash
# QNX Integration Advisor - one-command launcher for Linux, WSL2 and macOS.
# First run: creates a private Python environment in .venv and installs the tool (needs internet).
# Every run: starts the local web UI and opens it in your browser. Press Ctrl+C to stop.
# With QNX SDP 8.0: run `source ~/qnx800/qnxsdp-env.sh` first and results are verified against your sysroot.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
VENV=.venv
# The same folder opened from Windows and from WSL (QNX mode): keep the Linux environment in the WSL home,
# separate from the Windows one and out of synced folders such as OneDrive.
if [ -d .venv/Scripts ]; then VENV="$HOME/.qnx-advisor/venv"; mkdir -p "$HOME/.qnx-advisor"; fi
# Load the QNX SDP automatically when it is installed in the usual place.
if [ -z "${QNX_HOST:-}" ]; then
  for f in "$HOME"/qnx*/qnxsdp-env.sh; do
    if [ -f "$f" ]; then . "$f" >/dev/null; break; fi
  done
fi

echo
echo "  QNX Integration Advisor"
echo "  -----------------------"

# 1. Python environment (first run only)
if [ ! -x "$VENV/bin/python" ]; then
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
  "$PY" -m venv "$VENV" || { echo "  On Ubuntu you may need: sudo apt install python3-venv" >&2; exit 1; }
fi

# 2. Install or update the tool when pyproject.toml has changed
HASH="$("$VENV/bin/python" -c 'import hashlib;print(hashlib.sha256(open("pyproject.toml","rb").read()).hexdigest())')"
if [ "$(cat "$VENV/.installed" 2>/dev/null || true)" != "$HASH+llm" ]; then
  echo "  Installing the tool and its dependencies - this takes a minute the first time ..."
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q --upgrade pip >/dev/null 2>&1 || true
  if [ "$VENV" = .venv ]; then
    "$VENV/bin/python" -m pip install --disable-pip-version-check -q -e ".[llm]"
  else
    # A Windows folder seen from WSL: install only the dependencies (packaging cannot write metadata there);
    # the advisor itself runs straight from this folder with python -m.
    "$VENV/bin/python" -c 'import tomllib; p = tomllib.load(open("pyproject.toml", "rb"))["project"]; print(chr(10).join(p["dependencies"] + p["optional-dependencies"]["llm"]))' > "$VENV/requirements.txt"
    "$VENV/bin/python" -m pip install --disable-pip-version-check -q -r "$VENV/requirements.txt"
  fi
  echo "$HASH+llm" > "$VENV/.installed"
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
if [ -n "${QNX_HOST:-}" ]; then
  echo "  QNX SDP detected: $QNX_HOST"
  # First run with the SDP: index its headers and libraries so every recommendation is checked against it.
  if ! ls "$HOME"/.qnx-advisor/sysroot-index-*.json >/dev/null 2>&1; then
    echo "  Indexing your QNX SDP (first time only, about a minute) ..."
    "$VENV/bin/python" -m advisor.cli index-sdp || echo "  Indexing failed; results will be marked unverified."
  fi
fi
OPEN="--open"; [ "${QNX_ADVISOR_NO_OPEN:-}" = 1 ] && OPEN=""
echo "  Starting on http://127.0.0.1:$PORT - your browser will open shortly. Press Ctrl+C to stop."
echo
exec "$VENV/bin/python" -m advisor.cli serve --port "$PORT" $OPEN
