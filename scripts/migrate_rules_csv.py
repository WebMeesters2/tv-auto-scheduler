#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path, PurePosixPath

TARGET_FIELDS = [
    "enabled",
    "channel",
    "programme",
    "pre",
    "tv",
    "flag-delete-after-use",
    "filter-start-day",
    "filter-start-time",
    "filter-end-time",
]

FIELD_DEFAULTS = {
    "enabled": "y",
    "channel": "",
    "programme": "",
    "pre": "n",
    "tv": "n",
    "flag-delete-after-use": "n",
    "filter-start-day": "",
    "filter-start-time": "",
    "filter-end-time": "",
}


def validate_rules_file(rules_file: str) -> list[str]:
    path = Path(rules_file)
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_file}")

    issues: list[str] = []

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        existing_fields = reader.fieldnames or []
        rows = list(reader)

    missing_fields = [field for field in TARGET_FIELDS if field not in existing_fields]
    if missing_fields:
        issues.append(f"Missing columns: {', '.join(missing_fields)}")

    duplicate_fields = _find_duplicates(existing_fields)
    if duplicate_fields:
        issues.append(f"Duplicate columns: {', '.join(duplicate_fields)}")

    blank_header_positions = [
        str(index + 1) for index, field in enumerate(existing_fields) if not field
    ]
    if blank_header_positions:
        issues.append(
            "Blank header columns at positions: "
            + ", ".join(blank_header_positions)
        )

    for row_number, row in enumerate(rows, start=2):
        if None in row:
            extra_values = [value for value in row[None] if value]
            if extra_values:
                issues.append(
                    f"Row {row_number} has extra values beyond the header: "
                    + ", ".join(extra_values)
                )

    return issues


def migrate_rules_file(
    rules_file: str,
    *,
    create_backup: bool = True,
    dry_run: bool = False,
) -> tuple[bool, Path | None]:
    path = Path(rules_file)
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_file}")

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        existing_fields = reader.fieldnames or []
        rows = list(reader)

    extra_fields = [
        field for field in existing_fields if field and field not in TARGET_FIELDS
    ]
    final_fields = TARGET_FIELDS + extra_fields

    migrated_rows: list[dict[str, str]] = []
    for row in rows:
        migrated_row = {}
        for field in final_fields:
            value = row.get(field)
            migrated_row[field] = "" if value is None else str(value)

        for field, default in FIELD_DEFAULTS.items():
            if migrated_row[field] == "":
                if field in existing_fields:
                    continue
                migrated_row[field] = default

        migrated_rows.append(migrated_row)

    changed = existing_fields != final_fields

    if not changed:
        for row, migrated_row in zip(rows, migrated_rows, strict=False):
            for field in final_fields:
                original = row.get(field)
                normalized = "" if original is None else str(original)
                if normalized != migrated_row[field]:
                    changed = True
                    break
            if changed:
                break

    backup_path: Path | None = None
    if not changed or dry_run:
        return changed, backup_path

    if create_backup:
        backup_path = _build_backup_path(path)
        if backup_path.exists():
            raise FileExistsError(f"Backup file already exists: {backup_path}")
        backup_path.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=final_fields)
        writer.writeheader()
        writer.writerows(migrated_rows)

    return changed, backup_path


def _build_backup_path(path: Path) -> Path:
    if "/" in str(path) and "\\" not in str(path):
        return Path(str(PurePosixPath(str(path)).with_suffix(path.suffix + ".bak")))

    return path.with_suffix(path.suffix + ".bak")


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []

    for value in values:
        if not value:
            continue
        if value in seen and value not in duplicates:
            duplicates.append(value)
            continue
        seen.add(value)

    return duplicates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Insert missing TV Auto Scheduler rules.csv columns safely.",
    )
    parser.add_argument("rules_file", help="Path to rules.csv")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip writing a .bak backup file before migrating.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report whether a migration is needed without rewriting the file.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the current rules.csv structure without rewriting it.",
    )
    args = parser.parse_args()

    if args.validate:
        issues = validate_rules_file(args.rules_file)
        if not issues:
            print("rules.csv is valid.")
            return 0

        print("rules.csv validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    changed, backup_path = migrate_rules_file(
        args.rules_file,
        create_backup=not args.no_backup,
        dry_run=args.dry_run,
    )

    if not changed:
        print("rules.csv is already up to date.")
        return 0

    if args.dry_run:
        print("rules.csv requires migration.")
        return 0

    if backup_path is not None:
        print(f"Backup written to: {backup_path}")
    print(f"Migrated rules file: {args.rules_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
