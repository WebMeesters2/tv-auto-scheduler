# TV Auto Scheduler

Automatically schedule TV programmes from EPG data into Home Assistant calendars.

TV Auto Scheduler scans one or more EPG sources, matches programmes against a simple rule file, and automatically creates calendar events for matching broadcasts.

The goal is to maintain a personal TV watchlist without manually adding recurring programmes every week.

---

## Features

- Scan Home Assistant EPG entities
- Match programmes using channel and programme patterns
- Schedule matching programmes automatically
- Support multiple target calendars
- Prevent duplicate calendar entries
- Dry-run mode for safe testing
- Simple CSV-based rule configuration

---

## How it works

1. TV Auto Scheduler reads a CSV rule file.
2. It scans the configured EPG sensors.
3. Matching broadcasts are identified.
4. Calendar events are created automatically.
5. Existing auto-created events are detected and skipped.

Example:

Rule:

| Channel | Programme    |
| ------- | ------------ |
| BBC.\*  | Bargain Hunt |

Matching EPG entry:

```text
BBC1 | Bargain Hunt • Wetherby 10 and 11
```

Result:

A calendar event is automatically created.

---

## Rule file

Location:

```text
/config/tv_auto_scheduler/rules.csv
```

Example:

```csv
enabled,channel,programme,pre,tv
y,NPO.*,The Connection,y,y
y,BBC.*,Bargain Hunt,n,y
y,BBC.*,Celebrity Bridge of Lies,n,y
y,BBC.*,Return to Paradise,n,y
```

### Columns

| Column    | Description                               |
| --------- | ----------------------------------------- |
| enabled   | Enable or disable the rule (`y` / `n`)    |
| channel   | Regular expression used to match channels |
| programme | Programme title to search for             |
| pre       | Add to the pre-selection calendar         |
| tv        | Add to the active TV calendar             |

---

## Calendar targets

By default:

| Purpose            | Calendar             |
| ------------------ | -------------------- |
| Pre-selection      | `calendar.pre_tv`    |
| Active TV schedule | `calendar.televisie` |

These can be overridden when calling the scan service.

---

## Service

### Scan rules

```yaml
action: tv_auto_scheduler.scan
data:
  dry_run: true
```

### Real run

```yaml
action: tv_auto_scheduler.scan
data:
  dry_run: false
```

---

## Duplicate protection

TV Auto Scheduler marks created events using metadata stored in the event description.

When a matching event already exists, it will be skipped automatically.

This allows the scheduler to run repeatedly without creating duplicate calendar entries.

---

## Installation

### Manual installation

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

---

## Current status

Implemented:

- CSV rule loading
- EPG scanning
- Channel matching
- Programme matching
- Calendar event creation
- Duplicate detection
- Dry-run mode

Planned:

- Automatic scheduled scanning
- Rule priorities
- Repeat filtering
- Configuration Flow
- HACS support
- Calendar cleanup and update logic

---

## Disclaimer

This is an unofficial custom integration and is not affiliated with Home Assistant.

Use at your own risk.

---

## License

MIT License
