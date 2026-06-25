from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "migrate_rules_csv.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location("migrate_rules_csv", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load migration script from {SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migration = load_migration_module()

    def test_migrate_rules_file_adds_missing_columns_and_backup(self) -> None:
        csv_content = "\n".join(
            [
                "enabled,channel,programme,pre,tv,custom",
                "y,BBC.*,Bargain Hunt,n,y,keep-me",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed, backup_path = self.migration.migrate_rules_file(str(rules_file))

            with rules_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

            backup_content = backup_path.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertIsNotNone(backup_path)
        self.assertEqual(
            rows[0],
            {
                "rule-id": "1",
                "enabled": "y",
                "channel": "BBC.*",
                "programme": "Bargain Hunt",
                "pre": "n",
                "tv": "y",
                "flag-delete-after-use": "n",
                "named-time-range": "",
                "filter-start-day": "",
                "filter-start-time": "",
                "filter-end-time": "",
                "custom": "keep-me",
            },
        )
        self.assertIn("enabled,channel,programme,pre,tv,custom", backup_content)

    def test_migrate_rules_file_dry_run_does_not_rewrite(self) -> None:
        csv_content = "\n".join(
            [
                "enabled,channel,programme,pre,tv",
                "y,BBC.*,Bargain Hunt,n,y",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed, backup_path = self.migration.migrate_rules_file(
                str(rules_file),
                dry_run=True,
            )
            current_content = rules_file.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertIsNone(backup_path)
        self.assertEqual(current_content, csv_content)

    def test_validate_rules_file_reports_missing_columns(self) -> None:
        csv_content = "\n".join(
            [
                "enabled,channel,programme,pre,tv",
                "y,BBC.*,Bargain Hunt,n,y",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            issues = self.migration.validate_rules_file(str(rules_file))

        self.assertEqual(
            issues,
            [
                "Missing columns: rule-id, flag-delete-after-use, named-time-range, filter-start-day, filter-start-time, filter-end-time"
            ],
        )

    def test_migrate_rules_file_preserves_existing_rule_ids_and_assigns_missing_ones(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv",
                "5,y,BBC.*,Bargain Hunt,n,y",
                ",y,NPO.*,The Connection,y,y",
                "11,y,RTL4,Het Perfecte Plaatje,y,y",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed, _ = self.migration.migrate_rules_file(str(rules_file))

            with rules_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertTrue(changed)
        self.assertEqual([row["rule-id"] for row in rows], ["5", "12", "11"])

    def test_migrate_rules_file_repairs_shifted_rows_without_leading_rule_id_comma(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "y,RTL4,Het Perfecte Plaatje,y,y,n,primetime",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed, _ = self.migration.migrate_rules_file(str(rules_file))

            with rules_file.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertTrue(changed)
        self.assertEqual(rows[0]["rule-id"], "1")
        self.assertEqual(rows[0]["enabled"], "y")
        self.assertEqual(rows[0]["channel"], "RTL4")
        self.assertEqual(rows[0]["programme"], "Het Perfecte Plaatje")
        self.assertEqual(rows[0]["named-time-range"], "primetime")

    def test_migrate_rules_file_ignores_inline_comments_and_writes_compact_rows(self) -> None:
        csv_content = "\n".join(
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "y,BBC[1-2],Impossible,y,y,,afternoon # readable comment",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            changed, _ = self.migration.migrate_rules_file(str(rules_file))
            updated = rules_file.read_text(encoding="utf-8").splitlines()

        self.assertTrue(changed)
        self.assertEqual(
            updated,
            [
                "rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time",
                "1,y,BBC[1-2],Impossible,y,y,,afternoon",
            ],
        )

    def test_validate_rules_file_reports_extra_row_values(self) -> None:
        csv_content = "\n".join(
            [
                "enabled,channel,programme",
                "y,BBC.*,Bargain Hunt,unexpected",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            rules_file = Path(temp_dir) / "rules.csv"
            rules_file.write_text(csv_content, encoding="utf-8")

            issues = self.migration.validate_rules_file(str(rules_file))

        self.assertIn(
            "Row 2 has extra values beyond the header: unexpected",
            issues,
        )


if __name__ == "__main__":
    unittest.main()
