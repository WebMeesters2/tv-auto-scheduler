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

Example:

```csv
enabled,channel,programme,pre,tv,flag-delete-after-use,filter-start-time,filter-end-time
y,NPO.*,The Connection,y,y,n,,
y,BBC.*,Bargain Hunt,n,y,n,,
y,BBC.*,Celebrity Bridge of Lies,n,y,y,20:00,23:30
y,BBC.*,Return to Paradise,n,y,n,,
```

### Columns

| Column | Description |
| --- | --- |
| `enabled` | Enable or disable the rule (`y` / `n`) |
| `channel` | Case-insensitive regular expression matched against the channel key |
| `programme` | Case-insensitive regular expression matched against the programme title |
| `pre` | Add matching broadcasts to the pre-selection calendar |
| `tv` | Add matching broadcasts to the active TV calendar |
| `flag-delete-after-use` | Remove the rule from `rules.csv` after it creates at least one event (`y` / `n`, defaults to `n` when left empty) |
| `filter-start-time` | Optional lower bound for the programme start time in `HH:MM` |
| `filter-end-time` | Optional upper bound for the programme start time in `HH:MM` |

These CSV header names are fixed and must match exactly. For example, use `flag-delete-after-use`, `filter-start-time`, and `filter-end-time` as written here, not shortened alternatives such as `delete-after-use`, `start`, or `end`.

If you use a time filter, set both `filter-start-time` and `filter-end-time`. The filter is applied to the programme start time. Windows that cross midnight are supported, so `23:00` to `02:00` will match late-night and after-midnight starts.

If a field contains a comma, wrap it in double quotes as standard CSV. For example:

```csv
y,BBC.*,"Law & Order, Special Victims Unit",n,y,n,,
```

If a field contains a double quote character, escape it by doubling it:

```csv
y,BBC.*,"The ""Best Of"" Show",n,y,n,,
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
```

You may want to start with `dry_run: true` until the rule file behaves the way you expect.

## Duplicate Protection

Created events are tagged in the event description using an internal marker. When the integration finds an existing event with the same summary and time range that it previously created, it skips creating a duplicate.

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
- Optional start-time filtering
- Calendar event creation
- Duplicate detection
- Dry-run mode

Planned:

- Configuration flow
- Rule priorities
- Repeat filtering
- Calendar cleanup and update logic

## Disclaimer

This is an unofficial custom integration and is not affiliated with Home Assistant.

## License

MIT
