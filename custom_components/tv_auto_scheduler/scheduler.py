"""Scheduler core for loading CSV rules, scanning EPG data, and writing calendars.

This module owns the source-file workflow for the Open EPG scheduler: it reads
`rules.csv` and optional named time ranges, normalizes Home Assistant EPG sensor
attributes into programme objects, matches programmes against case-insensitive
regular-expression rules, and creates or replaces Home Assistant calendar events.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from homeassistant.components.calendar.const import (
    DATA_COMPONENT as CALENDAR_COMPONENT,
)
from homeassistant.components.calendar.const import (
    CalendarEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_DESCRIPTION_DEBUG,
    CALENDAR_DESCRIPTION_PROGRAMME,
    CHANNEL_DATABASE_ENTITY,
    CSV_CHANNEL,
    CSV_DELETE_AFTER_USE,
    CSV_ENABLED,
    CSV_FILTER_END_TIME,
    CSV_FILTER_START_DAY,
    CSV_FILTER_START_TIME,
    CSV_NAMED_TIME_RANGE,
    CSV_PRE,
    CSV_PROGRAMME,
    CSV_RULE_ID,
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
    rule_id: int = 0


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


@dataclass(frozen=True)
class ExistingAutoCalendarEvent:
    uid: str
    recurrence_id: str | None
    summary: str
    start_datetime: datetime
    end_datetime: datetime


@dataclass(frozen=True)
class NamedTimeRange:
    key: str
    filter_start_days: frozenset[int] | None
    filter_start_time: time | None
    filter_end_time: time | None


RULES_CSV_FIELD_ORDER = [
    CSV_RULE_ID,
    CSV_ENABLED,
    CSV_CHANNEL,
    CSV_PROGRAMME,
    CSV_PRE,
    CSV_TV,
    CSV_DELETE_AFTER_USE,
    CSV_NAMED_TIME_RANGE,
    CSV_FILTER_START_DAY,
    CSV_FILTER_START_TIME,
    CSV_FILTER_END_TIME,
]


RULES_CSV_FIELD_DEFAULTS = {
    CSV_RULE_ID: "",
    CSV_ENABLED: "y",
    CSV_CHANNEL: "",
    CSV_PROGRAMME: "",
    CSV_PRE: "n",
    CSV_TV: "n",
    CSV_DELETE_AFTER_USE: "n",
    CSV_NAMED_TIME_RANGE: "",
    CSV_FILTER_START_DAY: "",
    CSV_FILTER_START_TIME: "",
    CSV_FILTER_END_TIME: "",
}

_INLINE_COMMENT_FIELD = "__inline_comment__"


def load_rules(
    rules_file: str,
    named_time_ranges_file: str | None = None,
) -> list[ScheduleRule]:
    """Load enabled schedule rules from CSV paths and return parsed rule objects."""
    path = Path(rules_file)

    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_file}")

    named_time_ranges = load_named_time_ranges(
        rules_file,
        named_time_ranges_file,
    )

    rules: list[ScheduleRule] = []

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        existing_fields, rows = _read_csv_rows(file.readlines())
        next_rule_id = max(_collect_existing_rule_ids(rows, existing_fields), default=0) + 1

        for row_number, row in enumerate(rows, start=2):
            row = _normalize_rules_csv_row(row, existing_fields)
            rule_id, next_rule_id = _parse_rule_id(
                row.get(CSV_RULE_ID),
                row_number,
                next_rule_id,
            )
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

            named_time_range_key = _clean(row.get(CSV_NAMED_TIME_RANGE))
            named_time_range = _resolve_named_time_range(
                named_time_ranges,
                named_time_range_key,
                row_number,
            )
            if named_time_range_key and named_time_range is None:
                continue

            filter_start_days = _parse_start_day_filter(
                row,
                row_number,
                default=named_time_range.filter_start_days if named_time_range else None,
            )
            if _clean(row.get(CSV_FILTER_START_DAY)) and filter_start_days is None:
                continue

            filter_start_time, filter_end_time = _parse_time_filter(
                row,
                row_number,
                default_start_time=(
                    named_time_range.filter_start_time if named_time_range else None
                ),
                default_end_time=(
                    named_time_range.filter_end_time if named_time_range else None
                ),
            )
            if (
                _clean(row.get(CSV_FILTER_START_TIME))
                or _clean(row.get(CSV_FILTER_END_TIME))
            ) and (filter_start_time is None or filter_end_time is None):
                continue

            rules.append(
                ScheduleRule(
                    rule_id=rule_id,
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
    """Remove rows from a rules CSV and return how many rows were deleted."""
    if not row_numbers:
        return 0

    path = Path(rules_file)

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        fieldnames, rows = _read_csv_rows(file.readlines())

        if not fieldnames:
            return 0

        kept_rows: list[dict[str, str]] = []
        removed = 0

        for row_number, row in enumerate(rows, start=2):
            if row_number in row_numbers:
                removed += 1
                continue

            kept_rows.append(row)

    _write_compact_csv_rows(path, fieldnames, kept_rows)

    return removed


def ensure_rules_file_schema(rules_file: str) -> bool:
    """Normalize the rules CSV schema in place and return whether it changed."""
    path = Path(rules_file)

    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_file}")

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        existing_fields, rows = _read_csv_rows(file.readlines())

    extra_fields = [
        field for field in existing_fields if field and field not in RULES_CSV_FIELD_ORDER
    ]
    final_fields = RULES_CSV_FIELD_ORDER + extra_fields

    used_rule_ids = _collect_existing_rule_ids(rows, existing_fields)
    next_rule_id = max(used_rule_ids, default=0) + 1
    migrated_rows: list[dict[str, str]] = []

    for row in rows:
        migrated_row = _normalize_rules_csv_row(row, existing_fields)
        migrated_row[_INLINE_COMMENT_FIELD] = _clean(row.get(_INLINE_COMMENT_FIELD))
        for field in final_fields:
            migrated_row.setdefault(field, _clean(row.get(field)))

        for field, default in RULES_CSV_FIELD_DEFAULTS.items():
            if migrated_row[field] == "":
                if field in existing_fields:
                    continue
                migrated_row[field] = default

        rule_id_text = migrated_row[CSV_RULE_ID]
        parsed_rule_id = _try_parse_positive_int(rule_id_text)
        if parsed_rule_id is None:
            parsed_rule_id = next_rule_id
            while parsed_rule_id in used_rule_ids:
                parsed_rule_id += 1
            migrated_row[CSV_RULE_ID] = str(parsed_rule_id)

        used_rule_ids.add(parsed_rule_id)
        next_rule_id = max(next_rule_id, parsed_rule_id + 1)
        migrated_rows.append(migrated_row)

    changed = existing_fields != final_fields
    if not changed:
        for row, migrated_row in zip(rows, migrated_rows, strict=False):
            for field in final_fields:
                if _clean(row.get(field)) != migrated_row[field]:
                    changed = True
                    break
            if changed:
                break

    if not changed:
        return False

    _write_compact_csv_rows(path, final_fields, migrated_rows)

    return True


def resolve_named_time_ranges_path(
    rules_file: str,
    named_time_ranges_file: str | None = None,
) -> str:
    """Return an explicit named-time-ranges path or the default beside rules_file."""
    if named_time_ranges_file:
        return named_time_ranges_file

    if "/" in rules_file and "\\" not in rules_file:
        return str(PurePosixPath(rules_file).with_name("named_time_ranges.csv"))

    return str(Path(rules_file).with_name("named_time_ranges.csv"))


def load_named_time_ranges(
    rules_file: str,
    named_time_ranges_file: str | None = None,
) -> dict[str, NamedTimeRange]:
    """Load named time filters keyed case-insensitively by range name."""
    path = Path(resolve_named_time_ranges_path(rules_file, named_time_ranges_file))
    if not path.exists():
        return {}

    named_time_ranges: dict[str, NamedTimeRange] = {}

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        fieldnames, rows = _read_csv_rows(file.readlines())

        if not fieldnames:
            return {}

        for row_number, row in enumerate(rows, start=2):
            key = _clean(row.get("key") or row.get("KEY"))
            if not key:
                _LOGGER.warning(
                    "Skipping invalid named time range on row %s: key is required",
                    row_number,
                )
                continue

            filter_start_days = _parse_start_day_filter(
                row,
                row_number,
                source_name="named time range",
            )
            if _clean(row.get(CSV_FILTER_START_DAY)) and filter_start_days is None:
                continue

            filter_start_time, filter_end_time = _parse_time_filter(
                row,
                row_number,
                source_name="named time range",
            )
            if (
                _clean(row.get(CSV_FILTER_START_TIME))
                or _clean(row.get(CSV_FILTER_END_TIME))
            ) and (filter_start_time is None or filter_end_time is None):
                continue

            named_time_ranges[key.lower()] = NamedTimeRange(
                key=key,
                filter_start_days=filter_start_days,
                filter_start_time=filter_start_time,
                filter_end_time=filter_end_time,
            )

    return named_time_ranges


def build_dry_run_log_path(rules_file: str) -> str:
    """Return the default dry-run CSV log path beside the rules file."""
    if "/" in rules_file and "\\" not in rules_file:
        return str(PurePosixPath(rules_file).with_name("tv_auto_scheduler_dry_run.csv"))

    return str(Path(rules_file).with_name("tv_auto_scheduler_dry_run.csv"))


def resolve_dry_run_log_path(rules_file: str, dry_run_log_file: str | None) -> str:
    """Return a supplied dry-run log path or the default path for rules_file."""
    if dry_run_log_file:
        return dry_run_log_file

    return build_dry_run_log_path(rules_file)


def build_change_log_path(rules_file: str) -> str:
    """Return the default change-log CSV path beside the rules file."""
    if "/" in rules_file and "\\" not in rules_file:
        return str(PurePosixPath(rules_file).with_name("tv_auto_scheduler_changes.csv"))

    return str(Path(rules_file).with_name("tv_auto_scheduler_changes.csv"))


def resolve_change_log_path(rules_file: str, change_log_file: str | None) -> str:
    """Return a supplied change-log path or the default path for rules_file."""
    if change_log_file:
        return change_log_file

    return build_change_log_path(rules_file)


def append_change_log(log_file: str, entries: list[ChangeLogEntry]) -> int:
    """Append change-log entries to CSV and return the number of rows written."""
    if not entries:
        return 0

    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    fieldnames = _resolve_change_log_fieldnames(path, write_header)

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for entry in entries:
            writer.writerow(_build_change_log_row(entry, fieldnames))

    return len(entries)


def scan_epg(
    hass: HomeAssistant,
    show_missing_epg: bool = False,
) -> list[EpgProgramme]:
    """Read Home Assistant EPG sensors and return normalized programmes."""
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
    calendar_description_mode: str = CALENDAR_DESCRIPTION_PROGRAMME,
) -> None:
    """Create one Home Assistant calendar event for a matched programme."""
    summary = build_event_summary(programme)

    debug_text = build_event_debug_text(rule, programme)
    description = build_event_description(
        programme,
        debug_text,
        calendar_description_mode,
    )

    event_data = {
        "entity_id": calendar_entity,
        "summary": summary,
        "description": description,
        "location": debug_text,
        "start_date_time": programme.start_datetime.isoformat(),
        "end_date_time": programme.end_datetime.isoformat(),
    }

    await hass.services.async_call(
        "calendar",
        "create_event",
        event_data,
        blocking=True,
    )


AUTO_MARKER = "TV_AUTO_SCHEDULER: true"


async def calendar_event_exists(
    hass: HomeAssistant,
    calendar_entity: str,
    programme: EpgProgramme,
) -> bool:
    """Return whether the calendar already has the exact scheduler-created event."""
    exact_match, _ = await find_existing_auto_calendar_events(
        hass,
        calendar_entity,
        programme,
    )
    return exact_match is not None


async def find_existing_auto_calendar_events(
    hass: HomeAssistant,
    calendar_entity: str,
    programme: EpgProgramme,
) -> tuple[ExistingAutoCalendarEvent | None, list[ExistingAutoCalendarEvent]]:
    """Return exact and overlapping scheduler-created events for a programme."""
    entity = _get_calendar_entity(hass, calendar_entity)

    if entity is not None:
        query_start = _replacement_lookup_start(programme)
        query_end = _replacement_lookup_end(programme)

        try:
            events = await entity.async_get_events(
                hass,
                query_start,
                query_end,
            )
        except HomeAssistantError:
            _LOGGER.exception(
                "TV Auto Scheduler: failed to read existing events for %s",
                calendar_entity,
            )
            return None, []

        return _classify_existing_auto_calendar_events(events, programme)

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
        existing_location = _clean(event.get("location"))
        existing_metadata = f"{existing_description}\n{existing_location}"

        if (
            existing_summary == summary
            and existing_start == programme.start_datetime.isoformat()
            and existing_end == programme.end_datetime.isoformat()
            and AUTO_MARKER in existing_metadata
        ):
            return (
                ExistingAutoCalendarEvent(
                    uid="",
                    recurrence_id=None,
                    summary=existing_summary,
                    start_datetime=programme.start_datetime,
                    end_datetime=programme.end_datetime,
                ),
                [],
            )

    return None, []


async def replace_calendar_event(
    hass: HomeAssistant,
    calendar_entity: str,
    rule: ScheduleRule,
    programme: EpgProgramme,
    stale_events: list[ExistingAutoCalendarEvent],
    calendar_description_mode: str = CALENDAR_DESCRIPTION_PROGRAMME,
) -> int:
    """Delete stale matching calendar events, create the new event, and return deletions."""
    entity = _get_calendar_entity(hass, calendar_entity)

    if entity is None:
        raise HomeAssistantError(
            f"Calendar entity is not available for replacement: {calendar_entity}"
        )

    supported_features = getattr(entity, "supported_features", 0) or 0
    if not supported_features & CalendarEntityFeature.DELETE_EVENT:
        raise HomeAssistantError(
            f"Calendar does not support event deletion: {calendar_entity}"
        )

    removed = 0

    for stale_event in stale_events:
        await entity.async_delete_event(
            stale_event.uid,
            recurrence_id=stale_event.recurrence_id,
        )
        removed += 1

    await create_calendar_event(
        hass,
        calendar_entity,
        rule,
        programme,
        calendar_description_mode=calendar_description_mode,
    )

    return removed


def build_event_summary(programme: EpgProgramme) -> str:
    """Return the calendar summary text for a programme."""
    return f"{programme.channel_name} | {programme.title}"


def build_event_debug_text(rule: ScheduleRule, programme: EpgProgramme) -> str:
    """Return scheduler metadata for duplicate detection and debug views."""
    lines = [
        AUTO_MARKER,
        f"Rule: {rule.programme}",
        f"Source: {programme.epg_entity}",
    ]
    if programme.description:
        lines.append(f"Programme: {programme.description}")
    return "\n".join(lines)


def build_event_description(
    programme: EpgProgramme,
    debug_text: str,
    calendar_description_mode: str,
) -> str:
    """Return the calendar description shown by dashboard calendar cards."""
    if calendar_description_mode == CALENDAR_DESCRIPTION_DEBUG:
        return debug_text

    return programme.description or programme.title


def _extract_calendar_events_response(
    response: object,
    calendar_entity: str,
) -> list[object]:
    """Extract event objects from Home Assistant calendar service responses."""
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


def _get_calendar_entity(hass: HomeAssistant, calendar_entity: str) -> Any | None:
    """Return a loaded calendar entity object when Home Assistant exposes it."""
    component = hass.data.get(CALENDAR_COMPONENT)
    if component is None or not hasattr(component, "get_entity"):
        return None

    return component.get_entity(calendar_entity)


def _classify_existing_auto_calendar_events(
    events: list[object],
    programme: EpgProgramme,
) -> tuple[ExistingAutoCalendarEvent | None, list[ExistingAutoCalendarEvent]]:
    """Classify scheduler-created events as exact or shifted matches."""
    exact_match: ExistingAutoCalendarEvent | None = None
    shifted_matches: list[ExistingAutoCalendarEvent] = []
    summary = build_event_summary(programme)
    source_marker = f"Source: {programme.epg_entity}"

    for event in events:
        normalized_event = _normalize_existing_auto_calendar_event(
            event,
            summary,
            source_marker,
        )
        if normalized_event is None:
            continue

        if (
            normalized_event.start_datetime == programme.start_datetime
            and normalized_event.end_datetime == programme.end_datetime
        ):
            exact_match = normalized_event
            continue

        if _time_ranges_overlap(
            normalized_event.start_datetime,
            normalized_event.end_datetime,
            programme.start_datetime,
            programme.end_datetime,
        ):
            shifted_matches.append(normalized_event)

    return exact_match, shifted_matches


def _normalize_existing_auto_calendar_event(
    event: object,
    expected_summary: str,
    expected_source_marker: str,
) -> ExistingAutoCalendarEvent | None:
    """Convert a matching raw calendar event into the scheduler event shape."""
    summary = _clean(_existing_event_value(event, "summary"))
    description = _clean(_existing_event_value(event, "description"))
    location = _clean(_existing_event_value(event, "location"))
    metadata = f"{description}\n{location}"

    if summary != expected_summary:
        return None

    if AUTO_MARKER not in metadata or expected_source_marker not in metadata:
        return None

    uid = _clean(_existing_event_value(event, "uid"))
    if not uid:
        return None

    start_datetime = _existing_event_datetime(event, "start")
    end_datetime = _existing_event_datetime(event, "end")

    if start_datetime is None or end_datetime is None:
        return None

    recurrence_id = _clean(_existing_event_value(event, "recurrence_id")) or None

    return ExistingAutoCalendarEvent(
        uid=uid,
        recurrence_id=recurrence_id,
        summary=summary,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )


def _existing_event_value(event: object, name: str) -> Any:
    """Read a named value from a dict-like or attribute-based calendar event."""
    if isinstance(event, dict):
        return event.get(name)

    return getattr(event, name, None)


def _existing_event_datetime(event: object, attribute_name: str) -> datetime | None:
    """Return a local datetime value from a calendar event date/datetime field."""
    local_attribute_name = f"{attribute_name}_datetime_local"

    if hasattr(event, local_attribute_name):
        value = getattr(event, local_attribute_name)
        if isinstance(value, datetime):
            return value

    raw_value = _existing_event_value(event, attribute_name)
    if isinstance(raw_value, datetime):
        return dt_util.as_local(raw_value)

    if isinstance(raw_value, date):
        return dt_util.start_of_local_day(datetime.combine(raw_value, time.min))

    return None


def _replacement_lookup_start(programme: EpgProgramme) -> datetime:
    """Return the local-day query start used when looking for stale events."""
    return dt_util.start_of_local_day(programme.start_datetime)


def _replacement_lookup_end(programme: EpgProgramme) -> datetime:
    """Return the exclusive query end used when looking for stale events."""
    return _replacement_lookup_start(programme) + timedelta(days=1)


def _time_ranges_overlap(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    """Return whether two half-open datetime ranges overlap."""
    return start_a < end_b and start_b < end_a


def find_matches(
    rules: list[ScheduleRule],
    programmes: list[EpgProgramme],
) -> list[tuple[ScheduleRule, EpgProgramme]]:
    """Return every rule/programme pair that satisfies regex and time filters."""
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
    """Write a concise log summary for matched rule/programme pairs."""
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
    """Return whether a rule regex matches a programme channel key, ignoring case."""
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
    """Return whether a rule regex matches a programme title, ignoring case."""
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
    """Return whether a programme start time falls inside the rule time window."""
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
    """Return whether a programme start weekday satisfies the rule day filter."""
    if not rule.filter_start_days:
        return True

    return programme.start_datetime.weekday() in rule.filter_start_days


def _first_alias(channel_key: str, channel_data: dict[str, Any]) -> str:
    """Return the first configured channel alias, falling back to the channel key."""
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
    """Combine EPG day offset and HH:MM strings into local start/end datetimes."""
    base = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    base = base + timedelta(days=day_offset)

    start = _combine_base_date_and_time(base, start_time)
    end = _combine_base_date_and_time(base, end_time)

    if end <= start:
        end = end + timedelta(days=1)

    return start, end


def _combine_base_date_and_time(base: datetime, time_value: str) -> datetime:
    """Return base with hour and minute replaced from an HH:MM value."""
    hours, minutes = [int(part) for part in time_value.split(":", maxsplit=1)]
    return base.replace(hour=hours, minute=minutes, second=0, microsecond=0)


def _parse_time_filter(
    row: dict[str, Any],
    row_number: int,
    *,
    default_start_time: time | None = None,
    default_end_time: time | None = None,
    source_name: str = "rule",
) -> tuple[time | None, time | None]:
    """Parse optional start/end time filters, returning defaults or invalid sentinels."""
    start_value = _clean(row.get(CSV_FILTER_START_TIME))
    end_value = _clean(row.get(CSV_FILTER_END_TIME))

    if not start_value and not end_value:
        return default_start_time, default_end_time

    if not start_value or not end_value:
        _LOGGER.warning(
            "Skipping invalid %s on row %s: filter-start-time and filter-end-time must both be set",
            source_name,
            row_number,
        )
        return None, None

    try:
        return _parse_time_value(start_value), _parse_time_value(end_value)
    except ValueError:
        _LOGGER.warning(
            "Skipping invalid %s on row %s: invalid filter time value (%s-%s)",
            source_name,
            row_number,
            start_value,
            end_value,
        )
        return None, None


def _parse_start_day_filter(
    row: dict[str, Any],
    row_number: int,
    *,
    default: frozenset[int] | None = None,
    source_name: str = "rule",
) -> frozenset[int] | None:
    """Parse weekday tokens and ranges into Python weekday numbers."""
    value = _clean(row.get(CSV_FILTER_START_DAY))

    if not value:
        return default

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
                "Skipping invalid %s on row %s: invalid filter-start-day value (%s)",
                source_name,
                row_number,
                value,
            )
            return None

        days.add(weekday)

    if not days:
        _LOGGER.warning(
            "Skipping invalid %s on row %s: invalid filter-start-day value (%s)",
            source_name,
            row_number,
            value,
        )
        return None

    return frozenset(days)


def _parse_weekday_range(value: str) -> set[int] | None:
    """Parse a weekday range token into weekday numbers, including wraparound ranges."""
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
    """Parse an HH:MM value into a time object."""
    hours, minutes = [int(part) for part in value.split(":", maxsplit=1)]
    return time(hour=hours, minute=minutes)


def _parse_rule_id(
    value: Any,
    row_number: int,
    next_rule_id: int,
) -> tuple[int, int]:
    """Return a positive rule ID and the next candidate ID for following rows."""
    parsed_rule_id = _try_parse_positive_int(_clean(value))
    if parsed_rule_id is None:
        parsed_rule_id = next_rule_id

    return parsed_rule_id, max(next_rule_id, parsed_rule_id + 1)


def _collect_existing_rule_ids(
    rows: list[dict[str, Any]],
    existing_fields: list[str],
) -> set[int]:
    """Return all positive rule IDs already present in normalized CSV rows."""
    existing_rule_ids: set[int] = set()

    for row in rows:
        normalized_row = _normalize_rules_csv_row(row, existing_fields)
        parsed_rule_id = _try_parse_positive_int(normalized_row.get(CSV_RULE_ID, ""))
        if parsed_rule_id is not None:
            existing_rule_ids.add(parsed_rule_id)

    return existing_rule_ids


def _determine_next_rule_id(reader: csv.DictReader) -> int:
    """Return the next positive rule ID after scanning a CSV DictReader."""
    max_rule_id = 0
    for row in reader:
        parsed_rule_id = _try_parse_positive_int(_clean(row.get(CSV_RULE_ID)))
        if parsed_rule_id is not None:
            max_rule_id = max(max_rule_id, parsed_rule_id)

    return max_rule_id + 1 if max_rule_id else 1


def _resolve_named_time_range(
    named_time_ranges: dict[str, NamedTimeRange],
    key: str,
    row_number: int,
) -> NamedTimeRange | None:
    """Return the named time range for a key or log and return None when invalid."""
    if not key:
        return None

    resolved = named_time_ranges.get(key.lower())
    if resolved is not None:
        return resolved

    _LOGGER.warning(
        "Skipping invalid rule on row %s: unknown named time range (%s)",
        row_number,
        key,
    )
    return None


def _try_parse_positive_int(value: str) -> int | None:
    """Return a positive integer parsed from text, otherwise None."""
    if not value:
        return None

    try:
        parsed = int(value)
    except ValueError:
        return None

    return parsed if parsed > 0 else None


def _normalize_rules_csv_row(
    row: dict[str, Any],
    existing_fields: list[str],
) -> dict[str, str]:
    """Clean a rules CSV row and repair legacy rows missing the rule-id column."""
    normalized_row = {
        field: _clean(row.get(field))
        for field in existing_fields
        if field
    }

    if not _looks_like_shifted_rule_id_row(normalized_row):
        return normalized_row

    ordered_values = [normalized_row.get(field, "") for field in RULES_CSV_FIELD_ORDER]
    shifted_values = [""] + ordered_values[:-1]

    for field, value in zip(RULES_CSV_FIELD_ORDER, shifted_values, strict=False):
        normalized_row[field] = value

    return normalized_row


def _read_csv_rows(lines: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Read CSV text lines into fieldnames and rows while preserving inline comments."""
    prepared_lines = _prepare_csv_lines(lines)
    if not prepared_lines:
        return [], []

    reader = csv.DictReader(io.StringIO("\n".join(line for line, _ in prepared_lines)))
    fieldnames = reader.fieldnames or []
    rows = list(reader)
    comments = [comment for _, comment in prepared_lines[1:]]

    for row, comment in zip(rows, comments, strict=False):
        row[_INLINE_COMMENT_FIELD] = comment

    return fieldnames, rows


def _prepare_csv_lines(lines: list[str]) -> list[tuple[str, str]]:
    """Return non-empty CSV lines paired with stripped inline comments."""
    prepared_lines: list[tuple[str, str]] = []

    for line in lines:
        cleaned_line, comment = _split_inline_comment(line)
        cleaned_line = cleaned_line.strip()
        if not cleaned_line:
            continue
        prepared_lines.append((cleaned_line, comment))

    return prepared_lines


def _split_inline_comment(line: str, marker: str = "#") -> tuple[str, str]:
    """Split one CSV line at an unquoted comment marker."""
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
            return line[:index], line[index + 1 :].strip()
        index += 1

    return line, ""


def _write_compact_csv_rows(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    """Write CSV rows with trailing empty values trimmed and comments preserved."""
    with path.open("w", newline="", encoding="utf-8") as file:
        header_buffer = io.StringIO()
        header_writer = csv.writer(header_buffer, lineterminator="")
        header_writer.writerow(fieldnames)
        file.write(f"{header_buffer.getvalue()}\n")

        for row in rows:
            values = [_clean(row.get(field)) for field in fieldnames]
            while values and values[-1] == "":
                values.pop()
            row_buffer = io.StringIO()
            row_writer = csv.writer(row_buffer, lineterminator="")
            row_writer.writerow(values)
            line = row_buffer.getvalue()
            comment = _clean(row.get(_INLINE_COMMENT_FIELD))
            if comment:
                file.write(f"{line} # {comment}\n")
                continue
            file.write(f"{line}\n")


def _looks_like_shifted_rule_id_row(row: dict[str, str]) -> bool:
    """Return whether a row appears shifted because it lacks a leading rule ID."""
    rule_id_value = row.get(CSV_RULE_ID, "")
    enabled_value = row.get(CSV_ENABLED, "")

    if not rule_id_value or _try_parse_positive_int(rule_id_value) is not None:
        return False

    if not _looks_like_bool_token(rule_id_value):
        return False

    return not _looks_like_bool_token(enabled_value)


def _looks_like_bool_token(value: str) -> bool:
    """Return whether text is one of the scheduler's accepted boolean tokens."""
    return _clean(value).lower() in {"1", "true", "yes", "y", "ja", "j", "0", "false", "no", "n", "nee"}


def _build_change_log_row(
    entry: ChangeLogEntry,
    fieldnames: list[str],
) -> dict[str, str]:
    """Convert a change-log entry into a CSV row honoring existing fieldnames."""
    programme_timezone = (
        entry.programme.start_datetime.tzname()
        or entry.programme.end_datetime.tzname()
        or entry.run_datetime.tzname()
        or ""
    )

    row = {
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
        "source_epg": entry.programme.epg_entity,
        "programme_description": entry.programme.description,
    }
    if "rule_id" in fieldnames:
        row["rule_id"] = str(entry.rule.rule_id)
    if "rule_row" in fieldnames:
        row["rule_row"] = str(entry.rule.rule_id)
    # Only emit keys present in the active header to support legacy files safely.
    return {fieldname: row.get(fieldname, "") for fieldname in fieldnames}


def _normalize_change_log_fieldname(fieldname: str) -> str:
    """Map known malformed legacy change-log header names to supported ones."""
    normalized = _clean(fieldname)
    lowered = normalized.lower()

    if lowered in {"f4type", "\ufefftype"}:
        return "type"

    return normalized


def _resolve_change_log_fieldnames(path: Path, write_header: bool) -> list[str]:
    """Return the change-log CSV fields to write, preserving legacy headers."""
    if write_header:
        return [
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
            "rule_id",
            "source_epg",
            "programme_description",
        ]

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        existing_header = next(reader, [])

    normalized_header = [
        _normalize_change_log_fieldname(fieldname)
        for fieldname in existing_header
    ]

    if normalized_header != existing_header:
        _LOGGER.warning(
            "TV Auto Scheduler: normalized malformed change-log header in %s",
            path,
        )

    if "rule_id" in normalized_header:
        return normalized_header

    if "rule_row" in normalized_header:
        return normalized_header

    return [
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
        "rule_id",
        "source_epg",
        "programme_description",
    ]


def _format_change_log_datetime(value: datetime) -> str:
    """Format a datetime for the scheduler CSV logs."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _as_bool(value: Any, default: bool = False) -> bool:
    """Parse scheduler boolean tokens, returning default for blank values."""
    if value is None or value == "":
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "ja", "j"}


def _clean(value: Any) -> str:
    """Return a stripped string representation or an empty string for None."""
    return "" if value is None else str(value).strip()
