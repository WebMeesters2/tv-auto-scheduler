from __future__ import annotations

import csv
import importlib.util
import json
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

    dt.now = lambda: datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)  # noqa: UP017
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


def load_modules():
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

    for name in [
        "const",
        "scheduler",
        "epg_compare",
        "canalplus",
        "canalplus_compare",
    ]:
        sys.modules.pop(f"custom_components.tv_auto_scheduler.{name}", None)

    _load_module("custom_components.tv_auto_scheduler.const", PACKAGE_DIR / "const.py")
    _load_module(
        "custom_components.tv_auto_scheduler.scheduler",
        PACKAGE_DIR / "scheduler.py",
    )
    _load_module(
        "custom_components.tv_auto_scheduler.epg_compare",
        PACKAGE_DIR / "epg_compare.py",
    )
    _load_module(
        "custom_components.tv_auto_scheduler.canalplus",
        PACKAGE_DIR / "canalplus.py",
    )
    return _load_module(
        "custom_components.tv_auto_scheduler.canalplus_compare",
        PACKAGE_DIR / "canalplus_compare.py",
    )


class FakeCanalPlusClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, datetime, datetime]] = []

    def get_schedule(
        self,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict:
        self.requests.append((channel_id, start_at, end_at))
        return {
            "epg": {
                channel_id: [
                    {
                        "id": "asset-1",
                        "title": "Current Listing",
                        "params": {
                            "channelId": channel_id,
                            "start": "2026-07-09T20:00:00.000Z",
                            "end": "2026-07-09T21:00:00.000Z",
                        },
                    }
                ]
            }
        }


class CanalPlusCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compare = load_modules()
        cls.scheduler = sys.modules["custom_components.tv_auto_scheduler.scheduler"]

    def test_build_canalplus_comparison_report_writes_csv(self) -> None:
        client = FakeCanalPlusClient()
        open_epg_programmes = [
            self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="Old Listing",
                description="",
                start="20:00",
                end="21:00",
                start_datetime=datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc),  # noqa: UP017
                end_datetime=datetime(2026, 7, 9, 21, 0, tzinfo=timezone.utc),  # noqa: UP017
            )
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            report_file = Path(temp_dir) / "comparison.csv"
            report = self.compare.build_canalplus_comparison_report(
                open_epg_programmes,
                client,
                {"npo1": "canal-npo1"},
                report_file=str(report_file),
            )
            with report_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(client.requests[0][0], "canal-npo1")
        self.assertEqual(report.counts, {"replaced": 1})
        self.assertEqual(report.rows_written, 1)
        self.assertEqual(report.channel_count, 1)
        self.assertEqual(report.primary_count, 1)
        self.assertEqual(report.secondary_count, 1)
        self.assertEqual(report.fetch_error_count, 0)
        self.assertEqual(rows[0]["kind"], "replaced")
        self.assertEqual(rows[0]["channel"], "npo1")
        self.assertEqual(rows[0]["primary_title"], "Old Listing")
        self.assertEqual(rows[0]["secondary_title"], "Current Listing")


    def test_build_canalplus_comparison_report_skips_failed_channel(self) -> None:
        class FailingCanalPlusClient(FakeCanalPlusClient):
            def get_schedule(
                self,
                channel_id: str,
                start_at: datetime,
                end_at: datetime,
            ) -> dict:
                if channel_id == "bad-canal-id":
                    self.requests.append((channel_id, start_at, end_at))
                    raise RuntimeError("bad request")
                return super().get_schedule(channel_id, start_at, end_at)

        client = FailingCanalPlusClient()
        open_epg_programmes = [
            self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="Old Listing",
                description="",
                start="20:00",
                end="21:00",
                start_datetime=datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc),  # noqa: UP017
                end_datetime=datetime(2026, 7, 9, 21, 0, tzinfo=timezone.utc),  # noqa: UP017
            ),
            self.scheduler.EpgProgramme(
                channel_key="rtl4",
                channel_name="RTL 4",
                epg_entity="sensor.epg_rtl4",
                title="RTL Listing",
                description="",
                start="20:00",
                end="21:00",
                start_datetime=datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc),  # noqa: UP017
                end_datetime=datetime(2026, 7, 9, 21, 0, tzinfo=timezone.utc),  # noqa: UP017
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            report_file = Path(temp_dir) / "comparison.csv"
            report = self.compare.build_canalplus_comparison_report(
                open_epg_programmes,
                client,
                {"npo1": "canal-npo1", "rtl4": "bad-canal-id"},
                report_file=str(report_file),
            )
            with report_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(report.fetch_error_count, 1)
        self.assertEqual(report.secondary_count, 1)
        self.assertEqual(
            [request[0] for request in client.requests],
            ["canal-npo1", "bad-canal-id"],
        )
        self.assertEqual(report.counts["secondary_fetch_failed"], 1)
        self.assertEqual(rows[-1]["kind"], "secondary_fetch_failed")
        self.assertEqual(rows[-1]["channel"], "rtl4")
        self.assertIn("bad-canal-id", rows[-1]["note"])
        self.assertNotIn(
            "missing_in_secondary",
            [row["kind"] for row in rows if row["channel"] == "rtl4"],
        )

    def test_write_open_epg_export_file_serializes_programmes(self) -> None:
        open_epg_programmes = [
            self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="Export Me",
                description="",
                start="20:00",
                end="21:00",
                start_datetime=datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc),  # noqa: UP017
                end_datetime=datetime(2026, 7, 9, 21, 0, tzinfo=timezone.utc),  # noqa: UP017
            )
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            export_file = Path(temp_dir) / "open_epg_snapshot.json"
            rows_written = self.compare.write_open_epg_export_file(
                str(export_file),
                open_epg_programmes,
            )
            payload = json.loads(export_file.read_text(encoding="utf-8"))

        self.assertEqual(rows_written, 1)
        self.assertEqual(payload["provider"], "open_epg")
        self.assertEqual(payload["programme_count"], 1)
        self.assertEqual(payload["programmes"][0]["channel_key"], "npo1")
        self.assertEqual(payload["programmes"][0]["title"], "Export Me")

    def test_build_export_comparison_report_compares_snapshot_files(self) -> None:
        open_epg_programmes = [
            self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="Export Me",
                description="",
                start="20:00",
                end="21:00",
                start_datetime=datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc),  # noqa: UP017
                end_datetime=datetime(2026, 7, 9, 21, 0, tzinfo=timezone.utc),  # noqa: UP017
            )
        ]

        canalplus_snapshot = {
            "provider": "canalplus",
            "programmes": [
                {
                    "programme_id": "asset-1",
                    "channel_id": "npo1",
                    "title": "Export Me",
                    "description": "",
                    "start": "2026-07-09T20:00:00.000Z",
                    "end": "2026-07-09T21:00:00.000Z",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            open_epg_file = Path(temp_dir) / "open_epg_snapshot.json"
            canalplus_file = Path(temp_dir) / "canalplus_snapshot.json"
            open_epg_file.write_text(
                json.dumps(self.compare.build_open_epg_export_payload(open_epg_programmes)),
                encoding="utf-8",
            )
            canalplus_file.write_text(
                json.dumps(canalplus_snapshot),
                encoding="utf-8",
            )

            report = self.compare.build_export_comparison_report(
                str(open_epg_file),
                str(canalplus_file),
            )

        self.assertEqual(report.counts, {"confirmed": 1})
        self.assertEqual(report.primary_count, 1)
        self.assertEqual(report.secondary_count, 1)

    def test_build_canalplus_comparison_report_aligns_fetch_window(self) -> None:
        client = FakeCanalPlusClient()
        open_epg_programmes = [
            self.scheduler.EpgProgramme(
                channel_key="npo1",
                channel_name="NPO 1",
                epg_entity="sensor.epg_npo1",
                title="Offset Listing",
                description="",
                start="20:03",
                end="21:02",
                start_datetime=datetime(2026, 7, 9, 20, 3, tzinfo=timezone.utc),  # noqa: UP017
                end_datetime=datetime(2026, 7, 9, 21, 2, tzinfo=timezone.utc),  # noqa: UP017
            )
        ]

        self.compare.build_canalplus_comparison_report(
            open_epg_programmes,
            client,
            {"npo1": "canal-npo1"},
        )

        _channel_id, start_at, end_at = client.requests[0]
        self.assertEqual(start_at, datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc))  # noqa: UP017
        self.assertEqual(end_at, datetime(2026, 7, 9, 21, 15, tzinfo=timezone.utc))  # noqa: UP017

    def test_load_canalplus_channel_map_reads_ids_from_channels_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            channels_file = Path(temp_dir) / "channels.yaml"
            channels_file.write_text(
                """npo1:
  zap: "1"
  epg: sensor.epg_npo1
  canalplus_id: canal-npo1
npo2:
  zap: "2"
  epg: sensor.epg_npo2
rtl4:
  zap: "4"
  epg: sensor.epg_rtl4
  canalplus_id: canal-rtl4
""",
                encoding="utf-8",
            )

            channel_map = self.compare.load_canalplus_channel_map(str(channels_file))

        self.assertEqual(
            channel_map,
            {
                "npo1": "canal-npo1",
                "rtl4": "canal-rtl4",
            },
        )

    def test_sanitize_canalplus_authorization_removes_duplicate_bearer(self) -> None:
        sanitized = self.compare.sanitize_canalplus_authorization(
            "Bearer Bearer abc.def.ghi"
        )

        self.assertEqual(sanitized, "Bearer abc.def.ghi")

    def test_sanitize_canalplus_authorization_handles_pasted_prefixes(self) -> None:
        sanitized = self.compare.sanitize_canalplus_authorization(
            "Authorization: Bearer abc.def.ghi"
        )

        self.assertEqual(sanitized, "Bearer abc.def.ghi")


if __name__ == "__main__":
    unittest.main()
