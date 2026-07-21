from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "custom_components" / "tv_auto_scheduler"


def _install_homeassistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    calendar = types.ModuleType("homeassistant.components.calendar")
    calendar_const = types.ModuleType("homeassistant.components.calendar.const")
    core = types.ModuleType("homeassistant.core")
    exceptions = types.ModuleType("homeassistant.exceptions")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    class HomeAssistant:
        pass

    class HomeAssistantError(Exception):
        pass

    class CalendarEntityFeature:
        CREATE_EVENT = 1
        DELETE_EVENT = 2
        UPDATE_EVENT = 4

    dt.now = lambda: datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    dt.as_local = lambda value: value.astimezone(timezone.utc)
    dt.start_of_local_day = lambda value: value.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    calendar_const.CalendarEntityFeature = CalendarEntityFeature
    calendar_const.DATA_COMPONENT = "calendar_component"
    core.HomeAssistant = HomeAssistant
    exceptions.HomeAssistantError = HomeAssistantError
    calendar.const = calendar_const
    components.calendar = calendar
    util.dt = dt
    homeassistant.core = core
    homeassistant.components = components
    homeassistant.exceptions = exceptions
    homeassistant.util = util

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.calendar"] = calendar
    sys.modules["homeassistant.components.calendar.const"] = calendar_const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {module_name} from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_scheduler_module():
    _install_homeassistant_stubs()

    custom_components = sys.modules.setdefault(
        "custom_components",
        types.ModuleType("custom_components"),
    )
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]

    package = sys.modules.setdefault(
        "custom_components.tv_auto_scheduler",
        types.ModuleType("custom_components.tv_auto_scheduler"),
    )
    package.__path__ = [str(PACKAGE_DIR)]

    sys.modules.pop("custom_components.tv_auto_scheduler.const", None)
    sys.modules.pop("custom_components.tv_auto_scheduler.scheduler", None)

    _load_module(
        "custom_components.tv_auto_scheduler.const",
        PACKAGE_DIR / "const.py",
    )
    return _load_module(
        "custom_components.tv_auto_scheduler.scheduler",
        PACKAGE_DIR / "scheduler.py",
    )


class FakeState:
    def __init__(self, attributes: dict):
        self.attributes = attributes


class FakeStateMachine:
    def __init__(self, states: dict[str, FakeState]):
        self._states = states

    def get(self, entity_id: str):
        return self._states.get(entity_id)


class FakeHass:
    def __init__(self, states: dict[str, FakeState]):
        self.states = FakeStateMachine(states)
        self.services = types.SimpleNamespace(async_call=self._async_call)
        self.service_calls: list[tuple[str, str, dict, bool, bool]] = []
        self.data: dict[str, object] = {}

    async def _async_call(
        self,
        domain: str,
        service: str,
        data: dict,
        blocking: bool = False,
        return_response: bool = False,
    ):
        self.service_calls.append(
            (domain, service, data, blocking, return_response)
        )
        return {}


class FakeCalendarEvent:
    def __init__(
        self,
        *,
        uid: str,
        summary: str,
        description: str,
        start_datetime: datetime,
        end_datetime: datetime,
        recurrence_id: str | None = None,
    ):
        self.uid = uid
        self.summary = summary
        self.description = description
        self.start_datetime_local = start_datetime
        self.end_datetime_local = end_datetime
        self.recurrence_id = recurrence_id


class FakeCalendarEntity:
    def __init__(self, events: list[FakeCalendarEvent], supported_features: int):
        self.events = list(events)
        self.supported_features = supported_features
        self.deleted: list[tuple[str, str | None]] = []

    async def async_get_events(self, hass, start_date, end_date):
        return list(self.events)

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        self.deleted.append((uid, recurrence_id))
        self.events = [event for event in self.events if event.uid != uid]


class FakeCalendarComponent:
    def __init__(self, entities: dict[str, FakeCalendarEntity]):
        self.entities = entities

    def get_entity(self, entity_id: str):
        return self.entities.get(entity_id)


class SchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scheduler = load_scheduler_module()

    def test_channel_patterns_use_real_regex_matching(self) -> None:
        rule = self.scheduler.ScheduleRule(
            enabled=True,
            channel_pattern=r"BBC1|BBC2",
            programme="Bargain Hunt",
            pre=False,
            tv=True,
        )
        programme = self.scheduler.EpgProgramme(
            channel_key="BBC2",
            channel_name="BBC 2",
            epg_entity="sensor.epg_bbc2",
            title="Bargain Hunt",
            description="A daytime antiques quiz.",
            start="14:00",
            end="15:00",
            start_datetime=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(self.scheduler._matches_channel(rule, programme))

    def test_build_programme_datetimes_rolls_end_into_next_day(self) -> None:
        start, end = self.scheduler._build_programme_datetimes(0, "23:55", "00:10")

        self.assertEqual(start.isoformat(), "2026-06-08T23:55:00+00:00")
        self.assertEqual(end.isoformat(), "2026-06-09T00:10:00+00:00")

    def test_scan_epg_skips_invalid_time_values(self) -> None:
        hass = FakeHass(
            {
                "sensor.tv_channel_database": FakeState(
                    {
                        "channels": {
                            "bbc1": {
                                "aliases": ["BBC1"],
                                "epg": "sensor.epg_bbc1",
                            }
                        }
                    }
                ),
                "sensor.epg_bbc1": FakeState(
                    {
                        "today": {
                            "0": {
                                "title": "Valid Show",
                                "desc": "A valid description.",
                                "start": "14:00",
                                "end": "15:00",
                            },
                            "1": {
                                "title": "Broken Show",
                                "start": "bad",
                                "end": "16:00",
                            },
                        }
                    }
                ),
            }
        )

        programmes = self.scheduler.scan_epg(hass)

        self.assertEqual(len(programmes), 1)
        self.assertEqual(programmes[0].title, "Valid Show")
        self.assertEqual(programmes[0].description, "A valid description.")
        self.assertIsInstance(programmes[0].start_datetime, datetime)

    def test_extract_calendar_events_response_supports_nested_shape(self) -> None:
        response = {
            "calendar.televisie": {
                "events": [
                    {
                        "summary": "BBC1 | Bargain Hunt",
                    }
                ]
            }
        }

        events = self.scheduler._extract_calendar_events_response(
            response,
            "calendar.televisie",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["summary"], "BBC1 | Bargain Hunt")

    def test_load_rules_supports_optional_delete_and_time_filters(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "12,y,BBC.*,Bargain Hunt,n,y,y,,mon|wed,14:00,16:00",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            rules = self.scheduler.load_rules(str(rules_file))

        self.assertEqual(len(rules), 1)
        self.assertTrue(rules[0].delete_after_use)
        self.assertEqual(rules[0].rule_id, 12)
        self.assertEqual(rules[0].filter_start_days, frozenset({0, 2}))
        self.assertEqual(rules[0].filter_start_time.isoformat(), "14:00:00")
        self.assertEqual(rules[0].filter_end_time.isoformat(), "16:00:00")
        self.assertEqual(rules[0].row_number, 2)

    def test_load_rules_supports_named_time_ranges(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "8,y,RTL4,Het Perfecte Plaatje,y,y,n,primetime",
            ]
        )
        named_time_ranges_content = "\n".join(
            [
                "key,filter-start-day,filter-start-time,filter-end-time",
                "primetime,,20:00,22:00",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            named_time_ranges_file = Path(temp_dir) / "named_time_ranges.csv"
            rules_file.write_text(csv_content, encoding="utf-8")
            named_time_ranges_file.write_text(named_time_ranges_content, encoding="utf-8")

            rules = self.scheduler.load_rules(str(rules_file))

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].rule_id, 8)
        self.assertIsNone(rules[0].filter_start_days)
        self.assertEqual(rules[0].filter_start_time.isoformat(), "20:00:00")
        self.assertEqual(rules[0].filter_end_time.isoformat(), "22:00:00")

    def test_load_rules_accepts_rows_where_rule_id_column_was_omitted(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "y,RTL4,Het Perfecte Plaatje,y,y,n,primetime",
            ]
        )
        named_time_ranges_content = "\n".join(
            [
                "key,filter-start-day,filter-start-time,filter-end-time",
                "primetime,,20:00,22:00",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            named_time_ranges_file = Path(temp_dir) / "named_time_ranges.csv"
            rules_file.write_text(csv_content, encoding="utf-8")
            named_time_ranges_file.write_text(named_time_ranges_content, encoding="utf-8")

            rules = self.scheduler.load_rules(str(rules_file))

        self.assertEqual(len(rules), 1)
        self.assertTrue(rules[0].enabled)
        self.assertEqual(rules[0].channel_pattern, "RTL4")
        self.assertEqual(rules[0].programme, "Het Perfecte Plaatje")
        self.assertEqual(rules[0].rule_id, 1)
        self.assertEqual(rules[0].filter_start_time.isoformat(), "20:00:00")
        self.assertEqual(rules[0].filter_end_time.isoformat(), "22:00:00")

    def test_load_rules_ignores_inline_comments(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "71,y,BBC[1-2],Impossible,y,y,,afternoon # weekday afternoon catch-up",
            ]
        )
        named_time_ranges_content = "\n".join(
            [
                "key,filter-start-day,filter-start-time,filter-end-time",
                "afternoon,,14:00,18:00",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            named_time_ranges_file = Path(temp_dir) / "named_time_ranges.csv"
            rules_file.write_text(csv_content, encoding="utf-8")
            named_time_ranges_file.write_text(named_time_ranges_content, encoding="utf-8")

            rules = self.scheduler.load_rules(str(rules_file))

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].rule_id, 71)
        self.assertEqual(rules[0].channel_pattern, "BBC[1-2]")
        self.assertEqual(rules[0].programme, "Impossible")
        self.assertEqual(rules[0].filter_start_time.isoformat(), "14:00:00")
        self.assertEqual(rules[0].filter_end_time.isoformat(), "18:00:00")

    def test_ensure_rules_file_schema_adds_columns_and_assigns_rule_ids(self) -> None:
        csv_content = "\n".join(
            [
                "enabled,channel,programme,pre,tv,flag-delete-after-use",
                "y,BBC.*,Bargain Hunt,n,y,y",
                "y,NPO.*,The Connection,y,y,n",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed = self.scheduler.ensure_rules_file_schema(str(rules_file))

            with rules_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertTrue(changed)
        self.assertEqual(
            list(rows[0].keys()),
            [
                "rule-id",
                "enabled",
                "channel",
                "programme",
                "pre",
                "tv",
                "flag-delete-after-use",
                "named-time-range",
                "filter-start-day",
                "filter-start-time",
                "filter-end-time",
            ],
        )
        self.assertEqual([row["rule-id"] for row in rows], ["1", "2"])

    def test_ensure_rules_file_schema_preserves_existing_rule_ids_and_appends_new_ones(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "10,y,BBC.*,Bargain Hunt,n,y,n",
                ",y,NPO.*,The Connection,y,y,n",
                "25,y,RTL4,Het Perfecte Plaatje,y,y,n,primetime",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed = self.scheduler.ensure_rules_file_schema(str(rules_file))

            with rules_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertTrue(changed)
        self.assertEqual([row["rule-id"] for row in rows], ["10", "26", "25"])

    def test_ensure_rules_file_schema_preserves_inline_comments_on_compact_rewrite(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "y,BBC[1-2],Impossible,y,y,,afternoon # readable comment",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed = self.scheduler.ensure_rules_file_schema(str(rules_file))
            updated = rules_file.read_text(encoding="utf-8").splitlines()

        self.assertTrue(changed)
        self.assertEqual(
            updated,
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "1,y,BBC[1-2],Impossible,y,y,,afternoon # readable comment",
            ],
        )

    def test_find_matches_applies_start_time_filter(self) -> None:
        rule = self.scheduler.ScheduleRule(
            enabled=True,
            channel_pattern=r"BBC1",
            programme="Bargain Hunt",
            pre=False,
            tv=True,
            filter_start_time=self.scheduler._parse_time_value("14:00"),
            filter_end_time=self.scheduler._parse_time_value("15:00"),
        )
        matching_programme = self.scheduler.EpgProgramme(
            channel_key="BBC1",
            channel_name="BBC 1",
            epg_entity="sensor.epg_bbc1",
            title="Bargain Hunt",
            description="A daytime antiques quiz.",
            start="14:30",
            end="15:15",
            start_datetime=datetime(2026, 6, 8, 14, 30, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 8, 15, 15, tzinfo=timezone.utc),
        )
        non_matching_programme = self.scheduler.EpgProgramme(
            channel_key="BBC1",
            channel_name="BBC 1",
            epg_entity="sensor.epg_bbc1",
            title="Bargain Hunt",
            description="An evening repeat.",
            start="16:00",
            end="17:00",
            start_datetime=datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 8, 17, 0, tzinfo=timezone.utc),
        )

        matches = self.scheduler.find_matches(
            [rule],
            [matching_programme, non_matching_programme],
        )

        self.assertEqual(matches, [(rule, matching_programme)])

    def test_find_matches_applies_start_day_filter(self) -> None:
        rule = self.scheduler.ScheduleRule(
            enabled=True,
            channel_pattern=r"BBC1",
            programme="Bargain Hunt",
            pre=False,
            tv=True,
            filter_start_days=frozenset({0, 2}),
        )
        monday_programme = self.scheduler.EpgProgramme(
            channel_key="BBC1",
            channel_name="BBC 1",
            epg_entity="sensor.epg_bbc1",
            title="Bargain Hunt",
            description="A daytime antiques quiz.",
            start="14:30",
            end="15:15",
            start_datetime=datetime(2026, 6, 8, 14, 30, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 8, 15, 15, tzinfo=timezone.utc),
        )
        tuesday_programme = self.scheduler.EpgProgramme(
            channel_key="BBC1",
            channel_name="BBC 1",
            epg_entity="sensor.epg_bbc1",
            title="Bargain Hunt",
            description="A daytime antiques quiz.",
            start="14:30",
            end="15:15",
            start_datetime=datetime(2026, 6, 9, 14, 30, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 9, 15, 15, tzinfo=timezone.utc),
        )

        matches = self.scheduler.find_matches(
            [rule],
            [monday_programme, tuesday_programme],
        )

        self.assertEqual(matches, [(rule, monday_programme)])

    def test_parse_start_day_filter_supports_dutch_and_english_names(self) -> None:
        row = {"filter-start-day": "maandag|wed|vrijdag"}

        result = self.scheduler._parse_start_day_filter(row, 2)

        self.assertEqual(result, frozenset({0, 2, 4}))

    def test_parse_start_day_filter_supports_ranges(self) -> None:
        row = {"filter-start-day": "mon-fri|sun"}

        result = self.scheduler._parse_start_day_filter(row, 2)

        self.assertEqual(result, frozenset({0, 1, 2, 3, 4, 6}))

    def test_parse_start_day_filter_supports_wraparound_ranges(self) -> None:
        row = {"filter-start-day": "fri-mon"}

        result = self.scheduler._parse_start_day_filter(row, 2)

        self.assertEqual(result, frozenset({4, 5, 6, 0}))

    def test_create_calendar_event_appends_epg_description(self) -> None:
        hass = FakeHass({})
        rule = self.scheduler.ScheduleRule(
            enabled=True,
            channel_pattern=r"BBC1",
            programme="Bargain Hunt",
            pre=False,
            tv=True,
        )
        programme = self.scheduler.EpgProgramme(
            channel_key="BBC1",
            channel_name="BBC 1",
            epg_entity="sensor.epg_bbc1",
            title="Bargain Hunt",
            description="A daytime antiques quiz.",
            start="14:00",
            end="15:00",
            start_datetime=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
        )

        import asyncio

        asyncio.run(
            self.scheduler.create_calendar_event(
                hass,
                "calendar.televisie",
                rule,
                programme,
            )
        )

        self.assertEqual(len(hass.service_calls), 1)
        _, _, data, _, _ = hass.service_calls[0]
        self.assertEqual(data["summary"], "BBC 1 | Bargain Hunt")
        self.assertIn("TV_AUTO_SCHEDULER: true", data["description"])
        self.assertIn("Rule: Bargain Hunt", data["description"])
        self.assertIn("Source: sensor.epg_bbc1", data["description"])
        self.assertIn("Programme: A daytime antiques quiz.", data["description"])

    def test_build_change_log_path_uses_rules_directory(self) -> None:
        rules_file = "/config/tv_auto_scheduler/rules.csv"

        change_log = self.scheduler.build_change_log_path(rules_file)

        self.assertEqual(
            change_log,
            "/config/tv_auto_scheduler/tv_auto_scheduler_changes.csv",
        )

    def test_build_dry_run_log_path_uses_rules_directory(self) -> None:
        dry_run_log = self.scheduler.build_dry_run_log_path(
            "/config/tv_auto_scheduler/rules.csv"
        )

        self.assertEqual(
            dry_run_log,
            "/config/tv_auto_scheduler/tv_auto_scheduler_dry_run.csv",
        )

    def test_resolve_change_log_path_prefers_explicit_value(self) -> None:
        resolved = self.scheduler.resolve_change_log_path(
            "/config/tv_auto_scheduler/rules.csv",
            "/config/logs/custom_changes.csv",
        )

        self.assertEqual(resolved, "/config/logs/custom_changes.csv")

    def test_append_change_log_writes_excel_friendly_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "tv_auto_scheduler_changes.csv"
            rule = self.scheduler.ScheduleRule(
                enabled=True,
                channel_pattern=r"npo[12]",
                programme="NOS Journaal",
                pre=False,
                tv=True,
                row_number=7,
                rule_id=7,
            )
            programme = self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="NOS Journaal",
                description="Het laatste nieuws.",
                start="20:00",
                end="20:30",
                start_datetime=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc),
                end_datetime=datetime(2026, 6, 10, 20, 30, tzinfo=timezone.utc),
            )
            entry = self.scheduler.ChangeLogEntry(
                change_type="Add",
                run_datetime=datetime(2026, 6, 9, 6, 0, tzinfo=timezone.utc),
                calendar_entity="calendar.televisie",
                programme=programme,
                rule=rule,
            )

            written = self.scheduler.append_change_log(str(log_file), [entry])

            with log_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(written, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "Add")
        self.assertEqual(rows[0]["run_at"], "2026-06-09 06:00:00")
        self.assertEqual(rows[0]["start_at"], "2026-06-10 20:00:00")
        self.assertEqual(rows[0]["end_at"], "2026-06-10 20:30:00")
        self.assertEqual(rows[0]["timezone"], "UTC")
        self.assertEqual(rows[0]["calendar"], "calendar.televisie")
        self.assertEqual(rows[0]["channel"], "npo1")
        self.assertEqual(rows[0]["channel_name"], "NPO 1")
        self.assertEqual(rows[0]["programme"], "NOS Journaal")
        self.assertEqual(rows[0]["rule"], "NOS Journaal")
        self.assertEqual(rows[0]["rule_id"], "7")
        self.assertEqual(rows[0]["source_epg"], "sensor.epg_npo1")
        self.assertEqual(rows[0]["programme_description"], "Het laatste nieuws.")

    def test_append_change_log_accepts_legacy_f4type_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "tv_auto_scheduler_changes.csv"
            log_file.write_text(
                "F4type,run_at,start_at,end_at,timezone,calendar,channel,"
                "channel_name,programme,rule,rule_row,source_epg,"
                "programme_description\n",
                encoding="utf-8",
            )
            rule = self.scheduler.ScheduleRule(
                enabled=True,
                channel_pattern=r"npo[12]",
                programme="NOS Journaal",
                pre=False,
                tv=True,
                row_number=7,
                rule_id=7,
            )
            programme = self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="NOS Journaal",
                description="Het laatste nieuws.",
                start="20:00",
                end="20:30",
                start_datetime=datetime(2026, 6, 10, 20, 0, tzinfo=timezone.utc),
                end_datetime=datetime(2026, 6, 10, 20, 30, tzinfo=timezone.utc),
            )
            entry = self.scheduler.ChangeLogEntry(
                change_type="Add",
                run_datetime=datetime(2026, 6, 9, 6, 0, tzinfo=timezone.utc),
                calendar_entity="calendar.televisie",
                programme=programme,
                rule=rule,
            )

            written = self.scheduler.append_change_log(str(log_file), [entry])

            with log_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(written, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["F4type"], "Add")
        self.assertEqual(rows[0]["rule_row"], "7")


    def test_remove_rules_by_row_numbers_removes_only_selected_rows(self) -> None:
        csv_content = "\n".join(
            [
                "enabled,channel,programme,pre,tv,flag-delete-after-use",
                "y,BBC.*,Bargain Hunt,n,y,y",
                "y,NPO.*,The Connection,y,y,n",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            removed = self.scheduler.remove_rules_by_row_numbers(str(rules_file), {2})
            updated = rules_file.read_text(encoding="utf-8").splitlines()

        self.assertEqual(removed, 1)
        self.assertEqual(
            updated,
            [
                "enabled,channel,programme,pre,tv,flag-delete-after-use",
                "y,NPO.*,The Connection,y,y,n",
            ],
        )

    def test_find_existing_auto_calendar_events_detects_shifted_match(self) -> None:
        hass = FakeHass({})
        existing_event = FakeCalendarEvent(
            uid="abc123",
            summary="RTL 4 | Beste Kijkers",
            description=(
                "TV_AUTO_SCHEDULER: true\n"
                "Rule: Beste Kijkers\n"
                "Source: sensor.woonkamer_epg_fmqn5gzdfv_rtl_4\n"
            ),
            start_datetime=datetime(2026, 6, 20, 21, 35, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 20, 22, 45, tzinfo=timezone.utc),
        )
        hass.data["calendar_component"] = FakeCalendarComponent(
            {"calendar.televisie": FakeCalendarEntity([existing_event], supported_features=2)}
        )
        programme = self.scheduler.EpgProgramme(
            channel_key="rtl4",
            channel_name="RTL 4",
            epg_entity="sensor.woonkamer_epg_fmqn5gzdfv_rtl_4",
            title="Beste Kijkers",
            description="Beste kijkers",
            start="21:37",
            end="22:47",
            start_datetime=datetime(2026, 6, 20, 21, 37, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 20, 22, 47, tzinfo=timezone.utc),
        )

        import asyncio

        exact_match, shifted_matches = asyncio.run(
            self.scheduler.find_existing_auto_calendar_events(
                hass,
                "calendar.televisie",
                programme,
            )
        )

        self.assertIsNone(exact_match)
        self.assertEqual(len(shifted_matches), 1)
        self.assertEqual(shifted_matches[0].uid, "abc123")

    def test_replace_calendar_event_deletes_stale_event_before_creating_new_one(self) -> None:
        hass = FakeHass({})
        stale_event = FakeCalendarEvent(
            uid="abc123",
            summary="RTL 4 | Oh, wat een jaar!",
            description=(
                "TV_AUTO_SCHEDULER: true\n"
                "Rule: Oh, wat een Jaar!\n"
                "Source: sensor.woonkamer_epg_fmqn5gzdfv_rtl_4\n"
            ),
            start_datetime=datetime(2026, 6, 20, 20, 5, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 20, 21, 35, tzinfo=timezone.utc),
        )
        calendar_entity = FakeCalendarEntity([stale_event], supported_features=2)
        hass.data["calendar_component"] = FakeCalendarComponent(
            {"calendar.televisie": calendar_entity}
        )
        rule = self.scheduler.ScheduleRule(
            enabled=True,
            channel_pattern=r"rtl4",
            programme=r"Oh, wat een Jaar!",
            pre=False,
            tv=True,
        )
        programme = self.scheduler.EpgProgramme(
            channel_key="rtl4",
            channel_name="RTL 4",
            epg_entity="sensor.woonkamer_epg_fmqn5gzdfv_rtl_4",
            title="Oh, wat een jaar!",
            description="Oh, Wat een Jaar!",
            start="20:08",
            end="21:37",
            start_datetime=datetime(2026, 6, 20, 20, 8, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 20, 21, 37, tzinfo=timezone.utc),
        )
        shifted_match = self.scheduler.ExistingAutoCalendarEvent(
            uid="abc123",
            recurrence_id=None,
            summary="RTL 4 | Oh, wat een jaar!",
            start_datetime=datetime(2026, 6, 20, 20, 5, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 20, 21, 35, tzinfo=timezone.utc),
        )

        import asyncio

        removed = asyncio.run(
            self.scheduler.replace_calendar_event(
                hass,
                "calendar.televisie",
                rule,
                programme,
                [shifted_match],
            )
        )

        self.assertEqual(removed, 1)
        self.assertEqual(calendar_entity.deleted, [("abc123", None)])
        self.assertEqual(len(hass.service_calls), 1)
        _, _, data, _, _ = hass.service_calls[0]
        self.assertEqual(data["summary"], "RTL 4 | Oh, wat een jaar!")
        self.assertEqual(data["start_date_time"], "2026-06-20T20:08:00+00:00")
        self.assertEqual(data["end_date_time"], "2026-06-20T21:37:00+00:00")


if __name__ == "__main__":
    unittest.main()
