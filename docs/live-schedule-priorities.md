# Live Schedule Priorities

## Purpose

Rules can optionally prioritize programmes when matched events overlap in the active
TV calendar. Priority planning does not affect the pre-selection calendar.

## Rule Contract

The `priority` column in `rules.csv` accepts:

- `high`: preserve the programme's original EPG start and end times.
- `low`: let an overlapping programme take precedence.
- blank: preserve the legacy behavior unless the programme conflicts with an
  explicitly prioritized programme.

Values are case-insensitive. Unsupported values are logged and treated as blank.
The effective order is `high > blank > low`.

## Planning Behavior

1. Match EPG programmes using the existing channel, title, day, and time filters.
2. Build a separate plan for matches targeting the active TV calendar.
3. Sort candidates by original start, end, and stable rule ID.
4. For overlapping candidates, trim the lower-priority programme:
   - A later losing programme starts one minute after the winner ends.
   - An earlier losing programme ends one minute before the winner starts.
5. Omit a programme if trimming leaves no positive duration.
6. Keep equal unprioritized and equal high-priority overlaps unchanged. Equal low
   priorities use chronological order as the stable tie-break.
7. Use adjusted times for duplicate detection, replacement, dry runs, change logs,
   and calendar creation.

Only matched programmes in the current scan participate. Manual or unrelated
calendar events are not changed. When more than one rule matches the same broadcast,
the strongest TV priority is used for that broadcast.

## Implementation Areas

- `custom_components/tv_auto_scheduler/const.py`: CSV field name.
- `custom_components/tv_auto_scheduler/scheduler.py`: rule parsing and pure TV plan.
- `custom_components/tv_auto_scheduler/__init__.py`: apply planned times to live
  calendar operations while retaining original times for pre-selection.
- `scripts/migrate_rules_csv.py`: safe schema migration for existing rule files.
- `tests/`: parsing, migration, precedence, trimming, and compatibility coverage.

## Verification

- Run focused scheduler and migration tests.
- Run the complete test suite.
- Run `python -m compileall .`.
- Review `git status` and `git diff`.
