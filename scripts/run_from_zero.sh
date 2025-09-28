#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# pakai venv kalau ada
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

chmod 600 config.yaml 2>/dev/null || true
"$PY" orchestrate_from_zero.py
