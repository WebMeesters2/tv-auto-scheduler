# Project Notes

## Purpose

`tv_auto_scheduler` is a Home Assistant custom integration that scans Open EPG
sensor data, matches programmes against CSV rules, and creates calendar events
for pre-selection or active TV scheduling.

## Architecture

- Integration source lives in `custom_components/tv_auto_scheduler`.
- Scheduler rules are loaded from `rules.csv`; existing user rule files must not
  be overwritten.
- The scheduler reads channel metadata from `sensor.tv_channel_database` and EPG
  entries from the configured channel EPG sensors.
- Calendar events are created through Home Assistant calendar services.
- Experimental Canal+ comparison support is report-only and does not modify
  calendars.

## Documentation

- `README.md` is the primary user documentation.
- Durable technical notes and handover material live in `docs/`.
- Examples users can adapt live in `examples/`.
- Keep examples synchronized with the implementation and service schemas.

## Development Workflow

- Prefer Bash and WSL-native tools for this repository.
- Use the repository deployment script at `scripts/deploy.sh`.
- Do not assume deployment paths, credentials, hostnames, or environment details
  beyond the documented Home Assistant target `jeeves`.
- Keep behavior configurable where it is useful, but avoid adding configuration
  for one-off implementation details.

## Validation

- Run `python -m compileall .` for Python changes.
- Run focused tests for touched scheduler, migration, comparison, or script
  behavior.
- Run `bash -n scripts/deploy.sh` when deployment logic changes.
- Review `git status` and `git diff` before committing.

## Release Process

- Version source: `custom_components/tv_auto_scheduler/manifest.json`.
- Release notes location: `RELEASE_NOTES.md`; `.github/RELEASE_NOTES_TEMPLATE.md` for the template.
- Tagging/deployment steps: keep manifest version, release notes, HACS metadata, and Git tags synchronized.

## Local Rules

- Existing user `rules.csv` files must not be overwritten.
- Experimental Canal+ comparison support stays report-only unless explicitly changed.
- Repository deployment scripts are authoritative for local deployment.

## Open Questions

- Which Canal+ comparison features should graduate from report-only to active scheduling behavior.
- Whether additional validation should be added for rule-file migration behavior.
