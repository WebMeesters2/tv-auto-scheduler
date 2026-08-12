# TV Auto Scheduler

Automatically schedule TV programmes from EPG data into Home Assistant calendars.

This custom integration scans a channel database sensor, reads EPG entity data for each channel, matches broadcasts against regex-based CSV rules, and creates calendar events for the matches you want to keep track of.

## What This Integration Expects

`tv_auto_scheduler` does not fetch guide data itself. It depends on an existing entity:

```text
sensor.tv_channel_database
```

That entity must expose a `channels` attribute shaped roughly like this:

```yaml
channels:
  bbc1:
    aliases:
      - BBC1
    epg: sensor.epg_bbc1
  npo1:
    aliases:
      - NPO 1
    epg: sensor.epg_npo1
```

Each referenced EPG entity must then expose `today` and/or `tomorrow` mappings with programme entries that include at least:

```yaml
today:
  "0":
    title: Bargain Hunt
    start: "14:00"
    end: "15:00"
  "1":
    title: Return to Paradise
    start: "21:15"
    end: "22:10"
```

If that source data is missing or shaped differently, the scan will not find any programmes to schedule.

## Features

- Regex matching for both channel and programme rules
- Support for separate pre-selection and active TV calendars
- Duplicate protection for events created by this integration
- Dry-run mode for safe testing
- Optional logging of missing EPG entities
- Simple CSV-based rule configuration

## Installation

Copy:

```text
custom_components/tv_auto_scheduler
```

to:

```text
/config/custom_components/tv_auto_scheduler
```

Restart Home Assistant.

Add to `configuration.yaml`:

```yaml
tv_auto_scheduler:
```

Restart Home Assistant again.

## Rule File

Default location:

```text
/config/tv_auto_scheduler/rules.csv
```

If new rule columns are introduced in a future release, use the migration utility instead of editing larger files by hand:

```bash
python /config/tv_auto_scheduler/migrate_rules_csv.py /config/tv_auto_scheduler/rules.csv
```

The deployment scripts copy this utility to `/config/tv_auto_scheduler/migrate_rules_csv.py`. It inserts any missing known columns with safe defaults, preserves existing row values, keeps unknown extra columns, and writes a backup next to the original file as `rules.csv.bak`.

To validate the current file without changing it:

```bash
python /config/tv_auto_scheduler/migrate_rules_csv.py --validate /config/tv_auto_scheduler/rules.csv
```

Validation checks the current header against the expected rule columns and flags obvious CSV structure problems such as extra values beyond the header on a row.

Example:

```csv
rule-id,enabled,channel,programme,pre,tv,flag-delete-after-use,named-time-range,filter-start-day,filter-start-time,filter-end-time
1,y,NPO.*,The Connection,y,y,n
2,y,BBC.*,Bargain Hunt,n,y,n,,mon|wed
3,y,BBC.*,Celebrity Bridge of Lies,n,y,y,,fri,20:00,23:30
,y,RTL4,Het Perfecte Plaatje,y,y,n,primetime
```

### Columns

| Column | Description |
| --- | --- |
| `rule-id` | Stable scheduler-managed identifier for the rule. Leave it empty for new rows and the scheduler will assign the next available number |
| `enabled` | Enable or disable the rule (`y` / `n`) |
| `channel` | Case-insensitive regular expression matched against the channel key |
| `programme` | Case-insensitive regular expression matched against the programme title |
| `pre` | Add matching broadcasts to the pre-selection calendar |
| `tv` | Add matching broadcasts to the active TV calendar |
| `flag-delete-after-use` | Remove the rule from `rules.csv` after it creates at least one event (`y` / `n`, defaults to `n` when left empty) |
| `named-time-range` | Optional key that points to a named range in `named_time_ranges.csv` |
| `filter-start-day` | Optional weekday filter for the programme start date. Accepts one or more day names or day ranges |
| `filter-start-time` | Optional lower bound for the programme start time in `HH:MM` |
| `filter-end-time` | Optional upper bound for the programme start time in `HH:MM` |

These CSV header names are fixed and must match exactly. For example, use `rule-id`, `named-time-range`, `flag-delete-after-use`, `filter-start-day`, `filter-start-time`, and `filter-end-time` as written here, not shortened alternatives.

`rule-id` is the stable identifier that gets written into the change log. This means you can reorder rows in `rules.csv` without breaking the historical link between a change-log row and the rule that created it. The field is optional when the user edits the file, but the scheduler will automatically backfill missing or invalid IDs the next time it runs.

If you add a brand-new rule manually, both of these forms are accepted:

```csv
,y,RTL4,Het Perfecte Plaatje,y,y,n,primetime
y,RTL4,Het Perfecte Plaatje,y,y,n,primetime
```

The second form is treated as if the missing leading comma had been supplied, so the scheduler will still interpret `y` as `enabled` and assign a new `rule-id` automatically.

The five trailing optional fields do not need placeholder commas at the end of the line. In other words, keep only the commas needed to reach the last field you actually use. This is valid, for example:

```csv
71,y,BBC[1-2],Impossible,y,y,,afternoon
```

You can also add comments after a rule by placing `#` after the last CSV value you care about. Everything after that `#` is ignored while reading the file:

```csv
71,y,BBC[1-2],Impossible,y,y,,afternoon # weekday afternoon catch-up
```

If the scheduler or migration utility later normalizes the file, that inline rule comment is preserved on the same row.

If you use a time filter, set both `filter-start-time` and `filter-end-time`. The filter is applied to the programme start time. Windows that cross midnight are supported, so `23:00` to `02:00` will match late-night and after-midnight starts.

`filter-start-day` is also applied to the programme start. You can use English or Dutch weekday names, short or long, for example `mon`, `wednesday`, `vr`, or `zondag`. To match multiple start days in one rule, separate them with `|`, `,`, `;`, or `/`, for example `mon|wed|fri`. Day ranges are also supported, for example `mon-fri`, `sat-sun`, `ma-vr`, or wrap-around ranges such as `fri-mon`.

## Named Time Ranges

You can store reusable time windows in a sibling file next to `rules.csv`:

```text
/config/tv_auto_scheduler/named_time_ranges.csv
```

Example:

```csv
key,filter-start-day,filter-start-time,filter-end-time
primetime,,20:00,22:00
primetime_week,mon-fri,20:00,22:00
late_night_weekend,sat-sun,22:30,01:30
```

You can also generate a starter file automatically:

```bash
python /config/tv_auto_scheduler/create_named_time_ranges_template.py --rules-file /config/tv_auto_scheduler/rules.csv
```

If the file already exists, the helper leaves it untouched unless you add `--overwrite`.

Then a rule can reference one of those keys:

```csv
,y,RTL4,Het Perfecte Plaatje,y,y,n,primetime
```

If a rule uses `named-time-range`, the named values are used as defaults for `filter-start-day`, `filter-start-time`, and `filter-end-time`. Any explicit filter values on the rule itself override the named range value for that column.

If a field contains a comma, wrap it in double quotes as standard CSV. For example:

```csv
,y,BBC.*,"Law & Order, Special Victims Unit",n,y,n
```

If a field contains a double quote character, escape it by doubling it:

```csv
,y,BBC.*,"The ""Best Of"" Show",n,y,n
```

Example channel rules:

- `BBC.*`
- `NPO[123]`
- `BBC1|BBC2`

## Calendar Targets

Defaults:

| Purpose | Calendar |
| --- | --- |
| Pre-selection | `calendar.pre_tv` |
| Active TV schedule | `calendar.televisie` |

These can be overridden on each service call.

The target calendars must support both:

- `calendar.get_events`
- `calendar.create_event`

## Service

Service name:

```yaml
action: tv_auto_scheduler.scan
```

Dry-run example:

```yaml
action: tv_auto_scheduler.scan
data:
  dry_run: true
  dry_run_log: true
  dry_run_log_file: /config/tv_auto_scheduler/tv_auto_scheduler_dry_run.csv
```

Real run example:

```yaml
action: tv_auto_scheduler.scan
data:
  dry_run: false
```

Full example:

```yaml
action: tv_auto_scheduler.scan
data:
  rules_file: /config/tv_auto_scheduler/rules.csv
  dry_run: false
  pre_calendar: calendar.pre_tv
  tv_calendar: calendar.televisie
  show_missing_epg: false
  change_log: true
  change_log_file: /config/tv_auto_scheduler/tv_auto_scheduler_changes.csv
```

## Suggested Automation

Run the scan on a schedule so new guide data gets processed automatically:

```yaml
automation:
  - alias: TV Auto Scheduler Scan
    triggers:
      - trigger: time_pattern
        minutes: "/30"
    actions:
      - action: tv_auto_scheduler.scan
        data:
          dry_run: false
          change_log: true
          change_log_file: /config/tv_auto_scheduler/tv_auto_scheduler_changes.csv
```

You may want to start with `dry_run: true` until the rule file behaves the way you expect.

## Duplicate Protection

Created events are tagged in the event description using an internal marker. The description also includes the matching rule, the source EPG entity, and the EPG programme description when one is available. When the integration finds an existing event with the same summary and time range that it previously created, it skips creating a duplicate.

## Change Log

Set `change_log: true` on the `tv_auto_scheduler.scan` service call to append each created calendar event to a CSV file. If you do not provide `change_log_file`, the integration stores the log next to `rules.csv`. With the default rules path, the file will be written to:

```text
/config/tv_auto_scheduler/tv_auto_scheduler_changes.csv
```

The file is Excel-friendly and includes these columns:

```text
type,run_at,start_at,end_at,timezone,calendar,channel,channel_name,programme,rule,rule_id,source_epg,programme_description
```

Each row represents one actual calendar change. If a match creates both a pre-selection and an active TV event, the CSV gets two `Add` rows, one per calendar target. If you want the log somewhere else, set `change_log_file` to an explicit CSV path on the service call.

## Dry-Run Log

Set `dry_run: true` together with `dry_run_log: true` if you want a separate CSV that shows what the scheduler would change without touching any calendars.

If you do not provide `dry_run_log_file`, the default file is:

```text
/config/tv_auto_scheduler/tv_auto_scheduler_dry_run.csv
```

The dry-run log uses the same CSV structure as the normal change log, but the `type` column contains values such as `WouldAdd` and `WouldDelete`.

## Repository Hygiene

This repo includes:

- `hacs.json` for HACS metadata
- `pyproject.toml` with lightweight `ruff` and `mypy` config
- `LICENSE` for the MIT license declared by the project

## Current Status

Implemented:

- CSV rule loading
- EPG scanning
- Regex-based channel matching
- Regex-based programme matching
- Optional delete-after-use rules
- Optional start-day filtering
- Optional start-time filtering
- Calendar event creation
- Duplicate detection
- Dry-run mode
- Optional CSV change log for created events

Planned:

- Configuration flow
- Rule priorities
- Repeat filtering
- Calendar cleanup and update logic

## Disclaimer

This is an unofficial custom integration and is not affiliated with Home Assistant.

## License

MIT


## Experimental Canal+ Comparison

Open EPG remains the primary scheduling source. The experimental Canal+ comparison service fetches Canal+ schedule data for mapped channels and writes a report of differences. It does not create, delete, or modify calendar events.

The service currently requires a fresh Authorization header copied from an authenticated Canal+ browser request. Canal+ tokens are short-lived, so this is intended for investigation and validation rather than unattended automation.

Example:

    action: tv_auto_scheduler.compare_canalplus
    data:
      canalplus_authorization: !secret canalplus_authorization
      channels_file: /config/tv/channels.yaml
      comparison_report_file: /config/tv_auto_scheduler/canalplus_comparison.csv
      only_scheduled_programmes: true
      pre_calendar: calendar.pre_tv
      tv_calendar: calendar.televisie
      show_matching_programmes: false

The `channels_file` should contain the normal channel entries with a `canalplus_id` value for every channel that should be compared. You can still pass `canalplus_channels` directly on the service call to override or add individual mappings.

Useful comparison toggles:

- `only_scheduled_programmes`: when enabled, the integration first checks `pre_calendar` and `tv_calendar` and compares only Open EPG programmes that already exist there as scheduler-created events.
- With `only_scheduled_programmes: true`, secondary-only Canal+ rows (`missing_in_primary`) are excluded so the report stays focused on scheduled Open EPG items.
- `show_matching_programmes`: when disabled, `confirmed` rows are excluded so the report focuses on differences and fetch failures.

For the Canal+ PoC script, there is also a browser-session mode that keeps the login local to a persistent Playwright profile and makes the API calls from that session instead of asking you to copy a bearer token by hand:

  python scripts/canalplus_poc.py browser-normalized-epg 2026-07-09T00:00:00+00:00 2026-07-10T00:00:00+00:00

The first run opens Canal+ in a browser window, waits for you to finish login, and then reuses that local profile on later runs. Install Playwright first if you want to use this mode:

  pip install playwright
  playwright install chromium

If you prefer to isolate the browser dependencies, there is also an add-on scaffold in `addons/canalplus-browser` and a wrapper script at `scripts/run_canalplus_browser_container.sh`. That keeps Playwright and Chromium out of the HAOS host and runs the browser-backed helper in its own container.

That helper is only for the Canal+ side of the workflow. It does not see Home Assistant Open EPG entities on its own, so if you want to compare Canal+ against the Open EPG sensors that live in HA, run the `tv_auto_scheduler.compare_canalplus` service in Home Assistant itself.

HAOS install procedure for the add-on scaffold:

1. Expose the Home Assistant `/addons` share, for example with the Samba app or Studio Code Server.
2. Copy `addons/canalplus-browser` into `/addons/canalplus-browser` on the HAOS host.
3. Open Home Assistant and go to **Settings > Add-ons**.
4. Reload the add-on list if needed, then open the local add-on for Canal+ Browser Helper.
5. Install and start it.

The add-on is an idle runtime base rather than a finished interactive app, so the practical way to use it today is still the browser-session helper command itself. The add-on just keeps the Playwright/Chromium runtime packaged separately from HAOS.

If you need WSL or another external tool to participate in the workflow, use the new HA service `tv_auto_scheduler.export_open_epg` to write the current Open EPG snapshot to `/config/tv_auto_scheduler/open_epg_snapshot.json`, then consume that file from the external tool. That is the bridge that keeps HA as the source of truth for the Open EPG data.

To compare outside HA, the current helper is:

  python scripts/compare_open_epg_canalplus_exports.py /config/tv_auto_scheduler/open_epg_snapshot.json /path/to/canalplus_snapshot.json --report-file /path/to/comparison.csv

Add `--hide-matching-programmes` if you only want differences in that external report.

The Canal+ snapshot is the JSON output from `scripts/canalplus_poc.py browser-normalized-epg`.

The CSV report contains one row per comparison with the classification, channel, Open EPG title/time, Canal+ title/time, and start/end deltas. Current classifications include confirmed, missing_in_primary, missing_in_secondary, time_mismatch, duration_mismatch, title_mismatch, and replaced.

Each row also includes run-level metadata columns:

- `comparison_window_start`: earliest Open EPG start timestamp that was part of the compared input set.
- `comparison_window_end`: latest Open EPG end timestamp that was part of the compared input set.
- `suppressed_secondary_only_count`: number of secondary-only (`missing_in_primary`) rows suppressed for the run (for example when `only_scheduled_programmes: true`).

For the scheduler change log (`tv_auto_scheduler_changes.csv`):

- Rows are appended only when the scheduler adds or replaces events.
- If all matched programmes are already present in the target calendars, the run can succeed with zero new change-log rows.
- If writing the change-log file fails, the scheduler now logs an explicit warning after the run summary so the issue is visible in `home-assistant.log`.

The example Home Assistant script in `examples/canalplus_compare_script.yaml` accepts a fresh bearer token, writes a dated report file such as `YYMMDD_HHMM_canalplus_comparison.csv`, and calls this service from Home Assistant. The Home Assistant script trace only shows the service call itself; the Python comparison details are written to `home-assistant.log`. For extra detail during investigation, temporarily enable debug logging:

    logger:
      logs:
        custom_components.tv_auto_scheduler: debug

If the Canal+ comparison fails before the CSV report is written, the service raises an error so the script trace shows the failure instead of looking like a successful no-op.
