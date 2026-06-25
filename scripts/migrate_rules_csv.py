#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path, PurePosixPath

TARGET_FIELDS = [
    "rule-id",
    "enabled",
    "channel",
    "programme",
    "pre",
    "tv",
    "flag-delete-after-use",
    "named-time-range",
    "filter-start-day",
    "filter-start-time",
    "filter-end-time",
]

FIELD_DEFAULTS = {
    "rule-id": "",
    "enabled": "y",
    "channel": "",
    "programme": "",
    "pre": "n",
    "tv": "n",
    "flag-delete-after-use": "n",
    "named-time-range": "",
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
        reader = csv.DictReader(io.StringIO(_prepare_csv_text(file.readlines())))
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

    seen_rule_ids: set[int] = set()
    duplicate_rule_ids: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        parsed_rule_id = _try_parse_positive_int((row.get("rule-id") or "").strip())
        if parsed_rule_id is None:
            continue
        if parsed_rule_id in seen_rule_ids:
            duplicate_rule_ids.append(f"{parsed_rule_id} (row {row_number})")
            continue
        seen_rule_ids.add(parsed_rule_id)

    if duplicate_rule_ids:
        issues.append("Duplicate rule-id values: " + ", ".join(duplicate_rule_ids))

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
        reader = csv.DictReader(io.StringIO(_prepare_csv_text(file.readlines())))
        existing_fields = reader.fieldnames or []
        rows = list(reader)

    extra_fields = [
        field for field in existing_fields if field and field not in TARGET_FIELDS
    ]
    final_fields = TARGET_FIELDS + extra_fields

    migrated_rows: list[dict[str, str]] = []
    used_rule_ids = _collect_existing_rule_ids(rows, existing_fields)
    next_rule_id = max(used_rule_ids, default=0) + 1
    for row in rows:
        migrated_row = _normalize_rules_csv_row(row, existing_fields)
        for field in final_fields:
            value = migrated_row.get(field, row.get(field))
            migrated_row[field] = "" if value is None else str(value)

        for field, default in FIELD_DEFAULTS.items():
            if migrated_row[field] == "":
                if field in existing_fields:
                    continue
                migrated_row[field] = default

        parsed_rule_id = _try_parse_positive_int(migrated_row["rule-id"])
        if parsed_rule_id is None:
            parsed_rule_id = next_rule_id
            while parsed_rule_id in used_rule_ids:
                parsed_rule_id += 1
            migrated_row["rule-id"] = str(parsed_rule_id)

        used_rule_ids.add(parsed_rule_id)
        next_rule_id = max(next_rule_id, parsed_rule_id + 1)
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

    _write_compact_csv_rows(path, final_fields, migrated_rows)

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


def _try_parse_positive_int(value: str) -> int | None:
    if not value:
        return None

    try:
        parsed = int(value)
    except ValueError:
        return None

    return parsed if parsed > 0 else None


def _normalize_rules_csv_row(
    row: dict[str, str | None],
    existing_fields: list[str],
) -> dict[str, str]:
    normalized_row = {
        field: "" if row.get(field) is None else str(row.get(field))
        for field in existing_fields
        if field
    }

    if not _looks_like_shifted_rule_id_row(normalized_row):
        return normalized_row

    ordered_values = [normalized_row.get(field, "") for field in TARGET_FIELDS]
    shifted_values = [""] + ordered_values[:-1]

    for field, value in zip(TARGET_FIELDS, shifted_values, strict=False):
        normalized_row[field] = value

    return normalized_row


def _prepare_csv_text(lines: list[str]) -> str:
    prepared_lines: list[str] = []

    for line in lines:
        cleaned_line = _strip_inline_comment(line).strip()
        if not cleaned_line:
            continue
        prepared_lines.append(cleaned_line)

    return "\n".join(prepared_lines)


def _strip_inline_comment(line: str, marker: str = "#") -> str:
    in_quotes = False
    index = 0

    while index < len(line):
        char = line[index]
        if char == '"':
            if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif char == marker and not in_quotes:
            return line[:index]
        index += 1

    return line


def _write_compact_csv_rows(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(fieldnames)

        for row in rows:
            values = ["" if row.get(field) is None else str(row.get(field)) for field in fieldnames]
            while values and values[-1] == "":
                values.pop()
            writer.writerow(values)


def _collect_existing_rule_ids(
    rows: list[dict[str, str | None]],
    existing_fields: list[str],
) -> set[int]:
    existing_rule_ids: set[int] = set()

    for row in rows:
        normalized_row = _normalize_rules_csv_row(row, existing_fields)
        parsed_rule_id = _try_parse_positive_int(normalized_row.get("rule-id", ""))
        if parsed_rule_id is not None:
            existing_rule_ids.add(parsed_rule_id)

    return existing_rule_ids


def _looks_like_shifted_rule_id_row(row: dict[str, str]) -> bool:
    rule_id_value = row.get("rule-id", "").strip().lower()
    enabled_value = row.get("enabled", "").strip().lower()

    if not rule_id_value or _try_parse_positive_int(rule_id_value) is not None:
        return False

    if rule_id_value not in {"1", "true", "yes", "y", "ja", "j", "0", "false", "no", "n", "nee"}:
        return False

    return enabled_value not in {"1", "true", "yes", "y", "ja", "j", "0", "false", "no", "n", "nee"}


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
