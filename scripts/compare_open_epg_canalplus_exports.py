#!/usr/bin/env python3
"""Compare exported Open EPG and Canal+ snapshots outside Home Assistant."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.tv_auto_scheduler.canalplus_compare import (
    build_export_comparison_report,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare an HA-exported Open EPG snapshot with a Canal+ snapshot.",
    )
    parser.add_argument("open_epg_export_file")
    parser.add_argument("canalplus_export_file")
    parser.add_argument(
        "--report-file",
        help="Optional CSV file where comparison rows are written.",
    )
    parser.add_argument(
        "--hide-matching-programmes",
        action="store_true",
        help="Exclude confirmed matching programmes from the result and optional CSV report.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    report = build_export_comparison_report(
        args.open_epg_export_file,
        args.canalplus_export_file,
        report_file=args.report_file,
        show_matching_programmes=not args.hide_matching_programmes,
    )

    print(
        json.dumps(
            {
                "counts": report.counts,
                "channel_count": report.channel_count,
                "primary_count": report.primary_count,
                "secondary_count": report.secondary_count,
                "comparison_count": len(report.comparisons),
                "report_file": args.report_file or "",
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())