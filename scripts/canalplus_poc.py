#!/usr/bin/env python3
"""Proof-of-concept Canal+ client and browser-session helper."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None

API_BASE = "https://tvapi-hlm2.solocoo.tv/v1"
PROVIDER_ID = "canalplus"
DEFAULT_BROWSER_PROFILE_DIR = (
    Path.home() / ".cache" / "tv-auto-scheduler" / "canalplus-browser-profile"
)


@dataclass(frozen=True)
class NormalizedChannel:
    provider: str
    channel_id: str
    title: str
    lcn: int | None


@dataclass(frozen=True)
class NormalizedProgramme:
    provider: str
    programme_id: str
    channel_id: str
    channel_title: str
    channel_lcn: int | None
    title: str
    description: str
    start: datetime
    end: datetime
    restart: bool
    replay: bool
    recordable: bool
    series_id: str
    series_episode: int | None


@dataclass(frozen=True)
class CanalPlusClient:
    authorization: str
    origin: str = "https://play.canalplus.nl"
    referer: str = "https://play.canalplus.nl/"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        headers = {
            "Authorization": self.authorization,
            "Origin": self.origin,
            "Referer": self.referer,
        }

        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        request = Request(
            url,
            headers=headers,
            data=data,
            method=method,
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_bouquet(self) -> dict[str, Any]:
        return self._request_json("GET", "/bouquet")

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/assets/{asset_id}")

    def get_schedule(
        self,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            "/schedule",
            query={
                "channels": channel_id,
                "from": _format_api_datetime(start_at),
                "until": _format_api_datetime(end_at),
            },
        )

    def start_playback(self, asset_id: str) -> dict[str, Any]:
        # The traces show a JSON body with a "player" key.
        # The exact accepted value may change, so this remains a PoC placeholder.
        return self._request_json(
            "POST",
            f"/assets/{asset_id}/play",
            body={"player": "web"},
        )


@dataclass(frozen=True)
class BrowserSessionCanalPlusClient:
    page: Any

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        return self.page.evaluate(
            """async ({ url, method, body }) => {
                const options = {
                  method,
                  credentials: "include",
                };

                if (body !== null) {
                  options.headers = {
                    "Content-Type": "application/json",
                  };
                  options.body = JSON.stringify(body);
                }

                const response = await fetch(url, options);
                const text = await response.text();
                if (!response.ok) {
                  const snippet = text.length > 500 ? `${text.slice(0, 500)}...` : text;
                  throw new Error(
                    `HTTP Error ${response.status}: ${response.statusText}` +
                    (snippet ? `; response=${snippet}` : "")
                  );
                }

                return JSON.parse(text);
            }""",
            {"url": url, "method": method, "body": body},
        )

    def get_bouquet(self) -> dict[str, Any]:
        return self._request_json("GET", "/bouquet")

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/assets/{asset_id}")

    def get_schedule(
        self,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            "/schedule",
            query={
                "channels": channel_id,
                "from": _format_api_datetime(start_at),
                "until": _format_api_datetime(end_at),
            },
        )

    def start_playback(self, asset_id: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/assets/{asset_id}/play",
            body={"player": "web"},
        )


def normalize_channels(payload: dict[str, Any]) -> list[NormalizedChannel]:
    channels: list[NormalizedChannel] = []

    for item in payload.get("channels", []):
        asset_info = item.get("assetInfo") or {}
        params = asset_info.get("params") or {}

        channel_id = _clean_string(asset_info.get("id"))
        title = _clean_string(asset_info.get("title"))
        if not channel_id or not title:
            continue

        channels.append(
            NormalizedChannel(
                provider=PROVIDER_ID,
                channel_id=channel_id,
                title=title,
                lcn=_optional_int(params.get("lcn")),
            )
        )

    return sorted(
        channels,
        key=lambda channel: (channel.lcn is None, channel.lcn or 0, channel.title),
    )


def normalize_schedule(
    payload: dict[str, Any],
    channels: list[NormalizedChannel],
) -> list[NormalizedProgramme]:
    channel_lookup = {channel.channel_id: channel for channel in channels}
    programmes: list[NormalizedProgramme] = []

    epg = payload.get("epg") or {}
    for channel_id, items in epg.items():
        channel = channel_lookup.get(channel_id)
        channel_title = channel.title if channel else ""
        channel_lcn = channel.lcn if channel else None

        for item in items or []:
            params = item.get("params") or {}
            programme_id = _clean_string(item.get("id"))
            title = _clean_string(item.get("title"))
            start = _optional_datetime(params.get("start"))
            end = _optional_datetime(params.get("end"))
            if not programme_id or not title or start is None or end is None:
                continue

            programmes.append(
                NormalizedProgramme(
                    provider=PROVIDER_ID,
                    programme_id=programme_id,
                    channel_id=_clean_string(params.get("channelId")) or channel_id,
                    channel_title=channel_title,
                    channel_lcn=channel_lcn,
                    title=title,
                    description=_clean_string(item.get("description")),
                    start=start,
                    end=end,
                    restart=bool(params.get("restart")),
                    replay=bool(params.get("replay")),
                    recordable=bool(params.get("npvr")),
                    series_id=_clean_string(params.get("seriesId")),
                    series_episode=_optional_int(params.get("seriesEpisode")),
                )
            )

    return sorted(
        programmes,
        key=lambda programme: (
            programme.start,
            programme.channel_lcn is None,
            programme.channel_lcn or 0,
            programme.channel_title,
            programme.title,
        ),
    )


def build_normalized_epg(
    client: CanalPlusClient,
    start_at: datetime,
    end_at: datetime,
    channel_ids: list[str] | None = None,
) -> dict[str, Any]:
    bouquet = client.get_bouquet()
    channels = normalize_channels(bouquet)
    selected_channel_ids = channel_ids or [channel.channel_id for channel in channels]
    selected_id_set = set(selected_channel_ids)
    selected_channels = [
        channel for channel in channels if channel.channel_id in selected_id_set
    ]

    schedule_payload: dict[str, Any] = {"epg": {}}
    for channel_id in selected_channel_ids:
        channel_schedule = client.get_schedule(channel_id, start_at, end_at)
        schedule_payload["epg"].update(channel_schedule.get("epg") or {})

    programmes = normalize_schedule(schedule_payload, channels)

    return {
        "provider": PROVIDER_ID,
        "from": _format_api_datetime(start_at),
        "until": _format_api_datetime(end_at),
        "channels": [_to_jsonable(channel) for channel in selected_channels],
        "programmes": [_to_jsonable(programme) for programme in programmes],
    }


def _format_api_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # noqa: UP017
    return value.astimezone(timezone.utc).strftime(  # noqa: UP017
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _parse_datetime(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _to_jsonable(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.__dict__.items():
        if isinstance(item, datetime):
            result[key] = _format_api_datetime(item)
        else:
            result[key] = item
    return result


def _authorization_from_env() -> str:
    value = os.environ.get("CANALPLUS_AUTHORIZATION", "").strip()
    if not value:
        raise SystemExit(
            "Missing CANALPLUS_AUTHORIZATION environment variable.\n"
            "Expected a value copied from an authenticated browser request, or"
            " use the browser-session command for an interactive browser-backed"
            " flow."
        )
    return value


def _browser_session_client_from_args(
    login_url: str,
    profile_dir: str,
    headless: bool,
) -> tuple[BrowserSessionCanalPlusClient, Any, Any]:
    if sync_playwright is None:
        raise SystemExit(
            "Browser-session mode requires Playwright. Install it with:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    playwright = sync_playwright().start()
    browser_context = playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        viewport={"width": 1440, "height": 900},
    )
    page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
    page.goto(login_url, wait_until="domcontentloaded")
    print(
        "Open the browser window, complete Canal+ login if needed, then press Enter",
        file=sys.stderr,
    )
    input()
    return BrowserSessionCanalPlusClient(page=page), browser_context, playwright


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Proof-of-concept client for the private Canal+ web API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("bouquet", help="Fetch channel bouquet metadata.")

    asset_parser = subparsers.add_parser("asset", help="Fetch one asset by ID.")
    asset_parser.add_argument("asset_id")

    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Fetch EPG entries for one channel in a time window.",
    )
    schedule_parser.add_argument("channel_id")
    schedule_parser.add_argument(
        "start_at",
        help="ISO datetime, for example 2026-07-09T00:00:00+00:00",
    )
    schedule_parser.add_argument(
        "end_at",
        help="ISO datetime, for example 2026-07-10T00:00:00+00:00",
    )

    normalized_parser = subparsers.add_parser(
        "normalized-epg",
        help="Fetch bouquet and schedule data and emit normalized EPG rows.",
    )
    normalized_parser.add_argument(
        "start_at",
        help="ISO datetime, for example 2026-07-09T00:00:00+00:00",
    )
    normalized_parser.add_argument(
        "end_at",
        help="ISO datetime, for example 2026-07-10T00:00:00+00:00",
    )
    normalized_parser.add_argument(
        "--channel-id",
        action="append",
        dest="channel_ids",
        help=(
            "Limit extraction to one Canal+ channel ID. "
            "Can be supplied more than once."
        ),
    )

    play_parser = subparsers.add_parser(
        "play",
        help="Attempt to start playback for an asset.",
    )
    play_parser.add_argument("asset_id")

    browser_normalized_parser = subparsers.add_parser(
        "browser-normalized-epg",
        help=(
            "Fetch bouquet and schedule data through a local browser session and "
            "emit normalized EPG rows."
        ),
    )
    browser_normalized_parser.add_argument(
        "start_at",
        help="ISO datetime, for example 2026-07-09T00:00:00+00:00",
    )
    browser_normalized_parser.add_argument(
        "end_at",
        help="ISO datetime, for example 2026-07-10T00:00:00+00:00",
    )
    browser_normalized_parser.add_argument(
        "--channel-id",
        action="append",
        dest="channel_ids",
        help=(
            "Limit extraction to one Canal+ channel ID. "
            "Can be supplied more than once."
        ),
    )
    browser_normalized_parser.add_argument(
        "--browser-login-url",
        default="https://play.canalplus.nl/",
        help="Canal+ login URL to open in the browser session.",
    )
    browser_normalized_parser.add_argument(
        "--browser-profile-dir",
        default=str(DEFAULT_BROWSER_PROFILE_DIR),
        help=(
            "Persistent browser profile directory used to keep the Canal+ "
            "session local between runs."
        ),
    )
    browser_normalized_parser.add_argument(
        "--browser-headless",
        action="store_true",
        help=(
            "Run the browser headless. This is only useful when the persistent "
            "profile already contains a valid Canal+ session."
        ),
    )

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    browser_context = None
    playwright = None
    if args.command == "browser-normalized-epg":
        client, browser_context, playwright = _browser_session_client_from_args(
            args.browser_login_url,
            args.browser_profile_dir,
            args.browser_headless,
        )
    else:
        client = CanalPlusClient(authorization=_authorization_from_env())

    try:
        if args.command == "bouquet":
            payload = client.get_bouquet()
        elif args.command == "asset":
            payload = client.get_asset(args.asset_id)
        elif args.command == "schedule":
            payload = client.get_schedule(
                args.channel_id,
                _parse_datetime(args.start_at),
                _parse_datetime(args.end_at),
            )
        elif args.command == "normalized-epg":
            payload = build_normalized_epg(
                client,
                _parse_datetime(args.start_at),
                _parse_datetime(args.end_at),
                args.channel_ids,
            )
        elif args.command == "play":
            payload = client.start_playback(args.asset_id)
        elif args.command == "browser-normalized-epg":
            payload = build_normalized_epg(
                client,
                _parse_datetime(args.start_at),
                _parse_datetime(args.end_at),
                args.channel_ids,
            )
        else:
            raise SystemExit(f"Unsupported command: {args.command}")
    finally:
        if browser_context is not None:
            browser_context.close()
        if playwright is not None:
            playwright.stop()

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
