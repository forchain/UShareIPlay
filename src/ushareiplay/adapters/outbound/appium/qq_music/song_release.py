from __future__ import annotations

import datetime as dt
import json
from typing import Any
from urllib import parse, request


def parse_release_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


class QQMusicSongReleaseLookup:
    SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def get_release_date(self, keyword: str) -> str | None:
        keyword = (keyword or "").strip()
        if not keyword:
            return None

        params = {
            "p": 1,
            "n": 1,
            "w": keyword,
            "format": "json",
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://y.qq.com/",
        }
        url = f"{self.SEARCH_URL}?{parse.urlencode(params)}"
        req = request.Request(url, headers=headers)
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        songs = payload.get("data", {}).get("song", {}).get("list", [])
        if not songs:
            return None
        return self._date_from_timestamp(songs[0].get("pubtime"))

    @staticmethod
    def _date_from_timestamp(value: Any) -> str | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None

        china_time = dt.timezone(dt.timedelta(hours=8))
        return dt.datetime.fromtimestamp(timestamp, tz=china_time).date().isoformat()
