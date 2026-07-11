# Release Notes

## 2026-07-11

### Canal+ Comparison

- Added `channels_file` support for `tv_auto_scheduler.compare_canalplus`, defaulting to `/config/tv/channels.yaml`.
- Made inline `canalplus_channels` optional and treated it as an override for channel IDs loaded from the channels file.
- Added `canalplus_id`-based channel mapping from YAML channel database entries.
- Added comparison summary counts for configured channels, Open EPG programmes, Canal+ programmes, and Canal+ fetch errors.
- Added partial-report behavior when a Canal+ channel schedule fetch fails: failed channels are reported as `secondary_fetch_failed` instead of turning the whole comparison into misleading missing-secondary rows.
- Included Canal+ HTTP error response snippets in raised errors to make failed API calls easier to diagnose.
- Added a `note` column to Canal+ comparison reports for fetch-failure details.

### Examples and Deployment

- Added an example Home Assistant script for running Canal+ comparisons with a bearer token.
- Added an example channel database with `canalplus_id` values.
- Updated deployment to install the channel database only when it does not already exist, and to deploy the Canal+ comparison script example.
- Updated README and service schema documentation for `channels_file`, debug logging, and Canal+ comparison failure behavior.

### Scheduler Source Documentation

- Documented the scheduler source file with a module-level docstring.
- Added concise function docstrings throughout the scheduler source.
- Documented the DOX expectation that source files include file-level purpose comments and prudent function purpose/input/output comments.

### Tests and Fixtures

- Added tests for loading Canal+ channel IDs from a channels file.
- Added tests for partial Canal+ comparison reports when one channel fetch fails.
- Added Canal+ and Open EPG fixture data used by comparison work.
