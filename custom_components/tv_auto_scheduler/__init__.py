from __future__ import annotations

import logging
from functools import partial

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .canalplus import CanalPlusClient
from .canalplus_compare import build_canalplus_comparison_report
from .const import (
    CONF_CANALPLUS_AUTHORIZATION,
    CONF_CANALPLUS_CHANNELS,
    CONF_CHANGE_LOG,
    CONF_CHANGE_LOG_FILE,
    CONF_COMPARISON_REPORT_FILE,
    CONF_DRY_RUN,
    CONF_DRY_RUN_LOG,
    CONF_DRY_RUN_LOG_FILE,
    CONF_PRE_CALENDAR,
    CONF_RULES_FILE,
    CONF_SHOW_MISSING_EPG,
    CONF_TV_CALENDAR,
    DEFAULT_PRE_CALENDAR,
    DEFAULT_RULES_FILE,
    DEFAULT_TV_CALENDAR,
    DOMAIN,
    SERVICE_COMPARE_CANALPLUS,
    SERVICE_SCAN,
)
from .scheduler import (
    ChangeLogEntry,
    append_change_log,
    create_calendar_event,
    ensure_rules_file_schema,
    find_existing_auto_calendar_events,
    find_matches,
    load_rules,
    log_matches,
    remove_rules_by_row_numbers,
    replace_calendar_event,
    resolve_change_log_path,
    resolve_dry_run_log_path,
    scan_epg,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_COMPARE_CANALPLUS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CANALPLUS_AUTHORIZATION): cv.string,
        vol.Required(CONF_CANALPLUS_CHANNELS): vol.Schema({cv.string: cv.string}),
        vol.Optional(CONF_COMPARISON_REPORT_FILE): cv.path,
        vol.Optional(CONF_SHOW_MISSING_EPG, default=False): cv.boolean,
    }
)


SERVICE_SCAN_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_RULES_FILE, default=DEFAULT_RULES_FILE): cv.path,
        vol.Optional(CONF_DRY_RUN, default=True): cv.boolean,
        vol.Optional(CONF_DRY_RUN_LOG, default=False): cv.boolean,
        vol.Optional(CONF_DRY_RUN_LOG_FILE): cv.path,
        vol.Optional(CONF_PRE_CALENDAR, default=DEFAULT_PRE_CALENDAR): cv.entity_id,
        vol.Optional(CONF_TV_CALENDAR, default=DEFAULT_TV_CALENDAR): cv.entity_id,
        vol.Optional(CONF_SHOW_MISSING_EPG, default=False): cv.boolean,
        vol.Optional(CONF_CHANGE_LOG, default=False): cv.boolean,
        vol.Optional(CONF_CHANGE_LOG_FILE): cv.path,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def async_scan(call: ServiceCall) -> None:
        _LOGGER.debug("TV Auto Scheduler: scan service called")

        rules_file = call.data[CONF_RULES_FILE]
        dry_run = call.data[CONF_DRY_RUN]
        dry_run_log = call.data[CONF_DRY_RUN_LOG]
        dry_run_log_file = call.data.get(CONF_DRY_RUN_LOG_FILE)
        pre_calendar = call.data[CONF_PRE_CALENDAR]
        tv_calendar = call.data[CONF_TV_CALENDAR]
        show_missing_epg = call.data[CONF_SHOW_MISSING_EPG]
        change_log = call.data[CONF_CHANGE_LOG]
        change_log_file = call.data.get(CONF_CHANGE_LOG_FILE)
        run_started_at = dt_util.now()
        _LOGGER.debug(
            "Starting scan (rules_file=%s, dry_run=%s)",
            rules_file,
            dry_run,
        )

        try:
            schema_updated = await hass.async_add_executor_job(
                ensure_rules_file_schema,
                rules_file,
            )
            if schema_updated:
                _LOGGER.info(
                    "TV Auto Scheduler: updated rules.csv schema and assigned "
                    "missing rule-id values"
                )

            rules = await hass.async_add_executor_job(
                load_rules,
                rules_file,
            )

            _LOGGER.debug("Loaded %s rules", len(rules))

            programmes = scan_epg(
                hass,
                show_missing_epg=show_missing_epg,
            )

            _LOGGER.debug("Found %s EPG programmes", len(programmes))

            matches = find_matches(rules, programmes)

            _LOGGER.debug("Found %s matches", len(matches))

            for _rule, programme in matches:
                _LOGGER.debug(
                    "Match datetime: %s | %s | %s → %s",
                    programme.channel_name,
                    programme.title,
                    programme.start_datetime,
                    programme.end_datetime,
                )

            log_matches(matches)

            if dry_run:
                dry_run_log_entries: list[ChangeLogEntry] = []

                if dry_run_log:
                    for rule, programme in matches:
                        targets = []
                        if rule.pre:
                            targets.append(pre_calendar)
                        if rule.tv:
                            targets.append(tv_calendar)

                        for calendar_entity in targets:
                            (
                                exact_match,
                                stale_events,
                            ) = await find_existing_auto_calendar_events(
                                hass,
                                calendar_entity,
                                programme,
                            )
                            if exact_match is not None:
                                continue

                            if stale_events:
                                for stale_event in stale_events:
                                    dry_run_log_entries.append(
                                        ChangeLogEntry(
                                            change_type="WouldDelete",
                                            run_datetime=run_started_at,
                                            calendar_entity=calendar_entity,
                                            programme=programme.__class__(
                                                channel_key=programme.channel_key,
                                                channel_name=programme.channel_name,
                                                epg_entity=programme.epg_entity,
                                                title=programme.title,
                                                description=programme.description,
                                                start=stale_event.start_datetime.strftime("%H:%M"),
                                                end=stale_event.end_datetime.strftime("%H:%M"),
                                                start_datetime=stale_event.start_datetime,
                                                end_datetime=stale_event.end_datetime,
                                            ),
                                            rule=rule,
                                        )
                                    )
                                dry_run_log_entries.append(
                                    ChangeLogEntry(
                                        change_type="WouldAdd",
                                        run_datetime=run_started_at,
                                        calendar_entity=calendar_entity,
                                        programme=programme,
                                        rule=rule,
                                    )
                                )
                                continue

                            dry_run_log_entries.append(
                                ChangeLogEntry(
                                    change_type="WouldAdd",
                                    run_datetime=run_started_at,
                                    calendar_entity=calendar_entity,
                                    programme=programme,
                                    rule=rule,
                                )
                            )

                dry_run_logged = 0
                if dry_run_log and dry_run_log_entries:
                    resolved_dry_run_log_file = resolve_dry_run_log_path(
                        rules_file,
                        dry_run_log_file,
                    )
                    dry_run_logged = await hass.async_add_executor_job(
                        append_change_log,
                        resolved_dry_run_log_file,
                        dry_run_log_entries,
                    )
                    _LOGGER.info(
                        "TV Auto Scheduler: wrote %s dry-run change row(s) to %s",
                        dry_run_logged,
                        resolved_dry_run_log_file,
                    )

                _LOGGER.info(
                    "TV Auto Scheduler: dry-run enabled, no calendars changed%s",
                    (
                        ""
                        if not dry_run_log
                        else f", logged {dry_run_logged} proposed change(s)"
                    ),
                )
            else:
                created = 0
                replaced = 0
                skipped = 0
                removed_existing = 0
                rules_to_delete: set[int] = set()
                change_log_entries: list[ChangeLogEntry] = []

                for rule, programme in matches:
                    targets = []
                    created_for_match = False

                    if rule.pre:
                        targets.append(pre_calendar)

                    if rule.tv:
                        targets.append(tv_calendar)

                    for calendar_entity in targets:
                        (
                            exact_match,
                            stale_events,
                        ) = await find_existing_auto_calendar_events(
                            hass,
                            calendar_entity,
                            programme,
                        )

                        if exact_match is not None:
                            skipped += 1
                            _LOGGER.debug(
                                "Skipping existing event: %s | %s | %s",
                                calendar_entity,
                                programme.start_datetime,
                                programme.title,
                            )
                            continue

                        if stale_events:
                            try:
                                removed = await replace_calendar_event(
                                    hass,
                                    calendar_entity,
                                    rule,
                                    programme,
                                    stale_events,
                                )
                            except Exception:
                                _LOGGER.exception(
                                    "TV Auto Scheduler: failed to replace shifted "
                                    "event for %s | %s | %s",
                                    calendar_entity,
                                    programme.start_datetime,
                                    programme.title,
                                )
                                skipped += 1
                                continue

                            replaced += 1
                            removed_existing += removed
                            created_for_match = True

                            if change_log:
                                for stale_event in stale_events:
                                    change_log_entries.append(
                                        ChangeLogEntry(
                                            change_type="Delete",
                                            run_datetime=run_started_at,
                                            calendar_entity=calendar_entity,
                                            programme=programme.__class__(
                                                channel_key=programme.channel_key,
                                                channel_name=programme.channel_name,
                                                epg_entity=programme.epg_entity,
                                                title=programme.title,
                                                description=programme.description,
                                                start=stale_event.start_datetime.strftime("%H:%M"),
                                                end=stale_event.end_datetime.strftime("%H:%M"),
                                                start_datetime=stale_event.start_datetime,
                                                end_datetime=stale_event.end_datetime,
                                            ),
                                            rule=rule,
                                        )
                                    )
                                change_log_entries.append(
                                    ChangeLogEntry(
                                        change_type="Add",
                                        run_datetime=run_started_at,
                                        calendar_entity=calendar_entity,
                                        programme=programme,
                                        rule=rule,
                                    )
                                )
                            continue

                        await create_calendar_event(
                            hass,
                            calendar_entity,
                            rule,
                            programme,
                        )
                        created += 1
                        created_for_match = True

                        if change_log:
                            change_log_entries.append(
                                ChangeLogEntry(
                                    change_type="Add",
                                    run_datetime=run_started_at,
                                    calendar_entity=calendar_entity,
                                    programme=programme,
                                    rule=rule,
                                )
                            )

                    if (
                        created_for_match
                        and rule.delete_after_use
                        and rule.row_number is not None
                    ):
                        rules_to_delete.add(rule.row_number)

                removed_rules = 0
                if rules_to_delete:
                    removed_rules = await hass.async_add_executor_job(
                        remove_rules_by_row_numbers,
                        rules_file,
                        rules_to_delete,
                    )

                logged_changes = 0
                if change_log and change_log_entries:
                    resolved_change_log_file = resolve_change_log_path(
                        rules_file,
                        change_log_file,
                    )
                    logged_changes = await hass.async_add_executor_job(
                        append_change_log,
                        resolved_change_log_file,
                        change_log_entries,
                    )
                    _LOGGER.debug(
                        "TV Auto Scheduler: wrote %s change log row(s) to %s",
                        logged_changes,
                        resolved_change_log_file,
                    )

                _LOGGER.info(
                    "TV Auto Scheduler: created %s event(s), replaced %s shifted "
                    "event(s), removed %s previous event(s), skipped %s existing "
                    "event(s), removed %s used rule(s), logged %s change(s)",
                    created,
                    replaced,
                    removed_existing,
                    skipped,
                    removed_rules,
                    logged_changes,
                )

        except Exception:
            _LOGGER.exception("TV Auto Scheduler scan failed")


    async def async_compare_canalplus(call: ServiceCall) -> None:
        _LOGGER.debug("TV Auto Scheduler: Canal+ comparison service called")

        authorization = call.data[CONF_CANALPLUS_AUTHORIZATION]
        channel_map = dict(call.data[CONF_CANALPLUS_CHANNELS])
        report_file = call.data.get(CONF_COMPARISON_REPORT_FILE)
        show_missing_epg = call.data[CONF_SHOW_MISSING_EPG]

        try:
            programmes = scan_epg(
                hass,
                show_missing_epg=show_missing_epg,
            )
            client = CanalPlusClient(authorization=authorization)
            report = await hass.async_add_executor_job(
                partial(
                    build_canalplus_comparison_report,
                    programmes,
                    client,
                    channel_map,
                    report_file=report_file,
                )
            )

            _LOGGER.info(
                "TV Auto Scheduler: Canal+ comparison complete "
                "(%s comparison row(s), counts=%s%s)",
                len(report.comparisons),
                report.counts,
                (
                    f", wrote {report.rows_written} row(s) to {report_file}"
                    if report_file
                    else ""
                ),
            )
        except Exception:
            _LOGGER.exception("TV Auto Scheduler Canal+ comparison failed")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN,
        async_scan,
        schema=SERVICE_SCAN_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE_CANALPLUS,
        async_compare_canalplus,
        schema=SERVICE_COMPARE_CANALPLUS_SCHEMA,
    )

    return True
