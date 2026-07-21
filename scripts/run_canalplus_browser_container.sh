#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(dirname "$SCRIPT_DIR")"

IMAGE_NAME="tv-auto-scheduler-canalplus-browser"

docker build -f "$SOURCE_ROOT/addons/canalplus-browser/Dockerfile" -t "$IMAGE_NAME" "$SOURCE_ROOT"

exec docker run --rm -it \
  -v "$SOURCE_ROOT:/workspace" \
  -v "${HOME}/.cache/tv-auto-scheduler:/root/.cache/tv-auto-scheduler" \
  -e HOME=/root \
  "$IMAGE_NAME" python /workspace/scripts/canalplus_poc.py "$@"