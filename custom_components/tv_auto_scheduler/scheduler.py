from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CHANNEL_DATABASE_ENTITY,
    CSV_CHANNEL,
    CSV_DELETE_AFTER_USE,
    CSV_ENABLED,
    CSV_FILTER_END_TIME,
    CSV_FILTER_START_DAY,
    CSV_FILTER_START_TIME,
    CSV_PRE,
    CSV_PROGRAMME,
    CSV_TV,
)

_LOGGER = logging.getLogger(__name__)

_WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "ma": 0,
    "maa": 0,
    "maandag": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "di": 1,
    "din": 1,
    "dinsdag": 1,
    "wed": 2,
    "wednesday": 2,
    "wo": 2,
    "woe": 2,
    "woensdag": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "do": 3,
    "don": 3,
    "donderdag": 3,
    "fri": 4,
    "friday": 4,
    "vr": 4,
    "vrij": 4,
    "vrijdag": 4,
    "sat": 5,
    "saturday": 5,
    "za": 5,
    "zat": 5,
    "zaterdag": 5,
    "sun": 6,
    "sunday": 6,
    "zo": 6,
    "zon": 6,
    "zondag": 6,
}


@dataclass(frozen=True)
class ScheduleRule:
    enabled: bool
    channel_pattern: str
    programme: str
    pre: bool
    tv: bool
    delete_after_use: bool = False
    filter_start_days: frozenset[int] | None = None
    filter_start_time: time | None = None
    filter_end_time: time | None = None
    row_number: int | None = None


@dataclass(frozen=True)
class EpgProgramme:
    channel_key: str
    channel_name: str
    epg_entity: str
    title: str
    description: str
    start: str
    end: str
    start_datetime: datetime
    end_datetime: datetime


@dataclass(frozen=True)
class ChangeLogEntry:
    change_type: str
    run_datetime: datetime
    calendar_entity: str
    programme: EpgProgramme
    rule: ScheduleRule


def load_rules(rules_file: str) -> list[ScheduleRule]:
    path = Path(rules_file)

    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_file}")

    rules: list[ScheduleRule] = []

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row_number, row in enumerate(reader, start=2):
            enabled = _as_bool(row.get(CSV_ENABLED), default=True)

            if not enabled:
                continue

            channel = _clean(row.get(CSV_CHANNEL))
            programme = _clean(row.get(CSV_PROGRAMME))

            if not channel or not programme:
                _LOGGER.warning(
                    "Skipping invalid rule on row %s: channel and programme are required",
                    row_number,
                )
                continue

            filter_start_days = _parse_start_day_filter(row, row_number)
            if _clean(row.get(CSV_FILTER_START_DAY)) and filter_start_days is None:
                continue

            filter_start_time, filter_end_time = _parse_time_filter(row, row_number)
            if (
                _clean(row.get(CSV_FILTER_START_TIME))
                or _clean(row.get(CSV_FILTER_END_TIME))
            ) and (filter_start_time is None or filter_end_time is None):
                continue

            rules.append(
                ScheduleRule(
                    enabled=enabled,
                    channel_pattern=channel,
                    programme=programme,
                    pre=_as_bool(row.get(CSV_PRE), default=False),
                    tv=_as_bool(row.get(CSV_TV), default=False),
                    delete_after_use=_as_bool(
                        row.get(CSV_DELETE_AFTER_USE),
                        default=False,
                    ),
                    filter_start_days=filter_start_days,
                    filter_start_time=filter_start_time,
                    filter_end_time=filter_end_time,
                    row_number=row_number,
                )
            )

    return rules


def remove_rules_by_row_numbers(rules_file: str, row_numbers: set[int]) -> int:
    if not row_numbers:
        return 0

    path = Path(rules_file)

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames

        if not fieldnames:
            return 0

        kept_rows: list[dict[str, str]] = []
        removed = 0

        for row_number, row in enumerate(reader, start=2):
            if row_number in row_numbers:
                removed += 1
                continue

            kept_rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    return removed


def build_change_log_path(rules_file: str) -> str:
    if "/" in rules_file and "\\" not in rules_file:
        return str(PurePosixPath(rules_file).with_name("tv_auto_scheduler_changes.csv"))

    return str(Path(rules_file).with_name("tv_auto_scheduler_changes.csv"))


def resolve_change_log_path(rules_file: str, change_log_file: str | None) -> str:
    if change_log_file:
        return change_log_file

    return build_change_log_path(rules_file)


def append_change_log(log_file: str, entries: list[ChangeLogEntry]) -> int:
    if not entries:
        return 0

    path = Path(log_file)
    fieldnames = [
        "type",
        "run_at",
        "start_at",
        "end_at",
        "timezone",
        "calendar",
        "channel",
        "channel_name",
        "programme",
        "rule",
        "rule_row",
        "source_epg",
        "programme_description",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for entry in entries:
            writer.writerow(_build_change_log_row(entry))

    return len(entries)


def scan_epg(
    hass: HomeAssistant,
    show_missing_epg: bool = False,
) -> list[EpgProgramme]:
    state = hass.states.get(CHANNEL_DATABASE_ENTITY)

    if not state:
        _LOGGER.warning("Channel database entity not found: %s", CHANNEL_DATABASE_ENTITY)
        return []

    channels = state.attributes.get("channels")

    if not isinstance(channels, dict):
        _LOGGER.warning("Channel database has no usable 'channels' attribute")
        return []

    programmes: list[EpgProgramme] = []
    missing_epg_entities: list[str] = []

    for channel_key, channel_data in channels.items():
        if not isinstance(channel_data, dict):
            continue

        epg_entity = _clean(channel_data.get("epg"))

        if not epg_entity:
            continue

        epg_state = hass.states.get(epg_entity)

        if not epg_state:
            missing_epg_entities.append(epg_entity)
            continue

        channel_name = _first_alias(channel_key, channel_data)

        for day_name in ("today", "tomorrow"):
            day_data = epg_state.attributes.get(day_name)

            if not isinstance(day_data, dict):
                continue

            for item in day_data.values():
                if not isinstance(item, dict):
                    continue

                title = _clean(item.get("title"))
                description = _clean(item.get("desc"))

                if not title:
                    continue

                start_time = _clean(item.get("start"))
                end_time = _clean(item.get("end"))

                if not start_time or not end_time:
                    continue

                try:
                    start_datetime, end_datetime = _build_programme_datetimes(
                        0 if day_name == "today" else 1,
                        start_time,
                        end_time,
                    )
                except ValueError:
                    _LOGGER.warning(
                        "Skipping programme with invalid time values: %s | %s (%s-%s)",
                        channel_name,
                        title,
                        start_time,
                        end_time,
                    )
                    continue

                programmes.append(
                    EpgProgramme(
                        channel_key=str(channel_key),
                        channel_name=channel_name,
                        epg_entity=epg_entity,
                        title=title,
                        description=description,
                        start=start_time,
                        end=end_time,
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                    )
                )

    if missing_epg_entities:
        if show_missing_epg:
            for epg_entity in missing_epg_entities:
                _LOGGER.debug("EPG entity not found: %s", epg_entity)
        else:
            _LOGGER.debug(
                "Skipped %s channel(s) with missing EPG entities",
                len(missing_epg_entities),
            )

    return programmes


async def create_calendar_event(
    hass: HomeAssistant,
    calendar_entity: str,
    rule: ScheduleRule,
    programme: EpgProgramme,
) -> None:
    summary = build_event_summary(programme)

    description = (
        f"{AUTO_MARKER}\n"
        f"Rule: {rule.programme}\n"
        f"Source: {programme.epg_entity}\n"
    )

    if programme.description:
        description = f"{description}Programme: {programme.description}\n"

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": calendar_entity,
            "summary": summary,
            "description": description,
            "start_date_time": programme.start_datetime.isoformat(),
            "end_date_time": programme.end_datetime.isoformat(),
        },
        blocking=True,
    )


AUTO_MARKER = "TV_AUTO_SCHEDULER: true"


async def calendar_event_exists(
    hass: HomeAssistant,
    calendar_entity: str,
    programme: EpgProgramme,
) -> bool:
    summary = build_event_summary(programme)

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar_entity,
            "start_date_time": programme.start_datetime.isoformat(),
            "end_date_time": programme.end_datetime.isoformat(),
        },
        blocking=True,
        return_response=True,
    )

    events = _extract_calendar_events_response(response, calendar_entity)

    for event in events:
        if not isinstance(event, dict):
            continue

        existing_summary = _clean(event.get("summary"))
        existing_start = _clean(event.get("start"))
        existing_end = _clean(event.get("end"))
        existing_description = _clean(event.get("description"))

        if (
            existing_summary == summary
            and existing_start == programme.start_datetime.isoformat()
            and existing_end == programme.end_datetime.isoformat()
            and AUTO_MARKER in existing_description
        ):
            return True

    return False


def build_event_summary(programme: EpgProgramme) -> str:
    return f"{programme.channel_name} | {programme.title}"


def _extract_calendar_events_response(
    response: object,
    calendar_entity: str,
) -> list[object]:
    if not isinstance(response, dict):
        return []

    calendar_data = response.get(calendar_entity)

    if isinstance(calendar_data, dict):
        events = calendar_data.get("events")
        if isinstance(events, list):
            return events

    events = response.get("events")
    if isinstance(events, list):
        return events

    return []


def find_matches(
    rules: list[ScheduleRule],
    programmes: list[EpgProgramme],
) -> list[tuple[ScheduleRule, EpgProgramme]]:
    matches: list[tuple[ScheduleRule, EpgProgramme]] = []

    for rule in rules:
        for programme in programmes:
            if not _matches_channel(rule, programme):
                continue

            if not _matches_programme(rule, programme):
                continue

            if not _matches_start_time_filter(rule, programme):
                continue

            if not _matches_start_day_filter(rule, programme):
                continue

            matches.append((rule, programme))

    return matches


def log_matches(matches: list[tuple[ScheduleRule, EpgProgramme]]) -> None:
    if not matches:
        _LOGGER.info("TV Auto Scheduler: no matching programmes found")
        return

    _LOGGER.info("TV Auto Scheduler: found %s matching programme(s)", len(matches))

    for rule, programme in matches:
        targets = ", ".join(
            target
            for target, enabled in (("pre", rule.pre), ("tv", rule.tv))
            if enabled
        )

        _LOGGER.info(
            "TV Auto Scheduler match: %s | %s (%s-%s) → %s",
            programme.channel_name,
            programme.title,
            programme.start,
            programme.end,
            targets or "no target",
        )


def _matches_channel(rule: ScheduleRule, programme: EpgProgramme) -> bool:
    try:
        return bool(
            re.search(
                rule.channel_pattern,
                programme.channel_key,
                re.IGNORECASE,
            )
        )
    except re.error:
        _LOGGER.warning("Invalid channel regex pattern in rule: %s", rule.channel_pattern)
        return False


def _matches_programme(rule: ScheduleRule, programme: EpgProgramme) -> bool:
    try:
        return bool(
            re.search(
                rule.programme,
                programme.title,
                re.IGNORECASE,
            )
        )
    except re.error:
        _LOGGER.warning("Invalid regex pattern in rule: %s", rule.programme)
        return False


def _matches_start_time_filter(rule: ScheduleRule, programme: EpgProgramme) -> bool:
    if rule.filter_start_time is None or rule.filter_end_time is None:
        return True

    programme_time = programme.start_datetime.timetz().replace(tzinfo=None)

    if rule.filter_start_time <= rule.filter_end_time:
        return rule.filter_start_time <= programme_time <= rule.filter_end_time

    return (
        programme_time >= rule.filter_start_time
        or programme_time <= rule.filter_end_time
    )


def _matches_start_day_filter(rule: ScheduleRule, programme: EpgProgramme) -> bool:
    if not rule.filter_start_days:
        return True

    return programme.start_datetime.weekday() in rule.filter_start_days


def _first_alias(channel_key: str, channel_data: dict[str, Any]) -> str:
    aliases = channel_data.get("aliases")

    if isinstance(aliases, list) and aliases:
        first = aliases[0]
        if isinstance(first, str) and first.strip():
            return first.strip()

    return str(channel_key)


def _build_programme_datetimes(
    day_offset: int,
    start_time: str,
    end_time: str,
) -> tuple[datetime, datetime]:
    base = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    base = base + timedelta(days=day_offset)

    start = _combine_base_date_and_time(base, start_time)
    end = _combine_base_date_and_time(base, end_time)

    if end <= start:
        end = end + timedelta(days=1)

    return start, end


def _combine_base_date_and_time(base: datetime, time_value: str) -> datetime:
    hours, minutes = [int(part) for part in time_value.split(":", maxsplit=1)]
    return base.replace(hour=hours, minute=minutes, second=0, microsecond=0)


def _parse_time_filter(
    row: dict[str, Any],
    row_number: int,
) -> tuple[time | None, time | None]:
    start_value = _clean(row.get(CSV_FILTER_START_TIME))
    end_value = _clean(row.get(CSV_FILTER_END_TIME))

    if not start_value and not end_value:
        return None, None

    if not start_value or not end_value:
        _LOGGER.warning(
            "Skipping invalid rule on row %s: filter-start-time and filter-end-time must both be set",
            row_number,
        )
        return None, None

    try:
        return _parse_time_value(start_value), _parse_time_value(end_value)
    except ValueError:
        _LOGGER.warning(
            "Skipping invalid rule on row %s: invalid filter time value (%s-%s)",
            row_number,
            start_value,
            end_value,
        )
        return None, None


def _parse_start_day_filter(
    row: dict[str, Any],
    row_number: int,
) -> frozenset[int] | None:
    value = _clean(row.get(CSV_FILTER_START_DAY))

    if not value:
        return None

    days: set[int] = set()

    for token in re.split(r"[|,;/]+", value):
        normalized = token.strip().lower()
        if not normalized:
            continue

        day_range = _parse_weekday_range(normalized)
        if day_range is not None:
            days.update(day_range)
            continue

        weekday = _WEEKDAY_ALIASES.get(normalized)
        if weekday is None:
            _LOGGER.warning(
                "Skipping invalid rule on row %s: invalid filter-start-day value (%s)",
                row_number,
                value,
            )
            return None

        days.add(weekday)

    if not days:
        _LOGGER.warning(
            "Skipping invalid rule on row %s: invalid filter-start-day value (%s)",
            row_number,
            value,
        )
        return None

    return frozenset(days)


def _parse_weekday_range(value: str) -> set[int] | None:
    if "-" not in value:
        return None

    start_name, end_name = [part.strip() for part in value.split("-", maxsplit=1)]
    start_day = _WEEKDAY_ALIASES.get(start_name)
    end_day = _WEEKDAY_ALIASES.get(end_name)

    if start_day is None or end_day is None:
        return None

    if start_day <= end_day:
        return set(range(start_day, end_day + 1))

    return set(range(start_day, 7)) | set(range(0, end_day + 1))


def _parse_time_value(value: str) -> time:
    hours, minutes = [int(part) for part in value.split(":", maxsplit=1)]
    return time(hour=hours, minute=minutes)


def _build_change_log_row(entry: ChangeLogEntry) -> dict[str, str]:
    programme_timezone = (
        entry.programme.start_datetime.tzname()
        or entry.programme.end_datetime.tzname()
        or entry.run_datetime.tzname()
        or ""
    )

    return {
        "type": entry.change_type,
        "run_at": _format_change_log_datetime(entry.run_datetime),
        "start_at": _format_change_log_datetime(entry.programme.start_datetime),
        "end_at": _format_change_log_datetime(entry.programme.end_datetime),
        "timezone": programme_timezone,
        "calendar": entry.calendar_entity,
        "channel": entry.programme.channel_key,
        "channel_name": entry.programme.channel_name,
        "programme": entry.programme.title,
        "rule": entry.rule.programme,
        "rule_row": "" if entry.rule.row_number is None else str(entry.rule.row_number),
        "source_epg": entry.programme.epg_entity,
        "programme_description": entry.programme.description,
    }


def _format_change_log_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "ja", "j"}


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()
