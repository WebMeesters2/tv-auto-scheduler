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
