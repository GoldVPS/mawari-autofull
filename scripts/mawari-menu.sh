#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/mawari-autofull}"
CONTAINER="mawari_worker1"

banner() { echo -e "\n==== $* ====\n"; }

choose() {
  echo "1) Install dependencies"
  echo "2) Edit config.yaml"
  echo "3) Run orchestrate (from zero)"
  echo "4) Show container logs (follow)"
  echo "5) Restart container"
  echo "6) Stop container"
  echo "7) Start container"
  echo "8) Backup burner cache"
  echo "9) Exit"
  echo -n "Choice: "
}

main() {
  while true; do
    choose
    read -r c
    case "$c" in
      1) banner "Install dependencies"; bash "$REPO_DIR/scripts/install_deps.sh" ;;
      2) banner "Edit config.yaml";     ${EDITOR:-nano} "$REPO_DIR/config.yaml" ;;
      3) banner "Run orchestrate_from_zero.py"; bash "$REPO_DIR/scripts/run_from_zero.sh" ;;
      4) banner "Docker logs (Ctrl+C to exit)"; docker logs -f --tail=200 "$CONTAINER" || echo "Container not found." ;;
      5) banner "Docker restart"; docker restart "$CONTAINER" || echo "Container not found." ;;
      6) banner "Docker stop";    docker stop "$CONTAINER"    || echo "Container not found." ;;
      7) banner "Docker start";   docker start "$CONTAINER"   || echo "Container not found." ;;
      8)
        banner "Backup burner cache"
        SRC="$HOME/.mawari_automation/workers/worker1/cache/flohive-cache.json"
        DST="$HOME/flohive-cache.json.bak"
        if [ -f "$SRC" ]; then cp "$SRC" "$DST" && echo "Backed up to $DST"; else echo "Cache not found at $SRC"; fi
        ;;
      9) exit 0 ;;
      *) echo "invalid";;
    esac
  done
}

main
