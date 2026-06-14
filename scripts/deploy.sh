#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(dirname "$SCRIPT_DIR")"

INTEGRATION_NAME="tv_auto_scheduler"

HA_SSH_HOST="${HA_SSH_HOST:-jeeves}"
HA_CONFIG_DIR="${HA_CONFIG_DIR:-/mnt/ha-config}"

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
TARGET_CUSTOM_COMPONENTS_DIR="$HA_CONFIG_DIR/custom_components"
TARGET_INTEGRATION="$TARGET_CUSTOM_COMPONENTS_DIR/$INTEGRATION_NAME"

SOURCE_EXAMPLE_RULES="$SOURCE_ROOT/examples/tv-rules.csv"
SOURCE_RULES_MIGRATOR="$SOURCE_ROOT/scripts/migrate_rules_csv.py"
TARGET_RULES_DIR="$HA_CONFIG_DIR/tv_auto_scheduler"
TARGET_RULES="$TARGET_RULES_DIR/rules.csv"
TARGET_RULES_MIGRATOR="$TARGET_RULES_DIR/migrate_rules_csv.py"

if [[ ! -d "$SOURCE_INTEGRATION" ]]; then
  echo "Source integration folder not found: $SOURCE_INTEGRATION" >&2
  exit 1
fi

if [[ ! -d "$HA_CONFIG_DIR" ]]; then
  echo "Home Assistant config mount not found: $HA_CONFIG_DIR" >&2
  echo "Mount the Samba share first, for example at /mnt/ha-config." >&2
  exit 1
fi

echo "Deploying $INTEGRATION_NAME..."
echo "Source: $SOURCE_ROOT"
echo "Target: $HA_CONFIG_DIR"
echo

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY-RUN: would recreate $TARGET_INTEGRATION"
else
  mkdir -p "$TARGET_CUSTOM_COMPONENTS_DIR"
  rm -rf "$TARGET_INTEGRATION"
  cp -a "$SOURCE_INTEGRATION" "$TARGET_CUSTOM_COMPONENTS_DIR/"
fi

if [[ -f "$SOURCE_EXAMPLE_RULES" ]]; then
  if [[ -f "$TARGET_RULES" ]]; then
    echo "Rules file already exists, leaving it untouched:"
    echo "  $TARGET_RULES"
  else
    echo "Installing initial rules file:"
    echo "  $TARGET_RULES"

    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "DRY-RUN: rules copy skipped"
    else
      mkdir -p "$TARGET_RULES_DIR"
      cp "$SOURCE_EXAMPLE_RULES" "$TARGET_RULES"
    fi
  fi
fi

if [[ -f "$SOURCE_RULES_MIGRATOR" ]]; then
  echo
  echo "Deploying rules utility:"
  echo "  $TARGET_RULES_MIGRATOR"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN: rules utility copy skipped"
  else
    mkdir -p "$TARGET_RULES_DIR"
    cp "$SOURCE_RULES_MIGRATOR" "$TARGET_RULES_MIGRATOR"
    chmod +x "$TARGET_RULES_MIGRATOR"
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
