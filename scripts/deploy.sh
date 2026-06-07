#!/usr/bin/env bash

set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

INTEGRATION_NAME="tv_auto_scheduler"

HA_SSH_HOST="${HA_SSH_HOST:-jeeves}"
HA_CONFIG_ROOT="${HA_CONFIG_ROOT:-/config}"

DRY_RUN=0
RESTART_HA=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --restart-ha)
      RESTART_HA=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

SOURCE_INTEGRATION="$SOURCE_ROOT/custom_components/$INTEGRATION_NAME"
TARGET_INTEGRATION="$HA_CONFIG_ROOT/custom_components/$INTEGRATION_NAME"

SOURCE_EXAMPLE_RULES="$SOURCE_ROOT/examples/tv-rules.csv"
TARGET_RULES_DIR="$HA_CONFIG_ROOT/tv_auto_scheduler"
TARGET_RULES="$TARGET_RULES_DIR/rules.csv"

if [[ ! -d "$SOURCE_INTEGRATION" ]]; then
  echo "Source integration folder not found: $SOURCE_INTEGRATION" >&2
  exit 1
fi

echo "Deploying $INTEGRATION_NAME..."
echo "Source: $SOURCE_ROOT"
echo "Target: $HA_SSH_HOST:$HA_CONFIG_ROOT"
echo

RSYNC_FLAGS=(-av --delete --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.pyc')

if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_FLAGS+=(--dry-run)
fi

rsync "${RSYNC_FLAGS[@]}" \
  "$SOURCE_INTEGRATION/" \
  "$HA_SSH_HOST:$TARGET_INTEGRATION/"

echo

if [[ -f "$SOURCE_EXAMPLE_RULES" ]]; then
  if ssh "$HA_SSH_HOST" "test -f '$TARGET_RULES'"; then
    echo "Rules file already exists, leaving it untouched:"
    echo "  $TARGET_RULES"
  else
    echo "Installing initial rules file:"
    echo "  $TARGET_RULES"

    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "DRY-RUN: rules copy skipped"
    else
      ssh "$HA_SSH_HOST" "mkdir -p '$TARGET_RULES_DIR'"
      scp "$SOURCE_EXAMPLE_RULES" "$HA_SSH_HOST:$TARGET_RULES"
    fi
  fi
fi

echo
echo "Deploy complete."

if [[ "$RESTART_HA" -eq 1 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN: Home Assistant restart skipped"
  else
    echo "Restarting Home Assistant..."
    ssh "$HA_SSH_HOST" "ha core restart"
  fi
else
  echo "Restart Home Assistant or reload custom integrations if applicable."
fi