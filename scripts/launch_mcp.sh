#!/usr/bin/env bash
# Launcher script to start the MCP server using the project's virtualenv.
# Usage: scripts/launch_mcp.sh

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${HERE%/scripts}"
VENV_BIN="$REPO_ROOT/.venv/bin"

if [ ! -x "$VENV_BIN/uvicorn" ]; then
  echo "uvicorn not found in $VENV_BIN. Activate venv and install requirements first." >&2
  exit 2
fi

# Ensure imports resolve by adding repo root to PYTHONPATH and cd to repo root.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
cd "$REPO_ROOT"

# Exec uvicorn without printing to stdout (avoid non-JSON output for stdio transports).
exec "$VENV_BIN/uvicorn" "mcp.server:app" --host 127.0.0.1 --port 8000
