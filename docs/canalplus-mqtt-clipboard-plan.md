# Canal+ MQTT Clipboard Bridge Plan

## Purpose

Provide a convenient one-click path from the native Windows TV Channel Display
application to the existing Home Assistant Canal+ comparison service.

The intended workflow is:

1. Copy a fresh Canal+ authorization value from an authenticated browser request.
2. Click a button in TV Channel Display.
3. The Windows app reads the clipboard once.
4. The Windows app publishes the authorization value to MQTT.
5. Home Assistant receives the MQTT message and calls script.compare_canalplus_epg.

This avoids browser-dashboard clipboard restrictions while keeping the comparison
logic inside Home Assistant, where the Open EPG sensors already live.

## Workspace Setup

The TV Channel Display repository lives at:

- Windows path: D:\Users\Ruben\WMDATA\Projects\HA\tv-channel-display
- WSL view: /mnt/d/Users/Ruben/WMDATA/Projects/HA/tv-channel-display
- UNC WSL path: //wsl.localhost/Ubuntu-22.04/mnt/d/Users/Ruben/WMDATA/Projects/HA/tv-channel-display

For Codex workspace access, prefer adding the Windows path. It is a native
Windows/.NET project, and the WSL UNC path may not be writable or even readable
from the current Codex sandbox. Keep tv-auto-scheduler as the Home Assistant
integration workspace and add TV Channel Display as a second workspace root when
implementation starts.

## MQTT Contract

Use a narrow topic dedicated to this bridge:

    tv_auto_scheduler/canalplus/compare/request

Payload format:

    {
      "canalplus_authorization": "<fresh Authorization header or bearer token>",
      "source": "tv-channel-display",
      "requested_at": "2026-08-12T12:00:00Z"
    }

Only canalplus_authorization is required. The receiver should accept either a
full Authorization: Bearer ... value or a bare bearer token and pass it to
script.compare_canalplus_epg. That script owns the service call, report filename,
filter settings, and notification behavior.

Do not log the payload or persist the token. It should exist only long enough to
publish the MQTT message and run the comparison.

## Home Assistant Receiver

The Home Assistant side is an automation that bridges MQTT to the existing
script. The automation should not duplicate comparison settings, report naming,
or notification behavior:

    alias: Canal+ Compare From TV Channel Display
    mode: single
    triggers:
      - trigger: mqtt
        topic: tv_auto_scheduler/canalplus/compare/request
    conditions:
      - condition: template
        value_template: >
          {{ (trigger.payload_json.canalplus_authorization
              | default(trigger.payload_json.bearer_token, true)
              | default("", true)
              | trim) != "" }}
    actions:
      - action: script.compare_canalplus_epg
        data:
          bearer_token: >
            {{ trigger.payload_json.canalplus_authorization
               | default(trigger.payload_json.bearer_token, true) }}

Implementation notes:

- Keep comparison report paths, filters, and notifications in
  script.compare_canalplus_epg.
- Keep the MQTT receiver focused on validating the payload and passing the token
  into the script.
- Add a guard before implementation if invalid JSON should produce a persistent
  notification instead of a failed automation trace.

## TV Channel Display Changes

Implement this in the Windows app after adding the repository as a Codex
workspace root.

Planned changes:

1. Locate the existing MQTT publishing code and configuration model.
2. Add configurable values for:
   - enable or disable Canal+ compare button
   - MQTT request topic
3. Add a UI command/button named for the Canal+ comparison action.
4. On click:
   - read text from the Windows clipboard
   - trim whitespace
   - reject empty clipboard content with a local status message
   - publish the JSON payload to the configured MQTT topic
   - clear the token variable after publish
5. Show success/failure status without showing the token itself.

Prefer reusing the existing MQTT client and UI/status patterns. Do not add new
dependencies unless the app currently lacks MQTT publishing support.

## Security Notes

- MQTT must be treated as carrying a secret for this one message.
- Avoid retained messages for this topic.
- Avoid MQTT logging of payload bodies.
- Prefer authenticated MQTT and TLS if the broker setup supports it.
- Do not store the bearer token in app settings, Home Assistant secrets, files,
  traces, or release notes.

## Validation Plan

For TV Channel Display:

- Build the .NET project.
- Verify the button is hidden or disabled when MQTT is not configured.
- Verify an empty clipboard produces a local warning and no MQTT publish.
- Verify a non-empty clipboard publishes one non-retained MQTT message.

For tv-auto-scheduler:

- Validate the automation YAML in Home Assistant.
- Publish a test MQTT message with a harmless placeholder token and confirm the
  automation calls the expected service path.
- Run python -m compileall . if any integration code changes are made.

## Open Decisions

- Whether the receiver should be an example automation only, or built into the
  integration as an MQTT listener.
- Whether to send optional report/filter settings from TV Channel Display or keep
  them fixed in script.compare_canalplus_epg.
