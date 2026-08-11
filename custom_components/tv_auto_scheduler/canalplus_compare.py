from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

try:
    from homeassistant.util.yaml import load_yaml
except ImportError:  # pragma: no cover - only used by standalone tests
    load_yaml = None

from .canalplus import CanalPlusProgramme, fetch_channel_schedule
from .epg_compare import (
    CONFIRMED,
    SECONDARY_FETCH_FAILED,
    GuideProgramme,
    ProgrammeComparison,
    compare_guides,
    guide_programme_from_open_epg,
    guide_programme_from_canalplus_row,
)
from .scheduler import EpgProgramme, build_event_summary

_LOGGER = logging.getLogger(__name__)


def sanitize_canalplus_authorization(authorization: str) -> str:
    cleaned = authorization.strip().strip("\"'")
    if not cleaned:
        return ""

    # Prefer extracting a JWT-like token when copy/paste includes extra text.
    jwt_matches = re.findall(
        r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        cleaned,
    )
    if jwt_matches:
        return f"Bearer {jwt_matches[-1]}"

    cleaned = re.sub(
        r"^(authorization|auth|token)\s*[:=]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(bearer\s+)+", "", cleaned, flags=re.IGNORECASE)
    token = cleaned.split()[-1] if cleaned.split() else ""
    return f"Bearer {token}" if token else ""


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
    suppressed_secondary_only_count: int = 0


def build_open_epg_export_payload(
    open_epg_programmes: list[EpgProgramme],
) -> dict[str, object]:
    """Serialize normalized Open EPG programmes for export to JSON."""
    return {
        "provider": "open_epg",
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "programme_count": len(open_epg_programmes),
        "programmes": [_programme_row(programme) for programme in open_epg_programmes],
    }


def write_open_epg_export_file(
    export_file: str,
    open_epg_programmes: list[EpgProgramme],
) -> int:
    """Write a normalized Open EPG snapshot as JSON and return the programme count."""
    path = Path(export_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = build_open_epg_export_payload(open_epg_programmes)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(open_epg_programmes)


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


def load_open_epg_export_programmes(export_file: str) -> list[EpgProgramme]:
    payload = _load_json_file(export_file)
    programmes = payload.get("programmes")
    if not isinstance(programmes, list):
        return []

    loaded: list[EpgProgramme] = []
    for row in programmes:
        if not isinstance(row, dict):
            continue

        start_datetime = _parse_iso_datetime(row.get("start_datetime"))
        end_datetime = _parse_iso_datetime(row.get("end_datetime"))
        title = _clean_string(row.get("title"))
        channel_key = _clean_string(row.get("channel_key"))
        epg_entity = _clean_string(row.get("epg_entity"))
        if (
            not channel_key
            or not epg_entity
            or not title
            or start_datetime is None
            or end_datetime is None
        ):
            continue

        loaded.append(
            EpgProgramme(
                channel_key=channel_key,
                channel_name=_clean_string(row.get("channel_name")),
                epg_entity=epg_entity,
                title=title,
                description=_clean_string(row.get("description")),
                start=_clean_string(row.get("start")),
                end=_clean_string(row.get("end")),
                start_datetime=start_datetime,
                end_datetime=end_datetime,
            )
        )

    return loaded


def load_canalplus_export_programmes(export_file: str) -> list[GuideProgramme]:
    payload = _load_json_file(export_file)
    programmes = payload.get("programmes")
    if not isinstance(programmes, list):
        return []

    loaded: list[GuideProgramme] = []
    for row in programmes:
        if not isinstance(row, dict):
            continue

        try:
            loaded.append(guide_programme_from_canalplus_row(row))
        except ValueError:
            continue

    return loaded


def build_export_comparison_report(
    open_epg_export_file: str,
    canalplus_export_file: str,
    *,
    report_file: str | None = None,
    show_matching_programmes: bool = True,
    include_secondary_only_programmes: bool = True,
) -> CanalPlusComparisonReport:
    open_epg_programmes = load_open_epg_export_programmes(open_epg_export_file)
    canalplus_programmes = load_canalplus_export_programmes(canalplus_export_file)

    primary = [guide_programme_from_open_epg(programme) for programme in open_epg_programmes]
    raw_comparisons = compare_guides(primary, canalplus_programmes)
    comparisons = _filter_comparisons(
        raw_comparisons,
        show_matching_programmes=show_matching_programmes,
        include_secondary_only_programmes=include_secondary_only_programmes,
    )
    suppressed_secondary_only_count = _secondary_only_count(raw_comparisons) - _secondary_only_count(
        comparisons
    )
    window_start, window_end = _comparison_window(primary)
    counts = dict(Counter(comparison.kind for comparison in comparisons))

    rows_written = 0
    if report_file:
        rows_written = write_comparison_report(
            report_file,
            comparisons,
            comparison_window_start=window_start,
            comparison_window_end=window_end,
            suppressed_secondary_only_count=suppressed_secondary_only_count,
        )

    return CanalPlusComparisonReport(
        comparisons=comparisons,
        counts=counts,
        rows_written=rows_written,
        channel_count=len({programme.channel_key for programme in open_epg_programmes}),
        primary_count=len(open_epg_programmes),
        secondary_count=len(canalplus_programmes),
        fetch_error_count=0,
        suppressed_secondary_only_count=suppressed_secondary_only_count,
    )


def build_canalplus_comparison_report(
    open_epg_programmes: list[EpgProgramme],
    client: CanalPlusScheduleClient,
    channel_map: dict[str, str],
    *,
    report_file: str | None = None,
    show_matching_programmes: bool = True,
    include_secondary_only_programmes: bool = True,
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
    raw_comparisons = compare_guides(comparable_primary, secondary)
    comparisons = _filter_comparisons(
        raw_comparisons,
        show_matching_programmes=show_matching_programmes,
        include_secondary_only_programmes=include_secondary_only_programmes,
    )
    comparisons.extend(_fetch_error_comparisons(fetch_errors))
    suppressed_secondary_only_count = _secondary_only_count(raw_comparisons) - _secondary_only_count(
        comparisons
    )
    window_start, window_end = _comparison_window(primary)
    counts = dict(Counter(comparison.kind for comparison in comparisons))

    rows_written = 0
    if report_file:
        rows_written = write_comparison_report(
            report_file,
            comparisons,
            comparison_window_start=window_start,
            comparison_window_end=window_end,
            suppressed_secondary_only_count=suppressed_secondary_only_count,
        )

    return CanalPlusComparisonReport(
        comparisons=comparisons,
        counts=counts,
        rows_written=rows_written,
        channel_count=len(channel_map),
        primary_count=len(primary),
        secondary_count=len(secondary),
        fetch_error_count=len(fetch_errors),
        suppressed_secondary_only_count=suppressed_secondary_only_count,
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


def _load_json_file(path: str) -> dict[str, object]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _clean_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def write_comparison_report(
    report_file: str,
    comparisons: list[ProgrammeComparison],
    *,
    comparison_window_start: str = "",
    comparison_window_end: str = "",
    suppressed_secondary_only_count: int = 0,
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
                "comparison_window_start",
                "comparison_window_end",
                "suppressed_secondary_only_count",
            ],
        )
        writer.writeheader()
        for comparison in comparisons:
            writer.writerow(
                _comparison_row(
                    comparison,
                    comparison_window_start=comparison_window_start,
                    comparison_window_end=comparison_window_end,
                    suppressed_secondary_only_count=suppressed_secondary_only_count,
                )
            )

    return len(comparisons)


def _programme_row(programme: EpgProgramme) -> dict[str, object]:
    return {
        "channel_key": programme.channel_key,
        "channel_name": programme.channel_name,
        "epg_entity": programme.epg_entity,
        "title": programme.title,
        "description": programme.description,
        "start": programme.start,
        "end": programme.end,
        "start_datetime": programme.start_datetime.isoformat(),
        "end_datetime": programme.end_datetime.isoformat(),
    }


def filter_open_epg_programmes_by_scheduled_slots(
    open_epg_programmes: list[EpgProgramme],
    scheduled_slots: set[tuple[str, str, str]],
) -> list[EpgProgramme]:
    """Filter Open EPG programmes to scheduler slot keys read from calendars."""
    if not scheduled_slots:
        return []

    return [
        programme
        for programme in open_epg_programmes
        if _programme_slot_key(programme) in scheduled_slots
    ]


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _programme_slot_key(programme: EpgProgramme) -> tuple[str, str, str]:
    return (
        build_event_summary(programme),
        programme.start_datetime.isoformat(),
        programme.end_datetime.isoformat(),
    )


def _filter_comparisons(
    comparisons: list[ProgrammeComparison],
    *,
    show_matching_programmes: bool,
    include_secondary_only_programmes: bool,
) -> list[ProgrammeComparison]:
    filtered = comparisons

    if not include_secondary_only_programmes:
        filtered = [comparison for comparison in filtered if comparison.primary is not None]

    if show_matching_programmes:
        return filtered

    return [comparison for comparison in filtered if comparison.kind != CONFIRMED]


def _secondary_only_count(comparisons: list[ProgrammeComparison]) -> int:
    return sum(1 for comparison in comparisons if comparison.primary is None)


def _comparison_window(programmes: list[GuideProgramme]) -> tuple[str, str]:
    if not programmes:
        return "", ""

    return (
        min(programme.start_datetime for programme in programmes).isoformat(),
        max(programme.end_datetime for programme in programmes).isoformat(),
    )


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

        start_at = _floor_to_quarter_hour(
            min(programme.start_datetime for programme in channel_programmes)
        )
        end_at = _ceil_to_quarter_hour(
            max(programme.end_datetime for programme in channel_programmes)
        )
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


def _floor_to_quarter_hour(value: datetime) -> datetime:
    return value.replace(
        minute=(value.minute // 15) * 15,
        second=0,
        microsecond=0,
    )


def _ceil_to_quarter_hour(value: datetime) -> datetime:
    if value.minute % 15 == 0 and value.second == 0 and value.microsecond == 0:
        return value

    minutes_to_add = 15 - (value.minute % 15)
    if value.minute % 15 == 0:
        minutes_to_add = 15

    return (value + timedelta(minutes=minutes_to_add)).replace(
        second=0,
        microsecond=0,
    )


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


def _comparison_row(
    comparison: ProgrammeComparison,
    *,
    comparison_window_start: str,
    comparison_window_end: str,
    suppressed_secondary_only_count: int,
) -> dict[str, object]:
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
        "comparison_window_start": comparison_window_start,
        "comparison_window_end": comparison_window_end,
        "suppressed_secondary_only_count": suppressed_secondary_only_count,
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
