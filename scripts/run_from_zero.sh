#!/usr/bin/env bash
set -euo pipefail
chmod 600 config.yaml || true
python3 orchestrate_from_zero.py
