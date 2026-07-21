# TV Auto Scheduler Handover

## Current Focus

The Canal+ investigation now has two separate pieces:

1. `tv_auto_scheduler.compare_canalplus` runs inside Home Assistant and compares Canal+ schedules with the Open EPG sensors that already exist in HA.
2. `scripts/canalplus_poc.py browser-normalized-epg` runs a local browser-session helper for the Canal+ side only.

The WSL/browser helper does not have direct access to HA Open EPG entities. For the actual comparison workflow, HAOS remains the place where the service runs.

## What Is Already In Place

- Canal+ comparison service in the custom component.
- Token-based Canal+ client path for the comparison service.
- Browser-session Canal+ PoC mode.
- A local add-on scaffold at `addons/canalplus-browser` that packages Playwright and Chromium as a runtime base.
- A wrapper script at `scripts/run_canalplus_browser_container.sh` for local container use.
- An HA export service, `tv_auto_scheduler.export_open_epg`, that writes the current Open EPG snapshot to `/config/tv_auto_scheduler/open_epg_snapshot.json`.
- A file-based comparison helper, `scripts/compare_open_epg_canalplus_exports.py`, that compares the HA Open EPG export against the Canal+ browser JSON export.
- Documentation updates in `README.md`, `docs/canalplus-handover.md`, and `addons/canalplus-browser/README.md`.

## HAOS Add-on State

- The add-on scaffold is intentionally idle by default.
- It packages the browser runtime separately from HAOS.
- It does not yet run the repo-root PoC script by itself.

## Important Constraint

The browser helper can fetch Canal+ data, but it cannot see HA Open EPG sensors unless a separate HA API bridge is added.

## Next Step

Use the exported Open EPG snapshot as the bridge point for external comparison tooling. The new file-based comparison script can now compare the HA snapshot with the Canal+ browser JSON output outside HA.

## Useful Commands

- Deploy the integration to HA: `scripts/deploy.sh`
- Validate the browser wrapper: `bash -n scripts/run_canalplus_browser_container.sh`
- Run the Canal+ PoC tests: `.venv/bin/python -m unittest tests.test_canalplus_poc`

## Notes For Resume

- If the session is resumed in Codex CLI or GUI, start from this file and the docs under `docs/canalplus-handover.md`.
- The add-on scaffold is not yet the final solution; it is a stable runtime base.

## Final status before session full

Noted. The current state is preserved in `HANDOVER.md`, and the workflow split is documented in `README.md` and `canalplus-handover.md`.

For the next session, start from `HANDOVER.md` and continue with the file-based bridge:

1. Export Open EPG from HA with tv_auto_scheduler.export_open_epg.
2. Produce the Canal+ browser JSON snapshot.
3. Run compare_open_epg_canalplus_exports.py against both files.
