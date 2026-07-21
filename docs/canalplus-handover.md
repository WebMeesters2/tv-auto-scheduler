# Canal+ Handover

## Goal

Investigate whether Canal+ (`play.canalplus.nl`) can be used as:

- an alternate authenticated EPG source
- a source of programme metadata
- a source of optional provider-specific actions such as:
  - start playback
  - reminders
  - recordings
  - bookmarks

This work is intended to run in parallel to the existing Open EPG direction.

## What Has Already Been Established

### Main private API host

- `https://tvapi-hlm2.solocoo.tv/v1/...`

### Confirmed endpoint groups

- Bouquet / channel metadata
- Schedule / EPG
- Asset details
- Related content / episodes
- Start playback
- Reminders
- Recordings
- Bookmarks

### Not confirmed as a clean backend API

- Pause
- Resume
- Seek
- General transport-style media player control

The traces suggest that playback transport is mostly handled inside the browser player and media session, not by a neat public-style remote-control endpoint.

## Files Added In This Investigation

- [canalplus-private-api.md](/home/ruben/projects/tv-auto-scheduler/docs/canalplus-private-api.md)
- [canalplus_poc.py](/home/ruben/projects/tv-auto-scheduler/scripts/canalplus_poc.py)

## Key Conclusions So Far

1. Canal+ looks promising as an authenticated EPG/provider source.
2. The EPG path is strong enough to prototype:
   - channel listing
   - schedule retrieval
   - asset details
3. Playback initiation appears feasible through:
   - `POST /v1/assets/{asset_id}/play`
4. Full player transport control does not currently look like a good backend-only target.
5. Session/auth handling is the main technical risk:
   - browser bootstrap
   - `ssoToken`
   - `Authorization` header
   - likely token expiry/refresh

## Recommended Direction

Treat Canal+ as a provider with:

- required capabilities:
  - channels
  - schedule
  - asset details
- optional capabilities:
  - play
  - remind
  - record
  - bookmark

Do not design around pause/seek/resume unless later evidence shows a distinct control API.

## Next Good Steps

### Option 1: Normalize EPG

Create a small script that:

- calls bouquet
- calls schedule
- maps Canal+ channel IDs to titles / LCN values
- outputs normalized programme rows

This is the best next step if the priority is EPG integration.

### Option 2: Provider abstraction

Draft a provider interface that can sit beside the existing Open EPG path, for example:

- `list_channels()`
- `get_schedule(channel_id, start_at, end_at)`
- `get_asset(asset_id)`
- optional `play_asset(asset_id)`

This is the best next step if the priority is architecture.

### Option 3: Session/auth investigation

Document how the browser session is bootstrapped and whether it can be reproduced safely outside the browser.

This is the best next step if the priority is turning the PoC into something runnable.

## Current PoC Notes

The PoC script supports two modes:

- manual `CANALPLUS_AUTHORIZATION`

  via environment variable, copied from an authenticated browser request.

- `browser-normalized-epg`

  which opens a local Playwright browser profile, waits for you to finish login,
  and then reuses that session locally without surfacing the bearer token.

  For HAOS or other locked-down environments, the repository now also ships a
  dedicated add-on scaffold in `addons/canalplus-browser` and a wrapper script
  at `scripts/run_canalplus_browser_container.sh`. That keeps Playwright and
  Chromium outside the HAOS host while preserving the same browser-backed flow.

  HAOS install procedure for that scaffold:

  1. Expose the HAOS `/addons` share, for example with Samba or Studio Code Server.
  2. Copy `addons/canalplus-browser` to `/addons/canalplus-browser` on the HAOS host.
  3. In Home Assistant, open **Settings > Add-ons** and reload the add-on list if needed.
  4. Open the local Canal+ Browser Helper add-on, install it, and start it.

  The scaffold is intentionally idle by default. It is a packaged runtime base, not a finished interactive add-on yet, so the browser-session helper remains the primary way to use it right now.

  The helper only covers the Canal+ fetch side of the workflow. It does not have access to Home Assistant Open EPG entities unless you build a separate HA API bridge. For comparison against the Open EPG sensors already in HA, keep using the `tv_auto_scheduler.compare_canalplus` service inside Home Assistant.

## HA Bridge

If you want an external tool to participate without losing the Open EPG data that lives in Home Assistant, use the `tv_auto_scheduler.export_open_epg` service to write a JSON snapshot to `/config/tv_auto_scheduler/open_epg_snapshot.json`. That file is the current bridge point for WSL or the container-based helper.

To compare the exported HA snapshot with Canal+ outside HA, use `scripts/compare_open_epg_canalplus_exports.py` against the HA JSON export and the Canal+ `browser-normalized-epg` JSON output.

The token-based path is still available for direct comparison work, but the
browser-session path is the easier option when you want to avoid manual copy
and paste. Both remain research/prototype level.

## Normalized EPG Prototype

The PoC script now includes a normalized extraction command:

    python scripts/canalplus_poc.py normalized-epg 2026-07-09T00:00:00+00:00 2026-07-10T00:00:00+00:00 --channel-id <canalplus-channel-id>

The --channel-id option is optional and can be supplied more than once. Without it, the PoC fetches schedule data for all channels returned by the bouquet endpoint.

The normalized JSON output includes provider, from, until, channels, and programmes. Channel rows contain provider, channel_id, title, and lcn. Programme rows contain channel metadata, programme IDs, titles, UTC start/end values, and capability flags for restart, replay, and recording.

## Comparison Layer

A first comparison core now exists in custom_components/tv_auto_scheduler/epg_compare.py. It is intentionally source-neutral and does not change scheduler behaviour yet.

It compares primary Open EPG-style programmes with secondary Canal+ programmes and classifies results as:

- confirmed
- missing_in_primary
- missing_in_secondary
- time_mismatch
- duration_mismatch
- title_mismatch
- replaced

The comparator treats broadcaster suffixes such as (NOS) and clock labels such as 20.00 uur as weak title evidence, so equal time slots with only that kind of title difference can still confirm. Strong time-slot evidence can classify a real replacement even when titles differ.

The comparison module is now wired into an experimental report-only Home Assistant service: tv_auto_scheduler.compare_canalplus. It scans the existing Open EPG sensors, fetches mapped Canal+ schedules with a manually supplied bearer token, and can write a CSV discrepancy report. A known follow-up is one-to-many handling for cases where Canal+ splits one broad Open EPG block into several detailed segments.

## Suggested Restart Prompt

If starting a fresh chat, a good opener would be:

> Continue the Canal+ provider investigation in `tv-auto-scheduler`. Please read `docs/canalplus-handover.md` and `docs/canalplus-private-api.md`, then help me take the next step toward either normalized EPG extraction or a provider abstraction alongside Open EPG.
