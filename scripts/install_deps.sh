#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3-pip docker.io
python3 -m pip install --user -r requirements.txt
echo "Done. Next: edit config.yaml then run scripts/run_from_zero.sh"
