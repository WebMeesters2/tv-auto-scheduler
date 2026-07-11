from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

CONFIRMED = "confirmed"
MISSING_IN_PRIMARY = "missing_in_primary"
MISSING_IN_SECONDARY = "missing_in_secondary"
TIME_MISMATCH = "time_mismatch"
DURATION_MISMATCH = "duration_mismatch"
TITLE_MISMATCH = "title_mismatch"
REPLACED = "replaced"
SECONDARY_FETCH_FAILED = "secondary_fetch_failed"


@dataclass(frozen=True)
class GuideProgramme:
    source: str
    channel_key: str
    title: str
    start_datetime: datetime
    end_datetime: datetime
    description: str = ""
    provider_id: str = ""


@dataclass(frozen=True)
class ProgrammeComparison:
    kind: str
    primary: GuideProgramme | None
    secondary: GuideProgramme | None
    start_delta_minutes: int | None = None
    end_delta_minutes: int | None = None
    note: str = ""


def compare_guides(
    primary: list[GuideProgramme],
    secondary: list[GuideProgramme],
    *,
    time_tolerance: timedelta = timedelta(minutes=10),
    match_window: timedelta = timedelta(minutes=45),
) -> list[ProgrammeComparison]:
    """Compare two EPG programme lists without changing scheduler behaviour."""

    comparisons: list[ProgrammeComparison] = []
    matched_secondary: set[int] = set()

    for primary_programme in primary:
        match_index = _find_best_match(
            primary_programme,
            secondary,
            matched_secondary,
            match_window,
        )
        if match_index is None:
            comparisons.append(
                ProgrammeComparison(
                    kind=MISSING_IN_SECONDARY,
                    primary=primary_programme,
                    secondary=None,
                )
            )
            continue

        matched_secondary.add(match_index)
        secondary_programme = secondary[match_index]
        comparisons.append(
            _classify_match(
                primary_programme,
                secondary_programme,
                time_tolerance,
            )
        )

    for index, secondary_programme in enumerate(secondary):
        if index in matched_secondary:
            continue
        comparisons.append(
            ProgrammeComparison(
                kind=MISSING_IN_PRIMARY,
                primary=None,
                secondary=secondary_programme,
            )
        )

    return comparisons


def guide_programme_from_open_epg(programme: Any) -> GuideProgramme:
    return GuideProgramme(
        source="open_epg",
        channel_key=programme.channel_key,
        title=programme.title,
        description=programme.description,
        start_datetime=programme.start_datetime,
        end_datetime=programme.end_datetime,
    )


def guide_programme_from_canalplus_row(
    row: dict[str, Any],
    *,
    channel_key: str | None = None,
) -> GuideProgramme:
    return GuideProgramme(
        source="canalplus",
        channel_key=channel_key or str(row.get("channel_id", "")),
        title=str(row.get("title", "")),
        description=str(row.get("description", "")),
        start_datetime=_parse_api_datetime(str(row.get("start", ""))),
        end_datetime=_parse_api_datetime(str(row.get("end", ""))),
        provider_id=str(row.get("programme_id", "")),
    )


def _find_best_match(
    primary: GuideProgramme,
    candidates: list[GuideProgramme],
    matched_candidates: set[int],
    match_window: timedelta,
) -> int | None:
    best_index: int | None = None
    best_score: tuple[int, float] | None = None

    for index, candidate in enumerate(candidates):
        if index in matched_candidates:
            continue
        if candidate.channel_key != primary.channel_key:
            continue

        start_distance = abs(candidate.start_datetime - primary.start_datetime)
        overlaps = _programmes_overlap(primary, candidate)
        if not overlaps and start_distance > match_window:
            continue

        overlap = _overlap_duration(primary, candidate)
        title_penalty = 0 if _titles_match(primary.title, candidate.title) else 1
        score = (
            title_penalty,
            start_distance.total_seconds(),
            -overlap.total_seconds(),
        )
        if best_score is None or score < best_score:
            best_index = index
            best_score = score

    return best_index


def _classify_match(
    primary: GuideProgramme,
    secondary: GuideProgramme,
    time_tolerance: timedelta,
) -> ProgrammeComparison:
    start_delta = _delta_minutes(primary.start_datetime, secondary.start_datetime)
    end_delta = _delta_minutes(primary.end_datetime, secondary.end_datetime)
    titles_match = _titles_match(primary.title, secondary.title)
    start_within_tolerance = (
        abs(primary.start_datetime - secondary.start_datetime) <= time_tolerance
    )
    end_within_tolerance = (
        abs(primary.end_datetime - secondary.end_datetime) <= time_tolerance
    )

    if titles_match and start_within_tolerance and end_within_tolerance:
        kind = CONFIRMED
    elif titles_match:
        primary_duration = primary.end_datetime - primary.start_datetime
        secondary_duration = secondary.end_datetime - secondary.start_datetime
        duration_delta = abs(primary_duration - secondary_duration)
        if duration_delta <= time_tolerance:
            kind = TIME_MISMATCH
        else:
            kind = DURATION_MISMATCH
    elif start_within_tolerance or end_within_tolerance:
        kind = REPLACED
    else:
        kind = TITLE_MISMATCH

    return ProgrammeComparison(
        kind=kind,
        primary=primary,
        secondary=secondary,
        start_delta_minutes=start_delta,
        end_delta_minutes=end_delta,
    )


def _titles_match(left: str, right: str) -> bool:
    return _normalize_title(left) == _normalize_title(right)


def _normalize_title(value: str) -> str:
    value = re.sub(r"\([^)]{1,20}\)", " ", value.lower())
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\b\d{1,2}\s+\d{2}\s*uur\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _programmes_overlap(left: GuideProgramme, right: GuideProgramme) -> bool:
    return _overlap_duration(left, right) > timedelta(0)


def _overlap_duration(left: GuideProgramme, right: GuideProgramme) -> timedelta:
    start = max(left.start_datetime, right.start_datetime)
    end = min(left.end_datetime, right.end_datetime)
    if end <= start:
        return timedelta(0)
    return end - start


def _delta_minutes(left: datetime, right: datetime) -> int:
    return round((right - left).total_seconds() / 60)


def _parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
