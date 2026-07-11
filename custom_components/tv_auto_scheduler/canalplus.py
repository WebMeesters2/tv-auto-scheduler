from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://tvapi-hlm2.solocoo.tv/v1"
PROVIDER_ID = "canalplus"


@dataclass(frozen=True)
class CanalPlusProgramme:
    provider: str
    programme_id: str
    channel_id: str
    channel_title: str
    channel_lcn: int | None
    title: str
    description: str
    start: datetime
    end: datetime


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
    ) -> Any:
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        request = Request(
            url,
            headers={
                "Authorization": self.authorization,
                "Origin": self.origin,
                "Referer": self.referer,
            },
            method=method,
        )
        try:
            with urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as err:
            body = err.read().decode("utf-8", errors="replace").strip()
            if len(body) > 500:
                body = f"{body[:500]}..."
            message = f"HTTP Error {err.code}: {err.reason}"
            if body:
                message = f"{message}; response={body}"
            raise RuntimeError(message) from err

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


def fetch_channel_schedule(
    client: CanalPlusClient,
    channel_id: str,
    start_at: datetime,
    end_at: datetime,
) -> list[CanalPlusProgramme]:
    payload = client.get_schedule(channel_id, start_at, end_at)
    programmes: list[CanalPlusProgramme] = []

    epg = payload.get("epg") or {}
    for item in epg.get(channel_id, []):
        if not isinstance(item, dict):
            continue

        params = item.get("params") or {}
        programme_id = _clean_string(item.get("id"))
        title = _clean_string(item.get("title"))
        start = _optional_datetime(params.get("start"))
        end = _optional_datetime(params.get("end"))
        if not programme_id or not title or start is None or end is None:
            continue

        programmes.append(
            CanalPlusProgramme(
                provider=PROVIDER_ID,
                programme_id=programme_id,
                channel_id=_clean_string(params.get("channelId")) or channel_id,
                channel_title="",
                channel_lcn=None,
                title=title,
                description=_clean_string(item.get("description")),
                start=start,
                end=end,
            )
        )

    return programmes


def _format_api_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # noqa: UP017
    return value.astimezone(timezone.utc).strftime(  # noqa: UP017
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
