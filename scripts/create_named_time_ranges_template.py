#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path, PurePosixPath

DEFAULT_ROWS = [
    {
        "key": "primetime",
        "filter-start-day": "",
        "filter-start-time": "20:00",
        "filter-end-time": "22:00",
    },
    {
        "key": "primetime_week",
        "filter-start-day": "mon-fri",
        "filter-start-time": "20:00",
        "filter-end-time": "22:00",
    },
    {
        "key": "late_night_weekend",
        "filter-start-day": "sat-sun",
        "filter-start-time": "22:30",
        "filter-end-time": "01:30",
    },
]

FIELDNAMES = [
    "key",
    "filter-start-day",
    "filter-start-time",
    "filter-end-time",
]


def build_default_named_time_ranges_path(rules_file: str) -> str:
    if "/" in rules_file and "\\" not in rules_file:
        return str(PurePosixPath(rules_file).with_name("named_time_ranges.csv"))

    return str(Path(rules_file).with_name("named_time_ranges.csv"))


def create_named_time_ranges_template(
    output_file: str,
    *,
    overwrite: bool = False,
) -> bool:
    path = Path(output_file)

    if path.exists() and not overwrite:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(DEFAULT_ROWS)

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a starter named_time_ranges.csv file for TV Auto Scheduler.",
    )
    parser.add_argument(
        "output_file",
        nargs="?",
        help="Path to named_time_ranges.csv. If omitted, provide --rules-file.",
    )
    parser.add_argument(
        "--rules-file",
        help="Use the directory of this rules.csv file to resolve named_time_ranges.csv automatically.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing named_time_ranges.csv file.",
    )
    args = parser.parse_args()

    output_file = args.output_file
    if output_file is None:
        if not args.rules_file:
            parser.error("provide output_file or --rules-file")
        output_file = build_default_named_time_ranges_path(args.rules_file)

    created = create_named_time_ranges_template(
        output_file,
        overwrite=args.overwrite,
    )

    if created:
        print(f"Created named time ranges template: {output_file}")
        return 0

    print(f"named_time_ranges.csv already exists: {output_file}")
    print("Use --overwrite to replace it.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
