#!/usr/bin/env bash
# Start Master Smith on Linux/macOS: the containers, then the browser.  ./scripts/start.sh [--build] [--down]
set -e
cd "$(dirname "$0")/.."
case "${1:-}" in
  --down) docker compose down; exit 0 ;;
  --build) docker compose up -d --build ;;
  *) docker compose up -d ;;
esac
[ -f .env ] || { echo "No .env yet: copy .env.example to .env and put your keys in it."; exit 1; }
for i in $(seq 1 60); do curl -fs http://localhost:8080/healthz >/dev/null 2>&1 && break; sleep 2; done
curl -s http://localhost:8080/healthz; echo
(xdg-open http://localhost:3000 2>/dev/null || open http://localhost:3000 2>/dev/null || true)
docker compose ps
