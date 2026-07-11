from __future__ import annotations

import csv
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

try:
    from homeassistant.util.yaml import load_yaml
except ImportError:  # pragma: no cover - only used by standalone tests
    load_yaml = None

from .canalplus import CanalPlusProgramme, fetch_channel_schedule
from .epg_compare import (
    SECONDARY_FETCH_FAILED,
    GuideProgramme,
    ProgrammeComparison,
    compare_guides,
    guide_programme_from_open_epg,
)
from .scheduler import EpgProgramme

_LOGGER = logging.getLogger(__name__)


class CanalPlusScheduleClient(Protocol):
    def get_schedule(
        self,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict:
        ...


@dataclass(frozen=True)
class CanalPlusFetchError:
    channel_key: str
    channel_id: str
    start_at: datetime
    end_at: datetime
    message: str


@dataclass(frozen=True)
class CanalPlusComparisonReport:
    comparisons: list[ProgrammeComparison]
    counts: dict[str, int]
    rows_written: int = 0
    channel_count: int = 0
    primary_count: int = 0
    secondary_count: int = 0
    fetch_error_count: int = 0


def load_canalplus_channel_map(channels_file: str) -> dict[str, str]:
    channels = _load_channels_yaml(channels_file)
    channel_map: dict[str, str] = {}

    for channel_key, channel_config in channels.items():
        if not isinstance(channel_config, dict):
            continue

        canalplus_id = channel_config.get("canalplus_id")
        if canalplus_id:
            channel_map[str(channel_key)] = str(canalplus_id)

    return channel_map


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
    secondary, fetch_errors = _fetch_canalplus_programmes(
        primary,
        client,
        channel_map,
    )
    failed_channel_keys = {error.channel_key for error in fetch_errors}
    comparable_primary = [
        programme
        for programme in primary
        if programme.channel_key not in failed_channel_keys
    ]
    comparisons = compare_guides(comparable_primary, secondary)
    comparisons.extend(_fetch_error_comparisons(fetch_errors))
    counts = dict(Counter(comparison.kind for comparison in comparisons))

    rows_written = 0
    if report_file:
        rows_written = write_comparison_report(report_file, comparisons)

    return CanalPlusComparisonReport(
        comparisons=comparisons,
        counts=counts,
        rows_written=rows_written,
        channel_count=len(channel_map),
        primary_count=len(primary),
        secondary_count=len(secondary),
        fetch_error_count=len(fetch_errors),
    )


def _load_channels_yaml(channels_file: str) -> dict[str, object]:
    if load_yaml is not None:
        loaded = load_yaml(channels_file)
        return loaded if isinstance(loaded, dict) else {}

    return _load_simple_channels_yaml(channels_file)


def _load_simple_channels_yaml(channels_file: str) -> dict[str, object]:
    channels: dict[str, object] = {}
    current_key: str | None = None

    for raw_line in Path(channels_file).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if not raw_line.startswith(" ") and line.endswith(":"):
            current_key = line[:-1].strip()
            channels[current_key] = {}
            continue

        if current_key is None or not line.startswith("  ") or ":" not in line:
            continue

        key, value = line.strip().split(":", 1)
        if isinstance(channels[current_key], dict):
            channels[current_key][key.strip()] = value.strip().strip("\"'")

    return channels


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
                "note",
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
) -> tuple[list[GuideProgramme], list[CanalPlusFetchError]]:
    secondary: list[GuideProgramme] = []
    fetch_errors: list[CanalPlusFetchError] = []

    for channel_key, canalplus_channel_id in channel_map.items():
        channel_programmes = [
            programme for programme in primary if programme.channel_key == channel_key
        ]
        if not channel_programmes:
            continue

        start_at = min(programme.start_datetime for programme in channel_programmes)
        end_at = max(programme.end_datetime for programme in channel_programmes)
        _LOGGER.debug(
            "Fetching Canal+ schedule for %s (%s) from %s until %s",
            channel_key,
            canalplus_channel_id,
            start_at.isoformat(),
            end_at.isoformat(),
        )
        try:
            canalplus_programmes = fetch_channel_schedule(
                client,
                canalplus_channel_id,
                start_at,
                end_at,
            )
        except Exception as err:  # noqa: BLE001 - keep comparison report partial
            fetch_errors.append(
                CanalPlusFetchError(
                    channel_key=channel_key,
                    channel_id=canalplus_channel_id,
                    start_at=start_at,
                    end_at=end_at,
                    message=str(err),
                )
            )
            _LOGGER.warning(
                "Skipping Canal+ channel %s (%s) after schedule fetch failed "
                "for %s until %s: %s",
                channel_key,
                canalplus_channel_id,
                start_at.isoformat(),
                end_at.isoformat(),
                err,
            )
            continue

        _LOGGER.debug(
            "Fetched %s Canal+ programme(s) for %s",
            len(canalplus_programmes),
            channel_key,
        )
        for programme in canalplus_programmes:
            secondary.append(_guide_programme_from_canalplus(programme, channel_key))

    return secondary, fetch_errors


def _fetch_error_comparisons(
    fetch_errors: list[CanalPlusFetchError],
) -> list[ProgrammeComparison]:
    comparisons: list[ProgrammeComparison] = []
    for error in fetch_errors:
        comparisons.append(
            ProgrammeComparison(
                kind=SECONDARY_FETCH_FAILED,
                primary=GuideProgramme(
                    source="open_epg",
                    channel_key=error.channel_key,
                    title="",
                    start_datetime=error.start_at,
                    end_datetime=error.end_at,
                ),
                secondary=None,
                note=f"{error.channel_id}: {error.message}",
            )
        )
    return comparisons


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
        "note": comparison.note,
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
