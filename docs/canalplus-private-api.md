# Canal+ Private API Notes

## Purpose

This note captures the current findings from browser HAR traces against `play.canalplus.nl`.

The goal is to assess whether Canal+ can be used as:

- an alternate EPG source
- a source of programme metadata
- a trigger point for reminders, recordings, bookmarks, and playback

This is based on observed browser traffic and should be treated as unofficial and potentially unstable.

## Host Overview

The browser app uses:

- `https://play.canalplus.nl/` for the frontend
- `https://tvapi-hlm2.solocoo.tv/v1/...` for account and content APIs
- `https://license.solocoo.tv/...` for DRM license requests
- `https://nl-bkm100-prod-live.solocoo.tv/...` and `https://nl-bks...solocoo.tv/...` for media manifests and segments
- `https://bkastats.solocoo.tv/...` for playback metrics

## Endpoint Table

| Purpose | Method | Endpoint pattern | Notes |
| --- | --- | --- | --- |
| Provision session bootstrap | `POST` | `/v1/provision` | Seen before session creation |
| Create API session | `POST` | `/v1/session` | Requires browser-side session bootstrap, includes `ssoToken` in body |
| Current profile | `GET` | `/v1/profile` | Authenticated |
| Settings | `GET` | `/v1/settings` | Authenticated |
| Members | `GET` | `/v1/members` | Authenticated |
| Entitlements | `GET` | `/v1/entitlements` | Authenticated |
| Channel bouquet | `GET` | `/v1/bouquet` | Contains channel metadata including Canal+ channel IDs |
| Schedule / EPG | `GET` | `/v1/schedule?channels=<id>&from=<iso>&until=<iso>` | Main EPG endpoint |
| Asset details | `GET` | `/v1/assets/{asset_id}` | Programme or channel metadata |
| Related content | `GET` | `/v1/collections/related?...` | Detail view support |
| Episode list | `GET` | `/v1/collections/episodes?...` | Series/episode detail support |
| Markers | `GET` | `/v1/markers` | Seen on detail pages |
| Recordings list | `GET` | `/v1/recordings` | Current recording state |
| Favourites | `GET` | `/v1/favourites` | Account feature |
| Bookmarks list | `GET` | `/v1/bookmarks` | Account feature |
| Reminders list | `GET` | `/v1/reminders` | Account feature |
| Start playback | `POST` | `/v1/assets/{asset_id}/play` | Used for both live and replay |
| Add reminder | `POST` | `/v1/assets/{asset_id}/remind` | Adds reminder |
| Remove reminder | `POST` | `/v1/reminders` | Uses delete payload |
| Start single recording | `POST` | `/v1/assets/{asset_id}/record?series=false` | Single programme recording |
| Start series recording | `POST` | `/v1/assets/{asset_id}/record?series=true` | Series recording |
| Remove single recording | `POST` | `/v1/recordings` | Uses delete payload |
| Remove series recording | `DELETE` | `/v1/recordings/scheduledSeries/{asset_id}` | Removes scheduled series recording |
| Add bookmark | `POST` | `/v1/bookmarks` | Uses add payload |
| Remove bookmark | `POST` | `/v1/bookmarks` | Uses delete payload |
| Playback stats | `POST` | `/v1/stats` | Telemetry, not needed for EPG use |

## EPG Structure

### Bouquet

`GET /v1/bouquet` returns a `channels` collection.

Observed channel object shape:

```json
{
  "assetInfo": {
    "type": "Channel",
    "id": "9zhabdaigZd4WCwrn1Yyl7LtviNAKEgAgG6ysNpd",
    "title": "NPO 1 HD",
    "params": {
      "lcn": 1,
      "restart": true,
      "replay": true,
      "npvr": true
    }
  },
  "onlineEpg": true,
  "disableHbb": true,
  "sources": [
    {
      "type": "ott",
      "params": ""
    }
  ]
}
```

Useful fields:

- `assetInfo.id`
- `assetInfo.title`
- `assetInfo.params.lcn`

### Schedule

`GET /v1/schedule?...` returns an `epg` object keyed by channel ID.

Observed programme item shape:

```json
{
  "type": "EPG",
  "id": "Jew2bPzXDZsvBGDid4_Bf2lUjpMTXaHmLS1AmpYL",
  "title": "NOS De Avondetappe (NOS)",
  "images": [],
  "deals": [],
  "metadataLanguage": "nl",
  "params": {
    "start": "2026-07-08T21:30:00Z",
    "end": "2026-07-08T22:20:00Z",
    "channelId": "9zhabdaigZd4WCwrn1Yyl7LtviNAKEgAgG6ysNpd",
    "seriesId": "0cKRZdTCIJmS7zokk3EqybFKRc-OyVdsVxVCKFwK",
    "seriesEpisode": 3,
    "restart": true,
    "replay": true,
    "npvr": true,
    "age": 0,
    "genres": [],
    "formats": []
  }
}
```

Useful fields:

- `id`
- `title`
- `params.start`
- `params.end`
- `params.channelId`
- `params.restart`
- `params.replay`
- `params.npvr`

## Playback Findings

Playback is not controlled through a rich remote-control API.

Observed model:

1. Browser requests `POST /v1/assets/{id}/play`
2. API returns data that leads to DASH manifest playback
3. Browser fetches:
   - `index.mpd`
   - media segments
   - Widevine license
   - keepalive and teardown URLs

Observed:

- playback start is API-driven
- pause/resume was not exposed as a distinct API endpoint
- seek operations were not exposed as a distinct API endpoint
- "back to live" appears to create a new playback session rather than call a dedicated seek/live-edge endpoint

## Recommendation

### Strong candidate for integration

Canal+ looks promising for:

- EPG retrieval
- programme detail lookup
- reminders
- recordings
- bookmarks
- initiating playback

### Weak candidate for full player control

Canal+ does not currently look promising for:

- pause / resume
- seek
- true media-player style transport control

Those actions seem to remain inside the browser's playback session rather than a neat backend control API.

### Recommended project direction

1. Treat Canal+ as an alternate authenticated EPG/provider source, parallel to the Open EPG path.
2. Keep the provider abstraction centred on:
   - channel list
   - schedule retrieval
   - asset detail lookup
3. Treat playback/reminders/recordings as optional provider-specific capabilities.
4. Do not design around full web-player transport control unless a later trace exposes it clearly.

## Risks

- Private API, not documented
- Authentication/session bootstrap may change
- Tokens likely expire and require refresh logic
- DRM/media playback is browser/device dependent
- Any direct integration may break without notice
