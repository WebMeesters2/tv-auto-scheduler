from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "create_named_time_ranges_template.py"


def load_template_module():
    spec = importlib.util.spec_from_file_location(
        "create_named_time_ranges_template",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load template script from {SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CreateNamedTimeRangesTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = load_template_module()

    def test_create_named_time_ranges_template_writes_default_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "named_time_ranges.csv"

            created = self.template.create_named_time_ranges_template(str(output_file))

            with output_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertTrue(created)
        self.assertEqual(
            rows[0],
            {
                "key": "primetime",
                "filter-start-day": "",
                "filter-start-time": "20:00",
                "filter-end-time": "22:00",
            },
        )
        self.assertEqual(rows[1]["key"], "primetime_week")
        self.assertEqual(rows[2]["key"], "late_night_weekend")

    def test_create_named_time_ranges_template_does_not_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "named_time_ranges.csv"
            output_file.write_text("key,filter-start-day,filter-start-time,filter-end-time\ncustom,,,", encoding="utf-8")

            created = self.template.create_named_time_ranges_template(str(output_file))
            current_content = output_file.read_text(encoding="utf-8")

        self.assertFalse(created)
        self.assertIn("custom", current_content)


if __name__ == "__main__":
    unittest.main()
