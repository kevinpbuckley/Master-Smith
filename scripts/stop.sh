#!/usr/bin/env bash
# Tear Master Smith down; the data volume stays.  ./scripts/stop.sh [--wipe]  (--wipe also deletes the volume)
set -e
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--wipe" ]; then docker compose down -v; else docker compose down; fi
docker compose ps
