from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .canalplus import CanalPlusProgramme, fetch_channel_schedule
from .epg_compare import (
    GuideProgramme,
    ProgrammeComparison,
    compare_guides,
    guide_programme_from_open_epg,
)
from .scheduler import EpgProgramme


class CanalPlusScheduleClient(Protocol):
    def get_schedule(
        self,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict:
        ...


@dataclass(frozen=True)
class CanalPlusComparisonReport:
    comparisons: list[ProgrammeComparison]
    counts: dict[str, int]
    rows_written: int = 0


def build_canalplus_comparison_report(
    open_epg_programmes: list[EpgProgramme],
    client: CanalPlusScheduleClient,
    channel_map: dict[str, str],
    *,
    report_file: str | None = None,
) -> CanalPlusComparisonReport:
    primary = [
        guide_programme_from_open_epg(programme)
        for programme in open_epg_programmes
        if programme.channel_key in channel_map
    ]
    secondary = _fetch_canalplus_programmes(primary, client, channel_map)
    comparisons = compare_guides(primary, secondary)
    counts = dict(Counter(comparison.kind for comparison in comparisons))

    rows_written = 0
    if report_file:
        rows_written = write_comparison_report(report_file, comparisons)

    return CanalPlusComparisonReport(
        comparisons=comparisons,
        counts=counts,
        rows_written=rows_written,
    )


def write_comparison_report(
    report_file: str,
    comparisons: list[ProgrammeComparison],
) -> int:
    path = Path(report_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "kind",
                "channel",
                "primary_title",
                "primary_start",
                "primary_end",
                "secondary_title",
                "secondary_start",
                "secondary_end",
                "start_delta_minutes",
                "end_delta_minutes",
            ],
        )
        writer.writeheader()
        for comparison in comparisons:
            writer.writerow(_comparison_row(comparison))

    return len(comparisons)


def _fetch_canalplus_programmes(
    primary: list[GuideProgramme],
    client: CanalPlusScheduleClient,
    channel_map: dict[str, str],
) -> list[GuideProgramme]:
    secondary: list[GuideProgramme] = []

    for channel_key, canalplus_channel_id in channel_map.items():
        channel_programmes = [
            programme for programme in primary if programme.channel_key == channel_key
        ]
        if not channel_programmes:
            continue

        start_at = min(programme.start_datetime for programme in channel_programmes)
        end_at = max(programme.end_datetime for programme in channel_programmes)
        for programme in fetch_channel_schedule(
            client,
            canalplus_channel_id,
            start_at,
            end_at,
        ):
            secondary.append(_guide_programme_from_canalplus(programme, channel_key))

    return secondary


def _guide_programme_from_canalplus(
    programme: CanalPlusProgramme,
    channel_key: str,
) -> GuideProgramme:
    return GuideProgramme(
        source="canalplus",
        channel_key=channel_key,
        title=programme.title,
        description=programme.description,
        start_datetime=programme.start,
        end_datetime=programme.end,
        provider_id=programme.programme_id,
    )


def _comparison_row(comparison: ProgrammeComparison) -> dict[str, object]:
    primary = comparison.primary
    secondary = comparison.secondary

    return {
        "kind": comparison.kind,
        "channel": _channel_key(primary, secondary),
        "primary_title": primary.title if primary else "",
        "primary_start": primary.start_datetime.isoformat() if primary else "",
        "primary_end": primary.end_datetime.isoformat() if primary else "",
        "secondary_title": secondary.title if secondary else "",
        "secondary_start": secondary.start_datetime.isoformat() if secondary else "",
        "secondary_end": secondary.end_datetime.isoformat() if secondary else "",
        "start_delta_minutes": comparison.start_delta_minutes,
        "end_delta_minutes": comparison.end_delta_minutes,
    }


def _channel_key(
    primary: GuideProgramme | None,
    secondary: GuideProgramme | None,
) -> str:
    if primary is not None:
        return primary.channel_key
    if secondary is not None:
        return secondary.channel_key
    return ""
