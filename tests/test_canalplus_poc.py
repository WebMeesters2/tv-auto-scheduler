from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "canalplus_poc.py"


def load_canalplus_module():
    spec = importlib.util.spec_from_file_location("canalplus_poc", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Canal+ PoC script from {SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["canalplus_poc"] = module
    spec.loader.exec_module(module)
    return module


class FakeCanalPlusClient:
    def __init__(self) -> None:
        self.schedule_requests: list[tuple[str, datetime, datetime]] = []

    def get_bouquet(self) -> dict:
        return {
            "channels": [
                {
                    "assetInfo": {
                        "id": "npo1",
                        "title": "NPO 1 HD",
                        "params": {"lcn": 1},
                    },
                    "onlineEpg": True,
                },
                {
                    "assetInfo": {
                        "id": "rtl4",
                        "title": "RTL 4 HD",
                        "params": {"lcn": "4"},
                    },
                    "onlineEpg": True,
                },
            ]
        }

    def get_schedule(
        self,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> dict:
        self.schedule_requests.append((channel_id, start_at, end_at))
        return {
            "epg": {
                channel_id: [
                    {
                        "type": "EPG",
                        "id": f"{channel_id}-programme",
                        "title": "Evening News",
                        "description": "Daily news bulletin.",
                        "params": {
                            "start": "2026-07-09T18:00:00Z",
                            "end": "2026-07-09T18:30:00Z",
                            "channelId": channel_id,
                            "restart": True,
                            "replay": True,
                            "npvr": False,
                            "seriesId": "series-1",
                            "seriesEpisode": "12",
                        },
                    }
                ]
            }
        }


class FakeBrowserPage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def evaluate(self, script: str, payload: dict) -> dict:
        self.calls.append((script, payload))
        url = payload["url"]
        if url.endswith("/bouquet"):
            return FakeCanalPlusClient().get_bouquet()
        if "/schedule?" in url:
            channel_id = url.split("channels=")[1].split("&", 1)[0]
            return {
                "epg": {
                    channel_id: [
                        {
                            "id": f"{channel_id}-programme",
                            "title": "Evening News",
                            "params": {
                                "start": "2026-07-09T18:00:00Z",
                                "end": "2026-07-09T18:30:00Z",
                                "channelId": channel_id,
                            },
                        }
                    ]
                }
            }
        if "/assets/" in url:
            return {"ok": True}
        raise AssertionError(f"Unexpected browser request: {url}")


class CanalPlusPocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canalplus = load_canalplus_module()

    def test_normalize_channels_keeps_core_channel_fields(self) -> None:
        channels = self.canalplus.normalize_channels(
            FakeCanalPlusClient().get_bouquet()
        )

        self.assertEqual(channels[0].provider, "canalplus")
        self.assertEqual(channels[0].channel_id, "npo1")
        self.assertEqual(channels[0].title, "NPO 1 HD")
        self.assertEqual(channels[0].lcn, 1)
        self.assertEqual(channels[1].lcn, 4)

    def test_build_normalized_epg_outputs_jsonable_rows(self) -> None:
        client = FakeCanalPlusClient()
        start_at = datetime(2026, 7, 9, tzinfo=timezone.utc)  # noqa: UP017
        end_at = datetime(2026, 7, 10, tzinfo=timezone.utc)  # noqa: UP017

        payload = self.canalplus.build_normalized_epg(
            client,
            start_at,
            end_at,
            channel_ids=["rtl4"],
        )

        self.assertEqual(payload["provider"], "canalplus")
        self.assertEqual(payload["channels"][0]["channel_id"], "rtl4")
        self.assertEqual(payload["programmes"][0]["programme_id"], "rtl4-programme")
        self.assertEqual(payload["programmes"][0]["channel_title"], "RTL 4 HD")
        self.assertEqual(payload["programmes"][0]["start"], "2026-07-09T18:00:00.000Z")
        self.assertEqual(payload["programmes"][0]["series_episode"], 12)
        self.assertEqual(len(client.schedule_requests), 1)

    def test_browser_session_client_uses_page_evaluate(self) -> None:
        client = self.canalplus.BrowserSessionCanalPlusClient(FakeBrowserPage())
        start_at = datetime(2026, 7, 9, tzinfo=timezone.utc)  # noqa: UP017
        end_at = datetime(2026, 7, 10, tzinfo=timezone.utc)  # noqa: UP017

        payload = self.canalplus.build_normalized_epg(
            client,
            start_at,
            end_at,
            channel_ids=["rtl4"],
        )

        self.assertEqual(payload["channels"][0]["channel_id"], "rtl4")
        self.assertEqual(payload["programmes"][0]["programme_id"], "rtl4-programme")
        self.assertEqual(len(client.page.calls), 2)
        self.assertIn('credentials: "include"', client.page.calls[0][0])


if __name__ == "__main__":
    unittest.main()
