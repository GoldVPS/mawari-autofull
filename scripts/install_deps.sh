#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

apt-get update
apt-get install -y python3-venv python3-pip

# venv biar aman dari PEP 668
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
pip install -r requirements.txt

# Docker (pakai paket distro agar cepat/sederhana)
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y docker.io
  systemctl enable --now docker
fi

echo "✅ Dependencies ready. Next: isi config.yaml lalu pilih menu 3."
