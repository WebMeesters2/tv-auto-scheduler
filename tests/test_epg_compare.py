from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "custom_components" / "tv_auto_scheduler" / "epg_compare.py"


def load_compare_module():
    spec = importlib.util.spec_from_file_location("epg_compare", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load EPG compare module from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["epg_compare"] = module
    spec.loader.exec_module(module)
    return module


class EpgCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compare = load_compare_module()

    def test_compare_guides_confirms_matching_programmes(self) -> None:
        primary = [
            self._programme("open_epg", "npo1", "NOS Journaal", "20:00", "20:30")
        ]
        secondary = [
            self._programme("canalplus", "npo1", "NOS Journaal", "20:05", "20:30")
        ]

        comparisons = self.compare.compare_guides(primary, secondary)

        self.assertEqual(len(comparisons), 1)
        self.assertEqual(comparisons[0].kind, self.compare.CONFIRMED)
        self.assertEqual(comparisons[0].start_delta_minutes, 5)

    def test_compare_guides_detects_time_mismatch(self) -> None:
        primary = [
            self._programme("open_epg", "npo1", "Evening Show", "20:00", "21:00")
        ]
        secondary = [
            self._programme("canalplus", "npo1", "Evening Show", "20:25", "21:25")
        ]

        comparisons = self.compare.compare_guides(primary, secondary)

        self.assertEqual(comparisons[0].kind, self.compare.TIME_MISMATCH)
        self.assertEqual(comparisons[0].start_delta_minutes, 25)

    def test_compare_guides_detects_duration_mismatch(self) -> None:
        primary = [
            self._programme("open_epg", "npo1", "NOS WK Avond", "21:25", "21:50")
        ]
        secondary = [
            self._programme(
                "canalplus",
                "npo1",
                "NOS WK Avond (NOS)",
                "21:05",
                "21:50",
            )
        ]

        comparisons = self.compare.compare_guides(primary, secondary)

        self.assertEqual(comparisons[0].kind, self.compare.DURATION_MISMATCH)
        self.assertEqual(comparisons[0].start_delta_minutes, -20)

    def test_compare_guides_detects_title_mismatch_in_same_slot(self) -> None:
        primary = [
            self._programme("open_epg", "npo1", "Old Listing", "20:00", "21:00")
        ]
        secondary = [
            self._programme("canalplus", "npo1", "Current Listing", "20:00", "21:00")
        ]

        comparisons = self.compare.compare_guides(primary, secondary)

        self.assertEqual(comparisons[0].kind, self.compare.REPLACED)

    def test_titles_ignore_broadcaster_suffixes_and_clock_labels(self) -> None:
        primary = [
            self._programme(
                "open_epg",
                "npo1",
                "NOS Journaal 20.00 uur",
                "20:00",
                "20:35",
            )
        ]
        secondary = [
            self._programme(
                "canalplus",
                "npo1",
                "NOS Journaal (NOS)",
                "20:00",
                "20:35",
            )
        ]

        comparisons = self.compare.compare_guides(primary, secondary)

        self.assertEqual(comparisons[0].kind, self.compare.CONFIRMED)

    def test_compare_guides_reports_missing_programmes_on_both_sides(self) -> None:
        primary = [
            self._programme("open_epg", "npo1", "Only Open EPG", "18:00", "19:00")
        ]
        secondary = [
            self._programme("canalplus", "npo1", "Only Canal+", "21:00", "22:00")
        ]

        comparisons = self.compare.compare_guides(primary, secondary)

        self.assertEqual(
            [comparison.kind for comparison in comparisons],
            [
                self.compare.MISSING_IN_SECONDARY,
                self.compare.MISSING_IN_PRIMARY,
            ],
        )

    def test_canalplus_rows_parse_utc_timestamps(self) -> None:
        row = {
            "programme_id": "asset-1",
            "channel_id": "canal-npo1",
            "title": "NOS Journaal",
            "description": "News.",
            "start": "2026-07-09T18:00:00.000Z",
            "end": "2026-07-09T18:30:00.000Z",
        }

        programme = self.compare.guide_programme_from_canalplus_row(
            row,
            channel_key="npo1",
        )

        self.assertEqual(programme.channel_key, "npo1")
        self.assertEqual(programme.source, "canalplus")
        self.assertEqual(programme.provider_id, "asset-1")
        self.assertEqual(programme.start_datetime.tzinfo, timezone.utc)  # noqa: UP017

    def _programme(
        self,
        source: str,
        channel_key: str,
        title: str,
        start: str,
        end: str,
    ):
        return self.compare.GuideProgramme(
            source=source,
            channel_key=channel_key,
            title=title,
            start_datetime=self._datetime(start),
            end_datetime=self._datetime(end),
        )

    @staticmethod
    def _datetime(value: str) -> datetime:
        hour, minute = value.split(":")
        return datetime(
            2026,
            7,
            9,
            int(hour),
            int(minute),
            tzinfo=timezone.utc,  # noqa: UP017
        )


if __name__ == "__main__":
    unittest.main()
