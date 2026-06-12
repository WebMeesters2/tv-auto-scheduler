from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DRY_RUN,
    CONF_PRE_CALENDAR,
    CONF_RULES_FILE,
    CONF_SHOW_MISSING_EPG,
    CONF_TV_CALENDAR,
    DEFAULT_PRE_CALENDAR,
    DEFAULT_RULES_FILE,
    DEFAULT_TV_CALENDAR,
    DOMAIN,
    SERVICE_SCAN,
)
from .scheduler import (
    calendar_event_exists,
    create_calendar_event,
    find_matches,
    load_rules,
    log_matches,
    remove_rules_by_row_numbers,
    scan_epg,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SCAN_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_RULES_FILE, default=DEFAULT_RULES_FILE): cv.path,
        vol.Optional(CONF_DRY_RUN, default=True): cv.boolean,
        vol.Optional(CONF_PRE_CALENDAR, default=DEFAULT_PRE_CALENDAR): cv.entity_id,
        vol.Optional(CONF_TV_CALENDAR, default=DEFAULT_TV_CALENDAR): cv.entity_id,
        vol.Optional(CONF_SHOW_MISSING_EPG, default=False): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def async_scan(call: ServiceCall) -> None:
        _LOGGER.debug("TV Auto Scheduler: scan service called")

        rules_file = call.data[CONF_RULES_FILE]
        dry_run = call.data[CONF_DRY_RUN]
        pre_calendar = call.data[CONF_PRE_CALENDAR]
        tv_calendar = call.data[CONF_TV_CALENDAR]
        show_missing_epg = call.data[CONF_SHOW_MISSING_EPG]
        _LOGGER.debug(
            "Starting scan (rules_file=%s, dry_run=%s)",
            rules_file,
            dry_run,
        )

        try:
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

            for rule, programme in matches:
                _LOGGER.debug(
                    "Match datetime: %s | %s | %s → %s",
                    programme.channel_name,
                    programme.title,
                    programme.start_datetime,
                    programme.end_datetime,
                )

            log_matches(matches)

            if dry_run:
                _LOGGER.info(
                    "TV Auto Scheduler: dry-run enabled, no calendars changed"
                )
            else:
                created = 0
                skipped = 0
                rules_to_delete: set[int] = set()

                for rule, programme in matches:
                    targets = []
                    created_for_match = False

                    if rule.pre:
                        targets.append(pre_calendar)

                    if rule.tv:
                        targets.append(tv_calendar)

                    for calendar_entity in targets:
                        if await calendar_event_exists(hass, calendar_entity, programme):
                            skipped += 1
                            _LOGGER.debug(
                                "Skipping existing event: %s | %s | %s",
                                calendar_entity,
                                programme.start_datetime,
                                programme.title,
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

                _LOGGER.info(
                    "TV Auto Scheduler: created %s event(s), skipped %s existing event(s), removed %s used rule(s)",
                    created,
                    skipped,
                    removed_rules,
                )

        except Exception:
            _LOGGER.exception("TV Auto Scheduler scan failed")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN,
        async_scan,
        schema=SERVICE_SCAN_SCHEMA,
    )

    return True
