# Release v1.2.2

This documentation release plans the native Windows-to-Home Assistant MQTT
bridge for launching Canal+ comparisons with a clipboard bearer token.

## :boom: Breaking changes

* None.

## :memo: Documentation

* Added a Canal+ MQTT clipboard bridge implementation plan covering the TV
  Channel Display Windows app, MQTT payload contract, Home Assistant receiver
  automation, security notes, and validation steps.
* Added a Home Assistant MQTT receiver automation example for the TV Channel Display compare request topic.
* Updated the Canal+ comparison script example to write dated report filenames.
* Clarified that the MQTT receiver delegates only to script.compare_canalplus_epg.

## :white_check_mark: Validation

* Documentation-only change; checked filenames and examples during edit.

## Upgrade notes

No manual migration is required.

# Release v1.2.1

This maintenance release keeps local dated test captures out of version control.

## :boom: Breaking changes

* None.

## :wrench: Maintenance

* Ignored the local `tests/20260810/` test-data capture directory.

## :white_check_mark: Validation

* Verified `tests/20260810/` is ignored by Git.
* `.venv/bin/python -m compileall .`

## Upgrade notes

No manual migration is required.

# Release v1.2.0

This release adds comparison filters so Canal+ reports can focus on scheduled calendar programmes and optional differences-only output.

## :boom: Breaking changes

* None.

## :sparkles: Added

* Added `only_scheduled_programmes` to `tv_auto_scheduler.compare_canalplus` to restrict Open EPG comparison input to scheduler-created events already present in `pre_calendar` or `tv_calendar`.
* Added `show_matching_programmes` to `tv_auto_scheduler.compare_canalplus` to include or exclude `confirmed` rows.
* Added `--hide-matching-programmes` to `scripts/compare_open_epg_canalplus_exports.py` for differences-only external reports.

## :arrows_counterclockwise: Changed

* Extended `tv_auto_scheduler.compare_canalplus` with optional `pre_calendar` and `tv_calendar` parameters for scheduled-only filtering.
* Added `comparison_window_start`, `comparison_window_end`, and `suppressed_secondary_only_count` columns to Canal+ comparison CSV rows.

## :bug: Fixed

* Fixed `only_scheduled_programmes` output to suppress secondary-only rows (`missing_in_primary`) so unrelated Canal+ guide items do not appear in scheduled-only reports.
* Fixed deployment failures on CIFS mounts by synchronizing the integration directory in place instead of deleting and immediately recreating it.

## :memo: Documentation

* Updated README and service schema docs with the new Canal+ comparison filtering options.
* Documented comparison CSV metadata columns for window timestamps and suppressed secondary-only counts.

## :wrench: Maintenance

* Added tests for hiding confirmed matches and filtering Open EPG exports by scheduled calendar slots.
* Excluded and cleaned Python bytecode and cache directories from integration deployments.

## :white_check_mark: Validation

* `.venv/bin/python -m unittest tests.test_canalplus_compare`
* `.venv/bin/python -m compileall .`
* `bash -n scripts/deploy.sh`
* Isolated deployment sync verified stale-file deletion and Python cache cleanup.

## Upgrade notes

No manual migration is required.

# Release v1.1.2

This release adds a file-based Open EPG bridge and an external comparison script so the Canal+ workflow can be run outside Home Assistant when needed.

## :boom: Breaking changes

* None.

## :sparkles: Added

* Added `tv_auto_scheduler.export_open_epg` to write the current Open EPG snapshot to JSON.
* Added `scripts/compare_open_epg_canalplus_exports.py` to compare exported Open EPG and Canal+ snapshot files.
* Added a `browser-normalized-epg` Canal+ PoC mode that uses a local Playwright browser session.
* Added a dedicated Canal+ browser helper add-on scaffold under `addons/canalplus-browser`.
* Added a wrapper script for building and running the browser helper container locally.
* Added HAOS install guidance for the browser helper scaffold.

## :arrows_counterclockwise: Changed

* Updated the Canal+ PoC docs to describe both token-based and browser-session flows.
* Updated the Canal+ handover notes to reflect the containerized browser runtime.

## :bug: Fixed

* Fixed change-log appends for legacy/malformed headers (for example `F4type` instead of `type`) to prevent dropped Add/Delete rows.

## :memo: Documentation

* Documented the browser-session helper usage in README and handover notes.
* Documented the Open EPG export bridge and the external comparison helper.

## :wrench: Maintenance

* Added tests for the Open EPG snapshot export helper and file-based comparison bridge.
* Added tests for the browser-session Canal+ PoC client path.

## :white_check_mark: Validation

* `.venv/bin/python -m unittest tests.test_canalplus_compare tests.test_canalplus_poc`
* `.venv/bin/python -m compileall custom_components tests scripts`
* `bash -n scripts/run_canalplus_browser_container.sh`
* `.venv/bin/python -m unittest tests.test_canalplus_poc`

## Upgrade notes

The HAOS add-on scaffold is a runtime base, not a complete interactive add-on. To use it on HAOS, copy the add-on folder into `/addons`, then install and start the local add-on from the Home Assistant UI.

# Release v1.1.0

This release improves the experimental Canal+ comparison workflow by loading channel IDs from a shared channels file, producing clearer partial reports when Canal+ fetches fail, and adding deployment-ready examples and documentation.

## :boom: Breaking changes

* None.

## :sparkles: Added

* Added `channels_file` support for `tv_auto_scheduler.compare_canalplus`, defaulting to `/config/tv/channels.yaml`.
* Added `canalplus_id`-based channel mapping from YAML channel database entries.
* Added comparison summary counts for configured channels, Open EPG programmes, Canal+ programmes, and Canal+ fetch errors.
* Added `secondary_fetch_failed` comparison rows for channels whose Canal+ schedule fetch fails.
* Added a `note` column to Canal+ comparison reports for fetch-failure details.
* Added an example Home Assistant script for running Canal+ comparisons with a bearer token.
* Added an example channel database with `canalplus_id` values.

## :arrows_counterclockwise: Changed

* Made inline `canalplus_channels` optional and treated it as an override for channel IDs loaded from the channels file.
* Updated deployment to install the channel database only when it does not already exist.
* Updated deployment to copy the Canal+ comparison script example.

## :bug: Fixed

* Preserved partial Canal+ comparison reports when individual channel schedule fetches fail.
* Avoided misleading `missing_in_secondary` rows for channels that could not be fetched from Canal+.
* Included Canal+ HTTP error response snippets in raised errors to make failed API calls easier to diagnose.

## :memo: Documentation

* Updated README and service schema documentation for `channels_file`, debug logging, and Canal+ comparison failure behavior.
* Documented the scheduler source file with a module-level docstring.
* Added concise function docstrings throughout the scheduler source.
* Documented the DOX expectation that source files include file-level purpose comments and prudent function purpose/input/output comments.

## :wrench: Maintenance

* Added tests for loading Canal+ channel IDs from a channels file.
* Added tests for partial Canal+ comparison reports when one channel fetch fails.
* Added Canal+ and Open EPG fixture data used by comparison work.

## :white_check_mark: Validation

* `.venv/bin/python -m compileall custom_components tests scripts`
* `.venv/bin/python -m pytest tests`
* `bash -n scripts/deploy.sh`

## Upgrade notes

No manual migration is required. Existing inline `canalplus_channels` service data continues to work and now overrides entries loaded from `channels_file`.
