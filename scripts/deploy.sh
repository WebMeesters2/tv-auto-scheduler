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
SOURCE_EXAMPLE_NAMED_TIME_RANGES="$SOURCE_ROOT/examples/named_time_ranges.csv"
SOURCE_EXAMPLE_CHANNELS="$SOURCE_ROOT/examples/channels.yaml"
SOURCE_CANALPLUS_SCRIPT="$SOURCE_ROOT/examples/canalplus_compare_script.yaml"
SOURCE_RULES_MIGRATOR="$SOURCE_ROOT/scripts/migrate_rules_csv.py"
SOURCE_NAMED_TIME_RANGES_TEMPLATE="$SOURCE_ROOT/scripts/create_named_time_ranges_template.py"
TARGET_RULES_DIR="$HA_CONFIG_DIR/tv_auto_scheduler"
TARGET_TV_DIR="$HA_CONFIG_DIR/tv"
TARGET_RULES="$TARGET_RULES_DIR/rules.csv"
TARGET_NAMED_TIME_RANGES="$TARGET_RULES_DIR/named_time_ranges.csv"
TARGET_CHANNELS="$TARGET_TV_DIR/channels.yaml"
TARGET_CANALPLUS_SCRIPT="$TARGET_RULES_DIR/canalplus_compare_script.yaml"
TARGET_RULES_MIGRATOR="$TARGET_RULES_DIR/migrate_rules_csv.py"
TARGET_NAMED_TIME_RANGES_TEMPLATE="$TARGET_RULES_DIR/create_named_time_ranges_template.py"

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
  echo "DRY-RUN: would synchronize $TARGET_INTEGRATION"
else
  mkdir -p "$TARGET_INTEGRATION"
  rsync -a --delete --delete-excluded \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '*.pyc' \
    "$SOURCE_INTEGRATION/" \
    "$TARGET_INTEGRATION/"
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

if [[ -f "$SOURCE_EXAMPLE_NAMED_TIME_RANGES" ]]; then
  if [[ -f "$TARGET_NAMED_TIME_RANGES" ]]; then
    echo "Named time ranges file already exists, leaving it untouched:"
    echo "  $TARGET_NAMED_TIME_RANGES"
  else
    echo "Installing initial named time ranges file:"
    echo "  $TARGET_NAMED_TIME_RANGES"

    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "DRY-RUN: named time ranges copy skipped"
    else
      mkdir -p "$TARGET_RULES_DIR"
      cp "$SOURCE_EXAMPLE_NAMED_TIME_RANGES" "$TARGET_NAMED_TIME_RANGES"
    fi
  fi
fi

if [[ -f "$SOURCE_EXAMPLE_CHANNELS" ]]; then
  if [[ -f "$TARGET_CHANNELS" ]]; then
    echo "Channel database already exists, leaving it untouched:"
    echo "  $TARGET_CHANNELS"
    echo "  Merge canalplus_id values from examples/channels.yaml when needed."
  else
    echo "Installing initial channel database:"
    echo "  $TARGET_CHANNELS"

    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "DRY-RUN: channel database copy skipped"
    else
      mkdir -p "$TARGET_TV_DIR"
      cp "$SOURCE_EXAMPLE_CHANNELS" "$TARGET_CHANNELS"
    fi
  fi
fi

if [[ -f "$SOURCE_CANALPLUS_SCRIPT" ]]; then
  echo
  echo "Deploying Canal+ script example:"
  echo "  $TARGET_CANALPLUS_SCRIPT"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN: Canal+ script example copy skipped"
  else
    mkdir -p "$TARGET_RULES_DIR"
    cp "$SOURCE_CANALPLUS_SCRIPT" "$TARGET_CANALPLUS_SCRIPT"
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

if [[ -f "$SOURCE_NAMED_TIME_RANGES_TEMPLATE" ]]; then
  echo
  echo "Deploying named time ranges utility:"
  echo "  $TARGET_NAMED_TIME_RANGES_TEMPLATE"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN: named time ranges utility copy skipped"
  else
    mkdir -p "$TARGET_RULES_DIR"
    cp "$SOURCE_NAMED_TIME_RANGES_TEMPLATE" "$TARGET_NAMED_TIME_RANGES_TEMPLATE"
    chmod +x "$TARGET_NAMED_TIME_RANGES_TEMPLATE"
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
